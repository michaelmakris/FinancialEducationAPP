"""
/bff/auth: account lifecycle.

  register -> email link -> verify-email -> login [-> login/mfa] -> session
  password-reset/request -> email link -> password-reset/confirm
  mfa/setup -> mfa/enable (recovery codes) ; mfa/disable ; mfa/recovery-codes
  me, logout, password (change), sessions (list / revoke)

Answers never reveal whether an email is registered: register, resend and
reset-request always return 202, and the emails are sent in the background.
"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DB

from . import mailer, mfa, security, tokens
from .config import settings
from .db import get_db
from .models import Customer, utcnow
from .sessions import (Current, active_sessions, audit, clear_cookie, create_session, current, current_with_csrf,
                       revoke_all)

router = APIRouter(prefix="/bff/auth", tags=["auth"])

GENERIC_LOGIN_ERROR = "Invalid email or password"
TOO_MANY = "Too many attempts. Please wait a few minutes and try again."
BAD_LINK = "This link is invalid or has expired. Please request a new one."
ACCEPTED = {"status": "accepted",
            "message": "If the details are valid, we have sent you an email. Please check your inbox."}
_PW = security.PASSWORD_MAX * 4


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=_PW)
    full_name: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=_PW)


class MfaLoginIn(BaseModel):
    mfa_token: str = Field(max_length=200)
    code: str | None = Field(None, max_length=20)
    recovery_code: str | None = Field(None, max_length=40)


class EmailIn(BaseModel):
    email: str = Field(max_length=254)


class TokenIn(BaseModel):
    token: str = Field(max_length=200)


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    new_password: str = Field(max_length=_PW)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=_PW)
    new_password: str = Field(max_length=_PW)


class PasswordOnlyIn(BaseModel):
    password: str = Field(max_length=_PW)


class CodeIn(BaseModel):
    code: str = Field(max_length=20)


class PasswordAndCodeIn(BaseModel):
    password: str = Field(max_length=_PW)
    code: str = Field(max_length=20)


# ---------------------------------------------------------------- helpers
def _customer_out(c: Customer) -> dict:
    return {"id": c.id, "email": c.email, "full_name": c.full_name, "role": c.role,
            "email_verified": c.email_verified, "mfa_enabled": c.mfa_enabled,
            "created_at": c.created_at, "last_login_at": c.last_login_at}


def _session_payload(db: DB, customer: Customer, sess) -> dict:
    return {
        "customer": _customer_out(customer), "csrf_token": sess.csrf_token, "session_expires_at": sess.expires_at,
        "mfa_required": settings.require_mfa,
        "mfa_enrollment_required": settings.require_mfa and not customer.mfa_enabled,
        "recovery_codes_remaining": mfa.remaining_recovery_codes(db, customer.id) if customer.mfa_enabled else None,
    }


def _ip_limit(request: Request) -> None:
    if not security.limiter.hit(f"ip:{security.client_ip(request)}", settings.auth_rate_per_minute, 60):
        raise HTTPException(429, TOO_MANY)


def _mail(bg: BackgroundTasks, kind: str, to: str, subject_body: tuple[str, str]) -> None:
    """Queue an email, at most 3 of a kind per address per hour (no mail-bombing via our forms)."""
    if security.limiter.hit(f"mail:{kind}:{to}", 3, 3600):
        bg.add_task(mailer.deliver, kind, to, *subject_body)


def _by_email(db: DB, email: str) -> Customer | None:
    return db.execute(select(Customer).where(Customer.email == email)).scalar_one_or_none()


def _send_verification(db: DB, bg: BackgroundTasks, c: Customer) -> None:
    # Earlier links stay valid until they expire: customers often click the first email, not the newest.
    raw = tokens.issue(db, c.id, "verify_email", datetime.timedelta(hours=settings.verify_token_hours),
                       revoke_previous=False)
    _mail(bg, "verify_email", c.email, mailer.verify_email(c.full_name, raw))


def _notice(bg: BackgroundTasks, c: Customer, what: str) -> None:
    bg.add_task(mailer.deliver, "security_notice", c.email, *mailer.security_notice(c.full_name, what))


def _check_new_password(password: str, email: str, full_name: str, old: str | None = None) -> None:
    problems = security.password_problems(password, email, full_name)
    if old is not None and password == old:
        problems.append("different from the current password")
    if problems:
        raise HTTPException(422, "Password needs: " + "; ".join(problems))


def _require_password(db: DB, request: Request, c: Customer, password: str, event: str) -> None:
    if not security.verify_password(c.password_hash, password):
        audit(db, request, event, c.id, c.email)
        db.commit()
        raise HTTPException(403, "Password is incorrect")


# ---------------------------------------------------------------- registration + email verification
@router.post("/register")
def register(body: RegisterIn, request: Request, response: Response, bg: BackgroundTasks, db: DB = Depends(get_db)):
    _ip_limit(request)
    email = security.normalize_email(body.email)
    full_name = " ".join(body.full_name.split())
    if not security.valid_email(email):
        raise HTTPException(422, "Enter a valid email address")
    _check_new_password(body.password, email, full_name)
    existing = _by_email(db, email)

    if not settings.require_email_verification:  # dev shortcut: active immediately, signed in
        if existing:
            raise HTTPException(409, "An account with this email already exists")
        c = Customer(email=email, password_hash=security.hash_password(body.password), full_name=full_name,
                     email_verified=True, email_verified_at=utcnow(), last_login_at=utcnow())
        db.add(c)
        db.flush()
        sess = create_session(db, c, request, response)
        audit(db, request, "register", c.id, email)
        db.commit()
        response.status_code = 201
        return _session_payload(db, c, sess)

    if existing is None:
        c = Customer(email=email, password_hash=security.hash_password(body.password), full_name=full_name)
        db.add(c)
        db.flush()
        _send_verification(db, bg, c)
        audit(db, request, "register", c.id, email)
    elif not existing.email_verified:
        _send_verification(db, bg, existing)  # same person retrying; the first password stays
        audit(db, request, "register_retry", existing.id, email)
    else:
        _mail(bg, "already_registered", email, mailer.already_registered(existing.full_name))
        audit(db, request, "register_duplicate", existing.id, email)
    db.commit()
    response.status_code = 202
    return ACCEPTED


@router.post("/verify-email")
def verify_email(body: TokenIn, request: Request, db: DB = Depends(get_db)):
    _ip_limit(request)
    tok = tokens.find(db, body.token, "verify_email")
    if tok is None:
        raise HTTPException(400, BAD_LINK)
    c = db.get(Customer, tok.customer_id)
    tokens.consume(tok)
    c.email_verified, c.email_verified_at = True, utcnow()
    audit(db, request, "email_verified", c.id, c.email)
    db.commit()
    return {"status": "verified", "message": "Your email is confirmed. You can sign in now."}


@router.post("/resend-verification", status_code=202)
def resend_verification(body: EmailIn, request: Request, bg: BackgroundTasks, db: DB = Depends(get_db)):
    _ip_limit(request)
    c = _by_email(db, security.normalize_email(body.email))
    if c and not c.email_verified and c.status == "active":
        _send_verification(db, bg, c)
        db.commit()
    return ACCEPTED


# ---------------------------------------------------------------- login (+ MFA step)
@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, bg: BackgroundTasks, db: DB = Depends(get_db)):
    _ip_limit(request)
    email = security.normalize_email(body.email)
    email_key = f"email:{email}"
    window = settings.lockout_minutes * 60
    customer = _by_email(db, email)
    now = utcnow()

    # Same answer for a locked real account and a hammered unknown address (no account enumeration).
    if (customer and customer.locked_until and customer.locked_until > now) or \
            security.limiter.count(email_key, window) >= settings.login_max_failures:
        audit(db, request, "login_blocked", customer.id if customer else None, email)
        db.commit()
        raise HTTPException(429, TOO_MANY)

    ok = security.verify_password(customer.password_hash if customer else None, body.password)
    if not ok or customer is None or customer.status != "active":
        security.limiter.hit(email_key, 10**6, window)
        if customer:
            customer.failed_login_count += 1
            if customer.failed_login_count >= settings.login_max_failures:
                customer.locked_until = now + datetime.timedelta(minutes=settings.lockout_minutes)
                customer.failed_login_count = 0
                audit(db, request, "account_locked", customer.id, email)
        audit(db, request, "login_failed", customer.id if customer else None, email,
              detail="" if customer else "unknown email")
        db.commit()
        raise HTTPException(401, GENERIC_LOGIN_ERROR)

    security.limiter.reset(email_key)
    customer.failed_login_count, customer.locked_until = 0, None
    if security.needs_rehash(customer.password_hash):
        customer.password_hash = security.hash_password(body.password)

    if settings.require_email_verification and not customer.email_verified:
        _send_verification(db, bg, customer)
        audit(db, request, "login_unverified", customer.id, email)
        db.commit()
        # returned, not raised: an HTTPException would drop the queued email
        return JSONResponse({"detail": "Please confirm your email address first. We have sent you a new link."},
                            status_code=403, background=bg)

    if customer.mfa_enabled:
        if security.limiter.count(f"mfa:{customer.id}", window) >= 10:
            audit(db, request, "login_blocked", customer.id, email, detail="too many MFA failures")
            db.commit()
            raise HTTPException(429, TOO_MANY)
        raw = tokens.issue(db, customer.id, "mfa_login", datetime.timedelta(minutes=settings.mfa_challenge_minutes),
                           revoke_previous=False)
        audit(db, request, "login_password_ok", customer.id, email)
        db.commit()
        return {"mfa_required": True, "mfa_token": raw}

    customer.last_login_at = now
    sess = create_session(db, customer, request, response)  # always a fresh id: no session fixation
    audit(db, request, "login", customer.id, email)
    db.commit()
    return _session_payload(db, customer, sess)


@router.post("/login/mfa")
def login_mfa(body: MfaLoginIn, request: Request, response: Response, bg: BackgroundTasks, db: DB = Depends(get_db)):
    _ip_limit(request)
    tok = tokens.find(db, body.mfa_token, "mfa_login")
    if tok is None:
        raise HTTPException(401, "Your sign-in has expired. Please start again.")
    c = db.get(Customer, tok.customer_id)
    window = settings.lockout_minutes * 60
    if c is None or c.status != "active" or not c.mfa_enabled:
        raise HTTPException(401, "Your sign-in has expired. Please start again.")
    if security.limiter.count(f"mfa:{c.id}", window) >= 10:
        raise HTTPException(429, TOO_MANY)

    used_recovery = False
    if body.code:
        ok = mfa.check_code(c, body.code)
    elif body.recovery_code:
        ok = used_recovery = mfa.use_recovery_code(db, c.id, body.recovery_code)
    else:
        raise HTTPException(422, "Enter the 6-digit code from your authenticator app or a recovery code")
    if not ok:
        security.limiter.hit(f"mfa:{c.id}", 10**6, window)
        burned = tokens.failed_attempt(tok)
        audit(db, request, "mfa_failed", c.id, c.email)
        db.commit()
        raise HTTPException(401, "Your sign-in has expired. Please start again." if burned else "Invalid code")

    tokens.consume(tok)
    security.limiter.reset(f"mfa:{c.id}")
    c.last_login_at = utcnow()
    sess = create_session(db, c, request, response)
    audit(db, request, "login", c.id, c.email, detail="recovery code" if used_recovery else "totp")
    if used_recovery:
        _notice(bg, c, "A recovery code was used to sign in")
    db.commit()
    return _session_payload(db, c, sess)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, cur: Current = Depends(current_with_csrf), db: DB = Depends(get_db)):
    cur.session.revoked_at = utcnow()
    audit(db, request, "logout", cur.customer.id, cur.customer.email)
    db.commit()
    clear_cookie(response)


@router.get("/me")
def me(cur: Current = Depends(current), db: DB = Depends(get_db)):
    return _session_payload(db, cur.customer, cur.session)


# ---------------------------------------------------------------- passwords
@router.post("/password", status_code=204)
def change_password(body: PasswordIn, request: Request, bg: BackgroundTasks,
                    cur: Current = Depends(current_with_csrf), db: DB = Depends(get_db)):
    c = cur.customer
    if not security.verify_password(c.password_hash, body.current_password):
        audit(db, request, "password_change_failed", c.id, c.email)
        db.commit()
        raise HTTPException(403, "Current password is incorrect")
    _check_new_password(body.new_password, c.email, c.full_name, old=body.current_password)
    c.password_hash = security.hash_password(body.new_password)
    c.password_changed_at = utcnow()
    n = revoke_all(db, c.id, except_id=cur.session.id)  # sign out every other device
    audit(db, request, "password_changed", c.id, c.email, detail=f"revoked {n} other session(s)")
    _notice(bg, c, "Your password was changed")
    db.commit()


@router.post("/password-reset/request", status_code=202)
def password_reset_request(body: EmailIn, request: Request, bg: BackgroundTasks, db: DB = Depends(get_db)):
    _ip_limit(request)
    email = security.normalize_email(body.email)
    c = _by_email(db, email)
    if c and c.status == "active":
        raw = tokens.issue(db, c.id, "password_reset", datetime.timedelta(minutes=settings.reset_token_minutes))
        _mail(bg, "password_reset", c.email, mailer.password_reset(c.full_name, raw))
        audit(db, request, "password_reset_requested", c.id, email)
    else:
        audit(db, request, "password_reset_requested", None, email, detail="no active account")
    db.commit()
    return ACCEPTED


@router.post("/password-reset/confirm")
def password_reset_confirm(body: ResetIn, request: Request, bg: BackgroundTasks, db: DB = Depends(get_db)):
    _ip_limit(request)
    tok = tokens.find(db, body.token, "password_reset")
    if tok is None:
        raise HTTPException(400, BAD_LINK)
    c = db.get(Customer, tok.customer_id)
    if c is None or c.status != "active":
        raise HTTPException(400, BAD_LINK)
    _check_new_password(body.new_password, c.email, c.full_name)
    tokens.consume(tok)
    c.password_hash = security.hash_password(body.new_password)
    c.password_changed_at = utcnow()
    c.failed_login_count, c.locked_until = 0, None
    if not c.email_verified:  # the reset link proves the customer controls the address
        c.email_verified, c.email_verified_at = True, utcnow()
    security.limiter.reset(f"email:{c.email}")
    n = revoke_all(db, c.id)
    audit(db, request, "password_reset", c.id, c.email, detail=f"revoked {n} session(s)")
    _notice(bg, c, "Your password was reset")
    db.commit()
    # MFA is untouched: the next sign-in still asks for the authenticator code.
    return {"status": "password_reset", "message": "Your password has been changed. Please sign in."}


# ---------------------------------------------------------------- MFA management
@router.post("/mfa/setup")
def mfa_setup(body: PasswordOnlyIn, request: Request, cur: Current = Depends(current_with_csrf), db: DB = Depends(get_db)):
    c = cur.customer
    if c.mfa_enabled:
        raise HTTPException(409, "Two-step verification is already on")
    _require_password(db, request, c, body.password, "mfa_setup_failed")
    secret = mfa.new_secret()
    c.mfa_pending_secret_enc = security.encrypt(secret)
    db.commit()
    return mfa.provisioning(secret, c.email)


@router.post("/mfa/enable")
def mfa_enable(body: CodeIn, request: Request, bg: BackgroundTasks,
               cur: Current = Depends(current_with_csrf), db: DB = Depends(get_db)):
    c = cur.customer
    if c.mfa_enabled:
        raise HTTPException(409, "Two-step verification is already on")
    if not c.mfa_pending_secret_enc:
        raise HTTPException(409, "Start the setup first")
    step = mfa.verify_totp(security.decrypt(c.mfa_pending_secret_enc), body.code, None)
    if step is None:
        raise HTTPException(422, "That code didn't match. Check your phone's time and try the newest code.")
    c.mfa_secret_enc, c.mfa_pending_secret_enc = c.mfa_pending_secret_enc, None
    c.mfa_enabled_at, c.mfa_last_step = utcnow(), step
    codes = mfa.new_recovery_codes(db, c.id)
    audit(db, request, "mfa_enabled", c.id, c.email)
    _notice(bg, c, "Two-step verification was turned on")
    db.commit()
    return {"recovery_codes": codes}


@router.post("/mfa/disable", status_code=204)
def mfa_disable(body: PasswordAndCodeIn, request: Request, bg: BackgroundTasks,
                cur: Current = Depends(current_with_csrf), db: DB = Depends(get_db)):
    c = cur.customer
    if settings.require_mfa:
        raise HTTPException(403, "Two-step verification is required for all accounts")
    if not c.mfa_enabled:
        raise HTTPException(409, "Two-step verification is not on")
    _require_password(db, request, c, body.password, "mfa_disable_failed")
    if not mfa.check_code(c, body.code):
        raise HTTPException(422, "Invalid code")
    c.mfa_secret_enc = c.mfa_pending_secret_enc = None
    c.mfa_enabled_at = c.mfa_last_step = None
    mfa.retire_recovery_codes(db, c.id)
    audit(db, request, "mfa_disabled", c.id, c.email)
    _notice(bg, c, "Two-step verification was turned off")
    db.commit()


@router.post("/mfa/recovery-codes")
def mfa_new_recovery_codes(body: PasswordAndCodeIn, request: Request, bg: BackgroundTasks,
                           cur: Current = Depends(current_with_csrf), db: DB = Depends(get_db)):
    c = cur.customer
    if not c.mfa_enabled:
        raise HTTPException(409, "Two-step verification is not on")
    _require_password(db, request, c, body.password, "recovery_codes_failed")
    if not mfa.check_code(c, body.code):
        raise HTTPException(422, "Invalid code")
    codes = mfa.new_recovery_codes(db, c.id)
    audit(db, request, "recovery_codes_regenerated", c.id, c.email)
    _notice(bg, c, "New recovery codes were generated (the old ones no longer work)")
    db.commit()
    return {"recovery_codes": codes}


# ---------------------------------------------------------------- sessions
@router.get("/sessions")
def list_sessions(cur: Current = Depends(current), db: DB = Depends(get_db)):
    return [{"id": s.id[:16], "current": s.id == cur.session.id, "created_at": s.created_at,
             "last_seen_at": s.last_seen_at, "ip": s.ip, "user_agent": s.user_agent}
            for s in active_sessions(db, cur.customer.id)]


@router.delete("/sessions/{public_id}", status_code=204)
def revoke_session(public_id: str, request: Request, cur: Current = Depends(current_with_csrf), db: DB = Depends(get_db)):
    match = [s for s in active_sessions(db, cur.customer.id) if s.id[:16] == public_id]
    if len(public_id) != 16 or not match:
        raise HTTPException(404, "No such session")
    match[0].revoked_at = utcnow()
    audit(db, request, "session_revoked", cur.customer.id, cur.customer.email)
    db.commit()
