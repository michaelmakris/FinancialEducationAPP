"""
Personal access keys for AI assistants (the MCP server), and the internal
endpoint the MCP server uses to check them.

  /bff/auth/access-keys            customer: list, create (password + MFA code), revoke
  /bff/internal/introspect         MCP server only: is this key valid, for whom, with which scopes?

The internal endpoint is not reachable with a session or an access key: the
caller must present a 60-second JWT signed with a key listed in
BFF_INTERNAL_CALLERS (the MCP server's Ed25519 key), audience "bff-internal".
"""
from __future__ import annotations

import datetime
import time
from functools import lru_cache
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from prometheus_client import Counter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from . import mailer, mfa, security
from .config import settings
from .db import get_db
from .models import AccessKey, Customer, utcnow
from .sessions import Current, audit, current, current_with_csrf

router = APIRouter(tags=["access keys"])
INTROSPECTIONS = Counter("bff_introspections_total", "Access-key checks from internal services", ["result"])

KEY_PREFIX = "fea_mcp_"
# Access levels a customer can grant an assistant. Never "chat" or "ops:read".
LEVELS = {
    "read": "market:read portfolio:read",
    "trade": "market:read portfolio:read portfolio:write",
}
_TOUCH_EVERY = datetime.timedelta(minutes=5)


class CreateKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    level: str = Field(pattern="^(read|trade)$")
    days: int = Field(30, ge=1, le=365)
    password: str = Field(max_length=security.PASSWORD_MAX * 4)
    code: str | None = Field(None, max_length=20)


def _key_out(k: AccessKey) -> dict:
    level = next((lvl for lvl, s in LEVELS.items() if s == k.scopes), "custom")
    return {"id": k.id[:16], "name": k.name, "prefix": k.prefix, "level": level, "scopes": k.scopes.split(),
            "created_at": k.created_at, "expires_at": k.expires_at, "last_used_at": k.last_used_at}


def _active_keys(db: DB, customer_id: str) -> list[AccessKey]:
    now = utcnow()
    return list(db.execute(select(AccessKey).where(
        AccessKey.customer_id == customer_id, AccessKey.revoked_at.is_(None), AccessKey.expires_at > now,
    ).order_by(AccessKey.created_at.desc())).scalars())


@router.get("/bff/auth/access-keys")
def list_keys(cur: Current = Depends(current), db: DB = Depends(get_db)):
    return [_key_out(k) for k in _active_keys(db, cur.customer.id)]


@router.post("/bff/auth/access-keys", status_code=201)
def create_key(body: CreateKeyIn, request: Request, bg: BackgroundTasks,
               cur: Current = Depends(current_with_csrf), db: DB = Depends(get_db)):
    c = cur.customer
    if settings.require_mfa and not c.mfa_enabled:
        raise HTTPException(403, "mfa_enrollment_required")
    # Step-up: a key outlives the session, so re-check the password (and the MFA code if on).
    if not security.verify_password(c.password_hash, body.password):
        audit(db, request, "access_key_create_failed", c.id, c.email)
        db.commit()
        raise HTTPException(403, "Password is incorrect")
    if c.mfa_enabled and not (body.code and mfa.check_code(c, body.code)):
        raise HTTPException(422, "Enter the current code from your authenticator app")
    if body.days > settings.access_key_max_days:
        raise HTTPException(422, f"Keys can last at most {settings.access_key_max_days} days")
    if len(_active_keys(db, c.id)) >= settings.access_key_max_active:
        raise HTTPException(409, f"You already have {settings.access_key_max_active} active keys. Revoke one first.")
    raw = KEY_PREFIX + security.new_token()
    key = AccessKey(id=security.sha256_hex(raw), customer_id=c.id, name=" ".join(body.name.split()),
                    prefix=raw[:12], scopes=LEVELS[body.level],
                    expires_at=utcnow() + datetime.timedelta(days=body.days))
    db.add(key)
    audit(db, request, "access_key_created", c.id, c.email, detail=f"{key.prefix} {body.level} {body.days}d '{key.name}'")
    bg.add_task(mailer.deliver, "security_notice", c.email,
                *mailer.security_notice(c.full_name, f"An AI assistant access key ('{key.name}', {body.level} access) was created"))
    db.commit()
    return {**_key_out(key), "key": raw}  # the only time the full key is shown


@router.delete("/bff/auth/access-keys/{public_id}", status_code=204)
def revoke_key(public_id: str, request: Request, cur: Current = Depends(current_with_csrf), db: DB = Depends(get_db)):
    match = [k for k in _active_keys(db, cur.customer.id) if k.id[:16] == public_id]
    if len(public_id) != 16 or not match:
        raise HTTPException(404, "No such key")
    match[0].revoked_at = utcnow()
    audit(db, request, "access_key_revoked", cur.customer.id, cur.customer.email, detail=match[0].prefix)
    db.commit()


# ---------------------------------------------------------------- internal: MCP server checks a key
class IntrospectIn(BaseModel):
    key: str = Field(max_length=200)


@lru_cache(maxsize=1)
def _internal_keys() -> dict:
    keys = {}
    for part in filter(None, (p.strip() for p in settings.internal_callers.split(","))):
        name, _, path = part.partition("=")
        p = Path(path.strip())
        if name and p.exists():
            keys[name.strip()] = load_pem_public_key(p.read_bytes())
    return keys


def _internal_caller(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Internal endpoint")
    try:
        issuer = jwt.decode(token, options={"verify_signature": False}).get("iss")
        key = _internal_keys().get(issuer)
        if key is None or jwt.get_unverified_header(token).get("alg") != "EdDSA":
            raise jwt.InvalidTokenError("untrusted caller")
        claims = jwt.decode(token, key, algorithms=["EdDSA"], audience="bff-internal", issuer=issuer, leeway=10,
                            options={"require": ["exp", "iat", "iss", "aud"]})
        if claims["exp"] - claims["iat"] > 120:
            raise jwt.InvalidTokenError("lifetime")
    except jwt.PyJWTError:
        INTROSPECTIONS.labels("caller_rejected").inc()
        raise HTTPException(401, "Internal endpoint")
    return issuer


@router.post("/bff/internal/introspect", include_in_schema=False)
def introspect(body: IntrospectIn, caller: str = Depends(_internal_caller), db: DB = Depends(get_db)):
    inactive = {"active": False}
    if not body.key.startswith(KEY_PREFIX):
        INTROSPECTIONS.labels("inactive").inc()
        return inactive
    k = db.get(AccessKey, security.sha256_hex(body.key))
    now = utcnow()
    if k is None or k.revoked_at is not None or now >= k.expires_at:
        INTROSPECTIONS.labels("inactive").inc()
        return inactive
    c = db.get(Customer, k.customer_id)
    if c is None or c.status != "active" or not c.email_verified or (settings.require_mfa and not c.mfa_enabled):
        INTROSPECTIONS.labels("inactive").inc()
        return inactive
    allowed = set(security.ROLE_SCOPES.get(c.role, security.ROLE_SCOPES["customer"]).split())
    scopes = [s for s in k.scopes.split() if s in allowed]  # never more than the customer has
    if k.last_used_at is None or now - k.last_used_at > _TOUCH_EVERY:
        k.last_used_at = now
        db.commit()
    INTROSPECTIONS.labels("active").inc()
    return {"active": True, "customer_id": c.id, "scopes": scopes, "key_id": k.id[:16], "key_prefix": k.prefix,
            "expires_at": int(k.expires_at.replace(tzinfo=datetime.timezone.utc).timestamp()), "checked_at": int(time.time())}
