import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import AuthEvent, Customer, Session, utcnow
from tests.conftest import PASSWORD, csrf, last_mail_to, link_token, login, register, signup

COOKIE = "__Host-fea_session"


def _db():
    return SessionLocal()


def _events():
    db = _db()
    try:
        return [e.event for e in db.execute(select(AuthEvent).order_by(AuthEvent.id)).scalars()]
    finally:
        db.close()


def _customer(email="maria@example.com"):
    db = _db()
    try:
        return db.execute(select(Customer).where(Customer.email == email)).scalar_one()
    finally:
        db.close()


# ---------------------------------------------------------------- registration + verification
def test_register_sends_a_verification_link_and_does_not_sign_in(client, mail):
    r = register(client, email="  Maria@Example.COM ")
    assert r.status_code == 202 and r.json()["status"] == "accepted"
    assert "set-cookie" not in r.headers
    msg = last_mail_to(mail, "maria@example.com")
    assert msg["Subject"] == "Confirm your email address"
    assert "https://app.example/?action=verify-email&token=" in msg.get_content()
    c = _customer()
    assert c.password_hash.startswith("$argon2id$") and PASSWORD not in c.password_hash
    assert c.email_verified is False


def test_unverified_account_cannot_sign_in_and_gets_a_fresh_link(client, mail):
    register(client)
    first = link_token(last_mail_to(mail, "maria@example.com"), "verify-email")
    r = login(client)
    assert r.status_code == 403 and "confirm your email" in r.json()["detail"]
    second = link_token(last_mail_to(mail, "maria@example.com"), "verify-email")
    assert second != first
    assert client.post("/bff/auth/verify-email", json={"token": first}).status_code == 200   # older links still work
    assert client.post("/bff/auth/verify-email", json={"token": first}).status_code == 400   # single use
    assert login(client).status_code == 200


def test_verification_link_expires(client, mail):
    register(client)
    token = link_token(last_mail_to(mail, "maria@example.com"), "verify-email")
    db = _db()
    from app.models import AuthToken
    for t in db.execute(select(AuthToken)).scalars():
        t.expires_at = utcnow() - dt.timedelta(seconds=1)
    db.commit()
    db.close()
    assert client.post("/bff/auth/verify-email", json={"token": token}).status_code == 400


def test_registration_never_reveals_existing_accounts(client, mail):
    signup(client)
    client.cookies.clear()
    again = register(client, password="some other long passphrase")
    fresh = register(client, email="new.person@example.com")
    assert again.status_code == fresh.status_code == 202 and again.json() == fresh.json()
    assert last_mail_to(mail, "maria@example.com")["Subject"] == "Someone tried to register with your email"
    assert login(client).status_code == 200                                          # original password unchanged
    assert login(client, password="some other long passphrase").status_code == 401


def test_cookie_is_hardened_and_db_keeps_only_a_hash(client):
    signup(client)
    cookie = [h for h in client.cookies.jar][0]
    assert cookie.name == COOKIE and cookie.secure and cookie.path == "/"
    assert cookie.has_nonstandard_attr("HttpOnly")
    db = _db()
    assert db.get(Session, client.cookies.get(COOKIE)) is None  # stored as sha256(token)
    db.close()


@pytest.mark.parametrize("email,password,msg", [
    ("not-an-email", PASSWORD, "valid email"),
    ("a@example.com", "short1", "at least 12"),
    ("a@example.com", "password1234", "common"),
    ("a@example.com", "aaaaaaaaaaaaaaaa", "repetitive"),
    ("giorgos@example.com", "giorgos-is-my-password", "email name"),
    ("b@example.com", "papadopoulou-2026!", "your name"),
])
def test_register_rejects_bad_input(client, email, password, msg):
    r = register(client, email=email, password=password)
    assert r.status_code == 422 and msg in r.json()["detail"]


def test_resend_verification_is_silent_for_unknown_emails(client, mail):
    a = client.post("/bff/auth/resend-verification", json={"email": "ghost@example.com"})
    register(client)
    b = client.post("/bff/auth/resend-verification", json={"email": "maria@example.com"})
    assert a.status_code == b.status_code == 202 and a.json() == b.json()
    assert [m["To"] for m in mail.sent] == ["maria@example.com", "maria@example.com"]


def test_emails_to_one_address_are_capped(client, mail):
    register(client)
    for _ in range(5):
        client.post("/bff/auth/resend-verification", json={"email": "maria@example.com"})
    assert len(mail.sent) == 3  # at most 3 verification mails per hour per address


# ---------------------------------------------------------------- login
def test_login_errors_do_not_reveal_whether_the_account_exists(client):
    signup(client)
    client.cookies.clear()
    wrong = login(client, password="wrong password!!")
    unknown = login(client, email="nobody@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid email or password"}


def test_login_issues_a_new_session_id(client):
    signup(client)
    first = client.cookies.get(COOKIE)
    assert login(client, email="MARIA@example.com").status_code == 200   # emails are case-insensitive
    assert client.cookies.get(COOKIE) != first                            # no session fixation


