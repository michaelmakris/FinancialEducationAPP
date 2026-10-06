"""TOTP (RFC 6238, 30 s, 6 digits -- any authenticator app) and recovery codes."""
from __future__ import annotations

import base64
import hmac
import secrets
import time

import pyotp
import segno
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DB

from . import security
from .config import settings
from .models import Customer, RecoveryCode, utcnow

STEP_S = 30
RECOVERY_CODES = 10
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o/1/l/i confusion


def new_secret() -> str:
    return pyotp.random_base32(length=32)  # 160 bits


def provisioning(secret: str, email: str) -> dict:
    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.mfa_issuer)
    svg = segno.make(uri, error="m").svg_inline(scale=4, border=2)
    return {"otpauth_uri": uri, "secret": secret,
            "qr_svg_data_uri": "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()}


def verify_totp(secret: str, code: str, last_step: int | None, now: float | None = None) -> int | None:
    """Accepts the current step +/- 1 (clock drift). Returns the matched step, or None.
    A step at or before last_step is refused, so a code cannot be used twice."""
    code = "".join(code.split())
    if not (code.isdigit() and len(code) == 6):
        return None
    totp = pyotp.TOTP(secret)
    current = int((now if now is not None else time.time()) // STEP_S)
    for step in (current - 1, current, current + 1):
        if (last_step is None or step > last_step) and hmac.compare_digest(totp.at(step * STEP_S), code):
            return step
    return None


def check_code(customer: Customer, code: str) -> bool:
    """Verify against the customer's active secret and record the step (replay protection)."""
    if not customer.mfa_secret_enc:
        return False
    step = verify_totp(security.decrypt(customer.mfa_secret_enc), code, customer.mfa_last_step)
    if step is None:
        return False
    customer.mfa_last_step = step
    return True


def _normalize_recovery(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())


def retire_recovery_codes(db: DB, customer_id: str) -> None:
    db.execute(update(RecoveryCode).where(RecoveryCode.customer_id == customer_id, RecoveryCode.used_at.is_(None))
               .values(used_at=utcnow()))


def new_recovery_codes(db: DB, customer_id: str) -> list[str]:
    """Replace any existing codes; returns the plaintext codes (shown to the customer once)."""
    retire_recovery_codes(db, customer_id)
    codes = []
    for _ in range(RECOVERY_CODES):
        raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
        db.add(RecoveryCode(customer_id=customer_id, code_hash=security.keyed_hash(raw)))
    return codes


def use_recovery_code(db: DB, customer_id: str, code: str) -> bool:
    h = security.keyed_hash(_normalize_recovery(code))
    row = db.execute(select(RecoveryCode).where(RecoveryCode.customer_id == customer_id,
                                                RecoveryCode.code_hash == h, RecoveryCode.used_at.is_(None))).scalar_one_or_none()
    if row is None:
        return False
    row.used_at = utcnow()
    return True


def remaining_recovery_codes(db: DB, customer_id: str) -> int:
    return len(db.execute(select(RecoveryCode.id).where(RecoveryCode.customer_id == customer_id,
                                                        RecoveryCode.used_at.is_(None))).all())
