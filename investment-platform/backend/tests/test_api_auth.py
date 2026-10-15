"""The API only serves callers holding a valid, short-lived token from a trusted
issuer (the BFF), and each customer only ever sees their own portfolio."""
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app import auth
from app.config import settings
from tests.conftest import CUSTOMER_SCOPES, auth_headers, make_token


def test_health_and_metrics_stay_open(raw_client):
    assert raw_client.get("/health").status_code == 200
    assert raw_client.get("/metrics").status_code == 200


@pytest.mark.parametrize("path", ["/v1/instruments", "/instruments", "/portfolio", "/v1/macro/indicators"])
def test_anonymous_calls_are_refused(raw_client, path):
    r = raw_client.get(path)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_chat_refused_without_token(raw_client):
    assert raw_client.post("/chat", json={"message": "hi", "history": []}).status_code == 401


@pytest.mark.parametrize("make_bad", [
    lambda: make_token(key=Ed25519PrivateKey.generate()),                       # forged: wrong key
    lambda: make_token(iat=int(time.time()) - 400, lifetime=60),                # expired
    lambda: make_token(aud="some-other-api"),                                   # wrong audience
    lambda: make_token(iss="mcp"),                                              # issuer not trusted (yet)
    lambda: make_token(lifetime=3600),                                          # too long-lived
    lambda: jwt.encode({"iss": "bff", "aud": "investment-api", "sub": "x", "iat": int(time.time()),
                        "exp": int(time.time()) + 60}, "secret", algorithm="HS256"),  # alg confusion
    lambda: jwt.encode({"iss": "bff", "aud": "investment-api", "sub": "x", "iat": int(time.time()),
                        "exp": int(time.time()) + 60}, None, algorithm="none"),       # unsigned
    lambda: "not-a-jwt",
])
def test_bad_tokens_are_refused(raw_client, make_bad):
    r = raw_client.get("/v1/instruments", headers={"Authorization": f"Bearer {make_bad()}"})
    assert r.status_code == 401, r.text
    assert r.json()["detail"] in ("Invalid or expired credentials", "Missing bearer token")


def test_scopes_are_enforced(raw_client):
    read_only = {"scope": "market:read"}
    assert raw_client.get("/v1/instruments", headers=auth_headers(**read_only)).status_code == 200
    r = raw_client.get("/portfolio", headers=auth_headers(**read_only))
    assert r.status_code == 403 and "portfolio:read" in r.json()["detail"]
    viewer = {"scope": "market:read portfolio:read"}
    assert raw_client.get("/portfolio", headers=auth_headers(**viewer)).status_code == 200
    assert raw_client.post("/portfolio/reset", headers=auth_headers(**viewer)).status_code == 403
    # customers do not get ops:read
    assert raw_client.get("/v1/data-status", headers=auth_headers()).status_code == 403
    assert raw_client.get("/v1/data-status", headers=auth_headers(scope=CUSTOMER_SCOPES + " ops:read")).status_code == 200


def test_unknown_scopes_in_token_are_ignored(raw_client):
    r = raw_client.get("/v1/data-status", headers=auth_headers(scope="market:read admin:* ops:read:extra"))
    assert r.status_code == 403


def test_each_customer_has_an_isolated_portfolio(raw_client, practice_market):
    alice, bob = auth_headers(sub="alice"), auth_headers(sub="bob")
    raw_client.post("/portfolio/reset", headers=alice)
    raw_client.post("/portfolio/reset", headers=bob)
    assert raw_client.post("/portfolio/buy", json={"ticker": "TESTA.AT", "qty": 3}, headers=auth_headers(sub="alice")).status_code == 200
    raw_client.post("/portfolio/watchlist/NVDA", headers=auth_headers(sub="alice"))
    a = raw_client.get("/portfolio", headers=auth_headers(sub="alice")).json()
    b = raw_client.get("/portfolio", headers=auth_headers(sub="bob")).json()
    assert [p["ticker"] for p in a["positions"]] == ["TESTA.AT"] and a["cash"] < 10000
    assert b["positions"] == [] and b["cash"] == 10000
    assert raw_client.get("/portfolio/watchlist", headers=auth_headers(sub="bob")).json() == []


def test_chat_agents_forward_the_callers_token(raw_client, monkeypatch):
    """The assistant's internal API calls carry the same customer token, so they
    are subject to the same permissions as the customer."""
    from app.services.agents import base, orchestrator

    seen = {}

    def fake_run_chat(message, history, lang="en"):
        seen["headers"] = auth.outbound_headers()
        return "ok", [], ["analysis"]

    monkeypatch.setattr(orchestrator, "run_chat", fake_run_chat)
    token = make_token(sub="carol")
    r = raw_client.post("/chat", json={"message": "tell me a story about markets", "history": []}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert seen["headers"] == {"Authorization": f"Bearer {token}"}
    assert base.get_backend.__code__.co_names.count("outbound_headers") == 1  # helper actually uses it


def test_disabled_mode_runs_as_dev_principal(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "api_auth_mode", "disabled")
    r = raw_client.get("/portfolio")
    assert r.status_code == 200


def test_missing_key_config_fails_closed(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "api_trusted_issuers", "bff=/does/not/exist.pem")
    auth.trusted_keys.cache_clear()
    try:
        assert raw_client.get("/v1/instruments", headers=auth_headers()).status_code == 503
    finally:
        monkeypatch.undo()
        auth.trusted_keys.cache_clear()


def test_a_second_trusted_issuer_gets_exactly_its_scopes(raw_client, monkeypatch, tmp_path):
    """The MCP server signs with its own key (iss=mcp); the API trusts it only once listed."""
    from cryptography.hazmat.primitives import serialization

    mcp_key = Ed25519PrivateKey.generate()
    pub = tmp_path / "mcp_pub.pem"
    pub.write_bytes(mcp_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    token = make_token(sub="dana", iss="mcp", key=mcp_key, scope="market:read portfolio:read")
    assert raw_client.get("/v1/instruments", headers={"Authorization": f"Bearer {token}"}).status_code == 401  # not trusted yet
    monkeypatch.setattr(settings, "api_trusted_issuers", settings.api_trusted_issuers + f",mcp={pub}")
    auth.trusted_keys.cache_clear()
    try:
        h = {"Authorization": f"Bearer {token}"}
        assert raw_client.get("/v1/instruments", headers=h).status_code == 200
        assert raw_client.get("/portfolio", headers=h).status_code == 200
        assert raw_client.post("/portfolio/reset", headers=h).status_code == 403   # key has no portfolio:write
        assert raw_client.post("/chat", json={"message": "x", "history": []}, headers=h).status_code == 403
        # an mcp token cannot pass as the bff: the issuer picks the key
        forged = make_token(sub="dana", iss="bff", key=mcp_key)
        assert raw_client.get("/v1/instruments", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    finally:
        monkeypatch.undo()
        auth.trusted_keys.cache_clear()