def test_lockout_after_repeated_failures(client):
    signup(client)
    client.cookies.clear()
    for _ in range(settings.login_max_failures):
        assert login(client, password="wrong password!!").status_code == 401
    r = login(client)
    assert r.status_code == 429 and "Too many attempts" in r.json()["detail"]
    assert "account_locked" in _events() and "login_blocked" in _events()
    db = _db()
    db.execute(select(Customer)).scalar_one().locked_until = utcnow() - dt.timedelta(seconds=1)
    db.commit()
    db.close()
    from app import security
    security.limiter.clear()
    assert login(client).status_code == 200


def test_unknown_email_is_throttled_the_same_way(client):
    for _ in range(settings.login_max_failures):
        assert login(client, email="ghost@example.com").status_code == 401
    assert login(client, email="ghost@example.com").status_code == 429


def test_per_ip_rate_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_rate_per_minute", 3)
    codes = [login(client, email=f"x{i}@example.com").status_code for i in range(4)]
    assert codes == [401, 401, 401, 429]


# ---------------------------------------------------------------- sessions
def test_logout_needs_csrf_and_kills_the_session(client):
    signup(client)
    old = client.cookies.get(COOKIE)
    assert client.post("/bff/auth/logout").status_code == 403
    assert client.post("/bff/auth/logout", headers={"X-CSRF-Token": "guess"}).status_code == 403
    assert client.post("/bff/auth/logout", headers=csrf(client)).status_code == 204
    assert client.get("/bff/auth/me").status_code == 401
    client.cookies.set(COOKIE, old)
    assert client.get("/bff/auth/me").status_code == 401
    assert _events()[-1] == "logout"


def _age_session(minutes_idle=0, hours_old=0):
    db = _db()
    s = db.execute(select(Session)).scalars().all()[-1]
    s.last_seen_at -= dt.timedelta(minutes=minutes_idle)
    s.expires_at -= dt.timedelta(hours=hours_old)
    db.commit()
    db.close()


def test_idle_timeout(client):
    signup(client)
    _age_session(minutes_idle=settings.session_idle_minutes + 1)
    assert client.get("/bff/auth/me").status_code == 401


def test_absolute_timeout(client):
    signup(client)
    _age_session(hours_old=settings.session_absolute_hours)
    assert client.get("/bff/auth/me").status_code == 401


def test_password_change_signs_out_other_devices_and_notifies(client, mail):
    signup(client)
    laptop = TestClient(app, base_url="https://testserver")
    assert login(laptop).status_code == 200
    h = csrf(client)
    assert client.post("/bff/auth/password", json={"current_password": "nope nope nope", "new_password": "a brand new passphrase"}, headers=h).status_code == 403
    assert client.post("/bff/auth/password", json={"current_password": PASSWORD, "new_password": "short"}, headers=h).status_code == 422
    assert client.post("/bff/auth/password", json={"current_password": PASSWORD, "new_password": "a brand new passphrase"}, headers=h).status_code == 204
    assert client.get("/bff/auth/me").status_code == 200
    assert laptop.get("/bff/auth/me").status_code == 401
    assert last_mail_to(mail, "maria@example.com")["Subject"] == "Security notice: Your password was changed"
    client.cookies.clear()
    assert login(client, password="a brand new passphrase").status_code == 200


def test_list_and_revoke_sessions(client):
    signup(client)
    phone = TestClient(app, base_url="https://testserver", headers={"User-Agent": "phone"})
    login(phone)
    sessions = client.get("/bff/auth/sessions").json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    other = next(s for s in sessions if not s["current"])
    assert other["user_agent"] == "phone"
    assert client.delete(f"/bff/auth/sessions/{other['id']}", headers=csrf(client)).status_code == 204
    assert phone.get("/bff/auth/me").status_code == 401
    assert client.delete("/bff/auth/sessions/0000000000000000", headers=csrf(client)).status_code == 404


def test_cross_site_writes_are_refused(client):
    r = client.post("/bff/auth/login", json={"email": "a@example.com", "password": PASSWORD}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    ok = client.post("/bff/auth/login", json={"email": "a@example.com", "password": PASSWORD}, headers={"Origin": "https://testserver"})
    assert ok.status_code == 401


def test_security_headers(client):
    r = client.get("/bff/auth/me")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/bff/docs").status_code == 404


def test_disabled_customer_cannot_sign_in(client):
    signup(client)
    db = _db()
    db.execute(select(Customer)).scalar_one().status = "disabled"
    db.commit()
    db.close()
    assert client.get("/bff/auth/me").status_code == 401
    client.cookies.clear()
    assert login(client).status_code == 401


def test_dev_mode_without_email_verification(client, monkeypatch):
    monkeypatch.setattr(settings, "require_email_verification", False)
    r = register(client)
    assert r.status_code == 201 and client.get("/bff/auth/me").status_code == 200
