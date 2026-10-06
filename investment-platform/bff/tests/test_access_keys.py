import datetime as dt
import time

import jwt
import pyotp
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AccessKey, Customer, utcnow
from tests.conftest import MCP_KEY, PASSWORD, csrf, last_mail_to, signup


def internal_headers(key=MCP_KEY, iss="mcp", aud="bff-internal", lifetime=60):
    now = int(time.time())
    token = jwt.encode({"iss": iss, "aud": aud, "iat": now, "exp": now + lifetime}, key, algorithm="EdDSA")
    return {"Authorization": f"Bearer {token}"}


def create(client, level="read", days=30, name="Claude Desktop", **extra):
    return client.post("/bff/auth/access-keys", headers=csrf(client),
                       json={"name": name, "level": level, "days": days, "password": PASSWORD, **extra})


def introspect(client, access_key, **kw):
    return client.post("/bff/internal/introspect", json={"key": access_key}, headers=internal_headers(**kw))


def test_create_list_and_use_a_key(client, mail):
    customer_id = signup(client)["customer"]["id"]
    r = create(client)
    assert r.status_code == 201
    body = r.json()
    raw = body["key"]
    assert raw.startswith("fea_mcp_") and body["prefix"] == raw[:12] and body["level"] == "read"
    listed = client.get("/bff/auth/access-keys").json()
    assert len(listed) == 1 and "key" not in listed[0]                      # shown only once
    db = SessionLocal()
    assert db.execute(select(AccessKey)).scalar_one().id != raw                # only the hash is stored
    db.close()
    info = introspect(client, raw).json()
    assert info["active"] is True and info["customer_id"] == customer_id
    assert info["scopes"] == ["market:read", "portfolio:read"]
    assert "AI assistant access key" in last_mail_to(mail, "maria@example.com")["Subject"] + last_mail_to(mail, "maria@example.com").get_content()
    assert client.get("/bff/auth/access-keys").json()[0]["last_used_at"] is not None


def test_trade_level_adds_portfolio_write_only(client):
    signup(client)
    raw = create(client, level="trade").json()["key"]
    assert introspect(client, raw).json()["scopes"] == ["market:read", "portfolio:read", "portfolio:write"]
    assert create(client, level="admin").status_code == 422


def test_creation_needs_password_and_mfa_code(client):
    signup(client)
    assert client.post("/bff/auth/access-keys", headers=csrf(client),
                       json={"name": "x", "level": "read", "days": 30, "password": "wrong password!!"}).status_code == 403
    h = csrf(client)
    secret = client.post("/bff/auth/mfa/setup", json={"password": PASSWORD}, headers=h).json()["secret"]
    client.post("/bff/auth/mfa/enable", json={"code": pyotp.TOTP(secret).now()}, headers=h)
    assert create(client).status_code == 422                                   # MFA on: code required
    assert create(client, code=pyotp.TOTP(secret).at(time.time() + 30)).status_code == 201


def test_limits(client):
    signup(client)
    assert create(client, days=91).status_code == 422
    for i in range(10):
        assert create(client, name=f"k{i}").status_code == 201
    assert create(client, name="one too many").status_code == 409


def test_revoked_expired_and_disabled_keys_are_inactive(client):
    signup(client)
    a = create(client, name="a").json()
    b = create(client, name="b").json()
    assert client.delete(f"/bff/auth/access-keys/{a['id']}", headers=csrf(client)).status_code == 204
    assert introspect(client, a["key"]).json() == {"active": False}
    db = SessionLocal()
    k = db.execute(select(AccessKey).where(AccessKey.prefix == b["prefix"])).scalar_one()
    k.expires_at = utcnow() - dt.timedelta(seconds=1)
    db.commit()
    db.close()
    assert introspect(client, b["key"]).json() == {"active": False}
    c = create(client, name="c").json()
    db = SessionLocal()
    db.execute(select(Customer)).scalar_one().status = "disabled"
    db.commit()
    db.close()
    assert introspect(client, c["key"]).json() == {"active": False}


@pytest.mark.parametrize("bad", ["", "fea_mcp_doesnotexist", "not-a-key", "x" * 199])
def test_unknown_keys_are_inactive(client, bad):
    assert introspect(client, bad).json() == {"active": False}


def test_introspection_only_for_signed_internal_callers(client):
    signup(client)
    raw = create(client).json()["key"]
    assert client.post("/bff/internal/introspect", json={"key": raw}).status_code == 401                 # no caller token
    assert introspect(client, raw, key=Ed25519PrivateKey.generate()).status_code == 401                  # forged signature
    assert introspect(client, raw, iss="bff").status_code == 401                                         # not a listed caller
    assert introspect(client, raw, aud="investment-api").status_code == 401                              # wrong audience
    assert introspect(client, raw, lifetime=3600).status_code == 401                                     # long-lived
    # a customer session is not enough either
    assert client.post("/bff/internal/introspect", json={"key": raw}, headers=csrf(client)).status_code == 401


def test_keys_are_scoped_to_their_owner(client):
    signup(client)
    mine = create(client).json()
    client.cookies.clear()
    signup(client, email="other@example.com")
    assert client.get("/bff/auth/access-keys").json() == []
    assert client.delete(f"/bff/auth/access-keys/{mine['id']}", headers=csrf(client)).status_code == 404
