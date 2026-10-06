import datetime as dt
import subprocess
import sys
import time
from pathlib import Path

import fakeredis
import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import mailer, mfa, security
from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import Customer, RecoveryCode
from tests.conftest import PASSWORD, csrf, last_mail_to, link_token, login, signup

NEW_PW = "a completely new passphrase"


def _customer(email="maria@example.com"):
    db = SessionLocal()
    try:
        return db.execute(select(Customer).where(Customer.email == email)).scalar_one()
    finally:
        db.close()


# ---------------------------------------------------------------- password reset
def test_password_reset_end_to_end(client, mail):
    signup(client)
    phone = TestClient(app, base_url="https://testserver")
    login(phone)
    r = client.post("/bff/auth/password-reset/request", json={"email": "Maria@example.com"})
    assert r.status_code == 202
    msg = last_mail_to(mail, "maria@example.com")
    assert msg["Subject"] == "Reset your password"
    token = link_token(msg, "reset-password")
    weak = client.post("/bff/auth/password-reset/confirm", json={"token": token, "new_password": "short"})
    assert weak.status_code == 422                                  # token not consumed by a rejected password
    ok = client.post("/bff/auth/password-reset/confirm", json={"token": token, "new_password": NEW_PW})
    assert ok.status_code == 200
    assert client.post("/bff/auth/password-reset/confirm", json={"token": token, "new_password": NEW_PW + "!"}).status_code == 400
    assert phone.get("/bff/auth/me").status_code == 401            # every session ended
    assert client.get("/bff/auth/me").status_code == 401
    assert last_mail_to(mail, "maria@example.com")["Subject"] == "Security notice: Your password was reset"
    assert login(client).status_code == 401 and login(client, password=NEW_PW).status_code == 200


def test_reset_request_is_identical_for_unknown_emails(client, mail):
    a = client.post("/bff/auth/password-reset/request", json={"email": "ghost@example.com"})
    b = client.post("/bff/auth/password-reset/request", json={"email": "other@example.com"})
    assert a.status_code == b.status_code == 202 and a.json() == b.json()
    assert mail.sent == []


def test_reset_link_expires_and_only_newest_works(client, mail):
    signup(client)
    client.post("/bff/auth/password-reset/request", json={"email": "maria@example.com"})
    old = link_token(last_mail_to(mail, "maria@example.com"), "reset-password")
    client.post("/bff/auth/password-reset/request", json={"email": "maria@example.com"})
    new = link_token(last_mail_to(mail, "maria@example.com"), "reset-password")
    assert client.post("/bff/auth/password-reset/confirm", json={"token": old, "new_password": NEW_PW}).status_code == 400
    db = SessionLocal()
    from app.models import AuthToken
    for t in db.execute(select(AuthToken)).scalars():
        t.expires_at -= dt.timedelta(minutes=settings.reset_token_minutes + 1)
    db.commit()
    db.close()
    assert client.post("/bff/auth/password-reset/confirm", json={"token": new, "new_password": NEW_PW}).status_code == 400


def test_reset_unlocks_and_verifies(client, mail):
    from tests.conftest import register
    register(client)  # never verified
    client.post("/bff/auth/password-reset/request", json={"email": "maria@example.com"})
    token = link_token(last_mail_to(mail, "maria@example.com"), "reset-password")
    assert client.post("/bff/auth/password-reset/confirm", json={"token": token, "new_password": NEW_PW}).status_code == 200
    assert _customer().email_verified is True
    assert login(client, password=NEW_PW).status_code == 200


# ---------------------------------------------------------------- MFA
def _enable_mfa(client) -> tuple[str, list[str]]:
    h = csrf(client)
    assert client.post("/bff/auth/mfa/setup", json={"password": "wrong password!!"}, headers=h).status_code == 403
    setup = client.post("/bff/auth/mfa/setup", json={"password": PASSWORD}, headers=h).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/Investment%20Lab:maria%40example.com")
    assert setup["qr_svg_data_uri"].startswith("data:image/svg+xml;base64,")
    secret = setup["secret"]
    assert client.post("/bff/auth/mfa/enable", json={"code": "000000"}, headers=h).status_code == 422
    r = client.post("/bff/auth/mfa/enable", json={"code": pyotp.TOTP(secret).now()}, headers=h)
    assert r.status_code == 200
    codes = r.json()["recovery_codes"]
    assert len(codes) == 10 and len(set(codes)) == 10
    return secret, codes


