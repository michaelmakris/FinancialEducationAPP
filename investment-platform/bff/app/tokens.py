"""Single-use tokens (email verification, password reset, MFA login challenge)."""
from __future__ import annotations

import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session as DB

from . import security
from .models import AuthToken, utcnow

MAX_ATTEMPTS = 5  # wrong MFA codes per login challenge


def issue(db: DB, customer_id: str, purpose: str, ttl: datetime.timedelta, *, revoke_previous: bool = True) -> str:
    if revoke_previous:  # only the newest link of a kind works
        db.execute(update(AuthToken).where(AuthToken.customer_id == customer_id, AuthToken.purpose == purpose,
                                           AuthToken.used_at.is_(None)).values(used_at=utcnow()))
    raw = security.new_token()
    now = utcnow()
    db.add(AuthToken(id=security.sha256_hex(raw), customer_id=customer_id, purpose=purpose,
                     created_at=now, expires_at=now + ttl))
    return raw


def find(db: DB, raw: str | None, purpose: str) -> AuthToken | None:
    """A live token of this purpose, without consuming it."""
    if not raw or len(raw) > 200:
        return None
    tok = db.get(AuthToken, security.sha256_hex(raw))
    if tok is None or tok.purpose != purpose or tok.used_at is not None or utcnow() >= tok.expires_at:
        return None
    return tok


def consume(tok: AuthToken) -> None:
    tok.used_at = utcnow()


def failed_attempt(tok: AuthToken) -> bool:
    """Count a wrong code; True if the token is now burned."""
    tok.attempts += 1
    if tok.attempts >= MAX_ATTEMPTS:
        tok.used_at = utcnow()
        return True
    return False
