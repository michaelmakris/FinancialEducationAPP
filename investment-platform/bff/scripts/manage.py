"""
Account administration for staff, from the command line (every action is
written to auth_events with the operator's OS user name).

    python -m scripts.manage list [--role staff] [--limit 50]
    python -m scripts.manage show EMAIL
    python -m scripts.manage set-role EMAIL staff|customer
    python -m scripts.manage disable EMAIL        # blocks sign-in, ends all sessions
    python -m scripts.manage enable EMAIL
    python -m scripts.manage unlock EMAIL         # clears a failed-login lockout
    python -m scripts.manage reset-mfa EMAIL      # lost phone AND recovery codes (verify identity first!)
    python -m scripts.manage verify-email EMAIL   # mark verified (e.g. confirmed by support)
    python -m scripts.manage events EMAIL [--limit 30]
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app import mfa, security  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import AuthEvent, Customer, utcnow  # noqa: E402
from app.sessions import revoke_all  # noqa: E402


def _audit(db, c: Customer, event: str, detail: str = "") -> None:
    db.add(AuthEvent(customer_id=c.id, email=c.email, event=event, ip="cli",
                     user_agent=f"scripts.manage ({getpass.getuser()})", detail=detail))


def _get(db, email: str) -> Customer:
    c = db.execute(select(Customer).where(Customer.email == security.normalize_email(email))).scalar_one_or_none()
    if c is None:
        sys.exit(f"No account with email {email}")
    return c


def _row(c: Customer) -> str:
    flags = [c.role, c.status, "verified" if c.email_verified else "UNVERIFIED", "mfa" if c.mfa_enabled else "no-mfa"]
    if c.locked_until and c.locked_until > utcnow():
        flags.append(f"locked until {c.locked_until:%Y-%m-%d %H:%M} UTC")
    return f"{c.email:40s} {c.full_name[:28]:28s} {' '.join(flags)}  last login {c.last_login_at or '-'}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--role")
    ls.add_argument("--limit", type=int, default=50)
    for name in ("show", "disable", "enable", "unlock", "reset-mfa", "verify-email"):
        sub.add_parser(name).add_argument("email")
    sr = sub.add_parser("set-role")
    sr.add_argument("email")
    sr.add_argument("role", choices=sorted(security.ROLE_SCOPES))
    ev = sub.add_parser("events")
    ev.add_argument("email")
    ev.add_argument("--limit", type=int, default=30)
    a = p.parse_args()

    init_db()
    db = SessionLocal()
    try:
        if a.cmd == "list":
            q = select(Customer).order_by(Customer.created_at.desc()).limit(a.limit)
            if a.role:
                q = q.where(Customer.role == a.role)
            for c in db.execute(q).scalars():
                print(_row(c))
            return 0
        c = _get(db, a.email)
        if a.cmd == "show":
            print(_row(c))
            print(f"created {c.created_at}  password changed {c.password_changed_at}  mfa since {c.mfa_enabled_at or '-'}")
            if c.mfa_enabled:
                print(f"recovery codes left: {mfa.remaining_recovery_codes(db, c.id)}")
            return 0
        if a.cmd == "events":
            rows = db.execute(select(AuthEvent).where(AuthEvent.customer_id == c.id)
                              .order_by(AuthEvent.id.desc()).limit(a.limit)).scalars()
            for e in rows:
                print(f"{e.at:%Y-%m-%d %H:%M:%S}  {e.event:26s} {e.ip:16s} {e.detail}")
            return 0
        if a.cmd == "set-role":
            old, c.role = c.role, a.role
            revoke_all(db, c.id)  # new scopes apply from the next sign-in
            _audit(db, c, "role_changed", f"{old} -> {a.role}")
        elif a.cmd == "disable":
            c.status = "disabled"
            n = revoke_all(db, c.id)
            _audit(db, c, "account_disabled", f"revoked {n} session(s)")
        elif a.cmd == "enable":
            c.status = "active"
            _audit(db, c, "account_enabled")
        elif a.cmd == "unlock":
            c.locked_until, c.failed_login_count = None, 0
            security.limiter.reset(f"email:{c.email}")
            _audit(db, c, "account_unlocked")
        elif a.cmd == "reset-mfa":
            c.mfa_secret_enc = c.mfa_pending_secret_enc = None
            c.mfa_enabled_at = c.mfa_last_step = None
            mfa.retire_recovery_codes(db, c.id)
            n = revoke_all(db, c.id)
            _audit(db, c, "mfa_reset_by_staff", f"revoked {n} session(s)")
        elif a.cmd == "verify-email":
            c.email_verified, c.email_verified_at = True, utcnow()
            _audit(db, c, "email_verified_by_staff")
        db.commit()
        print(_row(c))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
