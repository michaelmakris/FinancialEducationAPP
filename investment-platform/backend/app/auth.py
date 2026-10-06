"""
Caller authentication for the API. The API is never called by browsers
directly: the BFF (../bff) authenticates the customer, then calls the API with
a short-lived token it signs with its Ed25519 key:

    Authorization: Bearer <JWT, alg EdDSA, iss=bff, aud=investment-api, sub=<customer id>,
                           scope="market:read portfolio:read ...", exp <= iat + 300s>

The API trusts only the issuers listed in API_TRUSTED_ISSUERS ("bff=/path/pub.pem,mcp=/path/pub.pem"),
each with its own public key -- so the API can verify tokens but never mint them.

Scopes:
    market:read      market data, demo analytics, simulations
    portfolio:read   own virtual portfolio and watchlist
    portfolio:write  trade / reset / edit watchlist on own portfolio
    chat             AI assistant
    ops:read         data-status (staff only)

API_AUTH_MODE=disabled turns all of this off for local development only; every
request then runs as the fixed principal "dev-local" with all scopes.
"""
from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import jwt
from fastapi import HTTPException, Request
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from .config import settings

log = logging.getLogger("auth")

ALL_SCOPES = frozenset({"market:read", "portfolio:read", "portfolio:write", "chat", "ops:read"})
MAX_TOKEN_LIFETIME_S = 300
LEEWAY_S = 10


@dataclass(frozen=True)
class Principal:
    subject: str            # customer id (or "dev-local")
    issuer: str             # bff | mcp | dev
    scopes: frozenset
    token: str | None       # raw bearer token, forwarded on internal API calls


_current: contextvars.ContextVar[Principal | None] = contextvars.ContextVar("principal", default=None)


class AuthConfigError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def trusted_keys() -> dict[str, object]:
    """{issuer: Ed25519 public key} from API_TRUSTED_ISSUERS."""
    keys = {}
    for part in filter(None, (p.strip() for p in settings.api_trusted_issuers.split(","))):
        issuer, _, path = part.partition("=")
        if not issuer or not path:
            raise AuthConfigError(f"API_TRUSTED_ISSUERS entry '{part}' must look like issuer=/path/to/public.pem")
        keys[issuer.strip()] = load_pem_public_key(Path(path.strip()).read_bytes())
    return keys


def verify_token(token: str) -> Principal:
    """Raises HTTPException(401) for anything that is not a valid, current token from a trusted issuer."""
    def deny(reason: str):
        log.info("rejected token: %s", reason)
        return HTTPException(401, "Invalid or expired credentials", headers={"WWW-Authenticate": "Bearer"})

    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise deny("malformed")
    issuer = unverified.get("iss")
    try:
        key = trusted_keys().get(issuer)
    except (AuthConfigError, OSError) as e:
        log.error("API auth misconfigured: %s", e)
        raise HTTPException(503, "API authentication is not configured")
    if key is None:
        raise deny(f"untrusted issuer {issuer!r}")
    if header.get("alg") != "EdDSA":
        raise deny("unexpected alg")
    try:
        claims = jwt.decode(
            token, key, algorithms=["EdDSA"], audience=settings.api_audience, issuer=issuer, leeway=LEEWAY_S,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError as e:
        raise deny(type(e).__name__)
    if claims["exp"] - claims["iat"] > MAX_TOKEN_LIFETIME_S:
        raise deny("lifetime too long")
    scopes = frozenset(str(claims.get("scope", "")).split()) & ALL_SCOPES
    return Principal(subject=str(claims["sub"]), issuer=issuer, scopes=scopes, token=token)


def require(*needed: str):
    """FastAPI dependency: authenticate the caller and require all `needed` scopes.

    Declared async on purpose: it runs in the request's own context, so the
    ContextVar it sets is visible to the (threadpool) endpoint and to the chat
    agents' internal API calls, which forward the same token."""
    needed_set = frozenset(needed)

    async def dependency(request: Request) -> Principal:
        if settings.api_auth_mode == "disabled":
            principal = Principal(subject="dev-local", issuer="dev", scopes=ALL_SCOPES, token=None)
        else:
            auth = request.headers.get("authorization", "")
            scheme, _, token = auth.partition(" ")
            if scheme.lower() != "bearer" or not token:
                raise HTTPException(401, "Missing bearer token", headers={"WWW-Authenticate": "Bearer"})
            principal = verify_token(token.strip())
        missing = needed_set - principal.scopes
        if missing:
            raise HTTPException(403, f"Missing scope(s): {', '.join(sorted(missing))}")
        request.state.principal = principal
        _current.set(principal)
        return principal

    return dependency


def current_principal() -> Principal | None:
    return _current.get()


def outbound_headers() -> dict[str, str]:
    """Headers for the API calling itself (chat agents): forward the caller's own token,
    so those calls carry the customer's identity and scopes, nothing more."""
    p = _current.get()
    return {"Authorization": f"Bearer {p.token}"} if p and p.token else {}