def _next_code(secret: str) -> str:
    """A code for the next 30 s step (the current one was just used: replays are refused)."""
    return pyotp.TOTP(secret).at(time.time() + mfa.STEP_S)


def test_mfa_secret_is_encrypted_and_codes_hashed(client):
    signup(client)
    secret, codes = _enable_mfa(client)
    c = _customer()
    assert c.mfa_secret_enc and secret not in c.mfa_secret_enc and security.decrypt(c.mfa_secret_enc) == secret
    db = SessionLocal()
    stored = [r.code_hash for r in db.execute(select(RecoveryCode)).scalars()]
    db.close()
    assert all(code.replace("-", "") not in stored for code in codes) and len(stored) == 10
    assert client.get("/bff/auth/me").json()["recovery_codes_remaining"] == 10


def test_login_with_mfa_needs_the_second_step(client, mail):
    signup(client)
    secret, _ = _enable_mfa(client)
    client.cookies.clear()
    r = login(client)
    assert r.status_code == 200 and r.json()["mfa_required"] is True and "set-cookie" not in r.headers
    challenge = r.json()["mfa_token"]
    assert client.get("/bff/auth/me").status_code == 401             # password alone is not a session
    assert client.post("/bff/auth/login/mfa", json={"mfa_token": challenge, "code": "123456"}).status_code == 401
    ok = client.post("/bff/auth/login/mfa", json={"mfa_token": challenge, "code": _next_code(secret)})
    assert ok.status_code == 200 and client.get("/bff/auth/me").status_code == 200
    assert client.post("/bff/auth/login/mfa", json={"mfa_token": challenge, "code": _next_code(secret)}).status_code == 401  # challenge used


def test_totp_codes_cannot_be_replayed():
    secret = mfa.new_secret()
    now = time.time()
    code = pyotp.TOTP(secret).at(now)
    step = mfa.verify_totp(secret, code, None, now=now)
    assert step is not None
    assert mfa.verify_totp(secret, code, step, now=now) is None          # same code again
    assert mfa.verify_totp(secret, pyotp.TOTP(secret).at(now - 300), None, now=now) is None  # too old
    assert mfa.verify_totp(secret, "12345", None, now=now) is None


def test_challenge_burns_after_five_wrong_codes(client):
    signup(client)
    secret, _ = _enable_mfa(client)
    client.cookies.clear()
    challenge = login(client).json()["mfa_token"]
    for _ in range(5):
        client.post("/bff/auth/login/mfa", json={"mfa_token": challenge, "code": "000000"})
    r = client.post("/bff/auth/login/mfa", json={"mfa_token": challenge, "code": _next_code(secret)})
    assert r.status_code == 401 and "start again" in r.json()["detail"]


def test_too_many_mfa_failures_across_challenges_block_login(client):
    signup(client)
    _enable_mfa(client)
    client.cookies.clear()
    for _ in range(2):
        ch = login(client).json()["mfa_token"]
        for _ in range(5):
            client.post("/bff/auth/login/mfa", json={"mfa_token": ch, "code": "000000"})
    assert login(client).status_code == 429


def test_recovery_code_login_is_single_use_and_notifies(client, mail):
    signup(client)
    _, codes = _enable_mfa(client)
    client.cookies.clear()
    ch = login(client).json()["mfa_token"]
    r = client.post("/bff/auth/login/mfa", json={"mfa_token": ch, "recovery_code": codes[0].upper()})
    assert r.status_code == 200 and r.json()["recovery_codes_remaining"] == 9
    assert last_mail_to(mail, "maria@example.com")["Subject"] == "Security notice: A recovery code was used to sign in"
    client.cookies.clear()
    ch = login(client).json()["mfa_token"]
    assert client.post("/bff/auth/login/mfa", json={"mfa_token": ch, "recovery_code": codes[0]}).status_code == 401


def test_password_reset_does_not_bypass_mfa(client, mail):
    signup(client)
    _enable_mfa(client)
    client.cookies.clear()
    client.post("/bff/auth/password-reset/request", json={"email": "maria@example.com"})
    token = link_token(last_mail_to(mail, "maria@example.com"), "reset-password")
    client.post("/bff/auth/password-reset/confirm", json={"token": token, "new_password": NEW_PW})
    r = login(client, password=NEW_PW)
    assert r.json().get("mfa_required") is True and client.get("/bff/auth/me").status_code == 401


def test_disable_mfa_needs_password_and_code(client):
    signup(client)
    secret, codes = _enable_mfa(client)
    h = csrf(client)
    assert client.post("/bff/auth/mfa/disable", json={"password": "wrong password!!", "code": _next_code(secret)}, headers=h).status_code == 403
    assert client.post("/bff/auth/mfa/disable", json={"password": PASSWORD, "code": "000000"}, headers=h).status_code == 422
    assert client.post("/bff/auth/mfa/disable", json={"password": PASSWORD, "code": _next_code(secret)}, headers=h).status_code == 204
    assert _customer().mfa_secret_enc is None
    client.cookies.clear()
    assert "csrf_token" in login(client).json()  # straight in, no MFA step


def test_required_mfa_blocks_the_api_until_enrolled(client, api, monkeypatch):
    monkeypatch.setattr(settings, "require_mfa", True)
    me = signup(client)
    assert me["mfa_enrollment_required"] is True
    r = client.get("/bff/api/v1/instruments")
    assert r.status_code == 403 and r.json()["detail"] == "mfa_enrollment_required" and api.calls == []
    secret, _ = _enable_mfa(client)
    assert client.get("/bff/api/v1/instruments").status_code == 200
    h = csrf(client)
    assert client.post("/bff/auth/mfa/disable", json={"password": PASSWORD, "code": _next_code(secret)}, headers=h).status_code == 403


def test_new_recovery_codes_replace_old_ones(client):
    signup(client)
    secret, old = _enable_mfa(client)
    r = client.post("/bff/auth/mfa/recovery-codes", json={"password": PASSWORD, "code": _next_code(secret)}, headers=csrf(client))
    new = r.json()["recovery_codes"]
    db = SessionLocal()
    c = db.execute(select(Customer)).scalar_one()
    assert mfa.use_recovery_code(db, c.id, old[0]) is False and mfa.use_recovery_code(db, c.id, new[0]) is True
    db.close()


# ---------------------------------------------------------------- shared rate limiting (Redis)
def test_redis_limiter_matches_memory_semantics():
    rl = security.RedisRateLimiter(fakeredis.FakeRedis())
    assert [rl.hit("k", 3, 60) for _ in range(4)] == [True, True, True, False]
    assert rl.count("k", 60) == 3
    rl.reset("k")
    assert rl.count("k", 60) == 0 and rl.hit("k", 1, 60) is True
    rl.clear()
    assert rl.count("k", 60) == 0


def test_redis_limiter_is_shared_between_instances():
    server = fakeredis.FakeServer()
    a = security.RedisRateLimiter(fakeredis.FakeRedis(server=server))
    b = security.RedisRateLimiter(fakeredis.FakeRedis(server=server))
    a.hit("login", 2, 60)
    b.hit("login", 2, 60)
    assert a.hit("login", 2, 60) is False  # replica A sees replica B's attempt


# ---------------------------------------------------------------- email backends
def test_outbox_writes_eml_files(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "outbox_dir", str(tmp_path))
    mailer.OutboxSender().send(mailer.build("x@example.com", "Hi", "Body https://app.example/?action=verify-email&token=abc"))
    files = list(tmp_path.glob("*.eml"))
    assert len(files) == 1 and b"token=abc" in files[0].read_bytes()


def test_delivery_failures_are_counted_not_raised(monkeypatch):
    class Broken:
        def send(self, msg):
            raise OSError("smtp down")
    mailer.set_sender(Broken())
    mailer.deliver("password_reset", "x@example.com", "s", "b")  # must not raise
    from prometheus_client import REGISTRY
    assert REGISTRY.get_sample_value("bff_emails_total", {"kind": "password_reset", "outcome": "failed"}) >= 1


# ---------------------------------------------------------------- admin CLI
def test_manage_cli(client):
    signup(client)
    env = {**__import__("os").environ}
    root = Path(__file__).resolve().parent.parent

    def run(*args):
        return subprocess.run([sys.executable, "-m", "scripts.manage", *args], cwd=root, env=env,
                              capture_output=True, text=True, timeout=60)

    out = run("set-role", "maria@example.com", "staff")
    assert out.returncode == 0 and "staff" in out.stdout
    assert client.get("/bff/auth/me").status_code == 401   # role change ends sessions: new scopes on next sign-in
    assert "role_changed" in run("events", "maria@example.com").stdout
    assert run("disable", "maria@example.com").returncode == 0
    assert login(client).status_code == 401
    run("enable", "maria@example.com")
    r = login(client)
    assert r.status_code == 200 and r.json()["customer"]["role"] == "staff"
    assert run("show", "nobody@example.com").returncode != 0
