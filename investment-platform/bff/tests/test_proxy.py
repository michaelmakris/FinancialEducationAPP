import json

import jwt
import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Customer
from tests.conftest import PUBLIC_KEY, csrf, signup


def _claims(request):
    scheme, token = request.headers["authorization"].split(" ")
    assert scheme == "Bearer"
    return jwt.decode(token, PUBLIC_KEY, algorithms=["EdDSA"], audience="investment-api", issuer="bff")


def test_anonymous_cannot_use_the_api(client, api):
    assert client.get("/bff/api/v1/instruments").status_code == 401
    assert api.calls == []


def test_get_is_forwarded_with_a_short_lived_customer_token(client, api):
    customer_id = signup(client)["customer"]["id"]
    api.body = [{"ticker": "ETE.AT"}]
    r = client.get("/bff/api/v1/instruments", params={"country": "GR", "q": "bank"})
    assert r.status_code == 200 and r.json() == [{"ticker": "ETE.AT"}]
    assert "x-internal-secret" not in r.headers               # upstream headers do not leak
    sent = api.calls[-1]
    assert str(sent.url) == "http://api.internal/v1/instruments?country=GR&q=bank"
    assert "cookie" not in sent.headers                        # the session cookie never reaches the API
    claims = _claims(sent)
    assert claims["sub"] == customer_id
    assert claims["scope"] == "market:read portfolio:read portfolio:write chat"
    assert claims["exp"] - claims["iat"] == 60


def test_ticker_paths_with_special_characters(client, api):
    signup(client)
    assert client.get("/bff/api/v1/instruments/%5EGSPC/performance").status_code == 200
    assert api.calls[-1].url.path == "/v1/instruments/^GSPC/performance"  # decoded, as the API routes it


def test_writes_need_csrf_and_forward_the_body(client, api):
    signup(client)
    payload = {"ticker": "AAPL", "qty": 2}
    assert client.post("/bff/api/portfolio/buy", json=payload).status_code == 403
    assert api.calls == []
    r = client.post("/bff/api/portfolio/buy", json=payload, headers=csrf(client))
    assert r.status_code == 200
    assert json.loads(api.calls[-1].content) == payload


def test_chat_gets_a_longer_token(client, api):
    signup(client)
    client.post("/bff/api/chat", json={"message": "hi", "history": []}, headers=csrf(client))
    c = _claims(api.calls[-1])
    assert c["exp"] - c["iat"] == 300


@pytest.mark.parametrize("path", ["metrics", "docs", "openapi.json", "health", "v1/data-status",
                                  "v1/instruments/ETE.AT/secret", "portfolio/admin", "v2/anything"])
def test_only_allowlisted_routes_reach_the_api(client, api, path):
    signup(client)
    assert client.get(f"/bff/api/{path}").status_code == 404
    assert api.calls == []


@pytest.mark.parametrize("path", ["v1/instruments/%2e%2e/data-status", "v1/instruments/a%2Fb", "v1/instruments/ET E"])
def test_path_tricks_are_rejected(client, api, path):
    signup(client)
    assert client.get(f"/bff/api/{path}").status_code in (400, 404)
    assert api.calls == []


def test_staff_role_gets_ops_routes_and_scope(client, api):
    signup(client)
    db = SessionLocal()
    db.execute(select(Customer)).scalar_one().role = "staff"
    db.commit()
    db.close()
    assert client.get("/bff/api/v1/data-status").status_code == 200
    assert "ops:read" in _claims(api.calls[-1])["scope"]


def test_upstream_errors(client, api):
    signup(client)
    api.status, api.body = 404, {"detail": "Unknown ticker 'X'"}
    r = client.get("/bff/api/v1/instruments/X")
    assert r.status_code == 404 and r.json()["detail"] == "Unknown ticker 'X'"   # normal API errors pass through
    api.status = 401
    assert client.get("/bff/api/v1/instruments").status_code == 502              # API rejected our token: our fault
    api.down = True
    r = client.get("/bff/api/v1/instruments")
    assert r.status_code == 502 and "temporarily unavailable" in r.json()["detail"]


def test_metrics_count_proxy_traffic(client, api):
    signup(client)
    client.get("/bff/api/v1/instruments")
    client.get("/bff/api/metrics")
    text = client.get("/metrics").text
    assert 'bff_upstream_requests_total{route="v1/instruments",status="2xx"}' in text
    assert 'bff_proxy_denied_total{reason="not_allowed"}' in text
    assert 'bff_auth_events_total{event="register"}' in text


def test_token_rejection_is_counted_separately(client, api):
    signup(client)
    api.status = 401
    client.get("/bff/api/v1/instruments")
    assert 'bff_upstream_requests_total{route="v1/instruments",status="token_rejected"}' in client.get("/metrics").text


@pytest.mark.parametrize("method,path", [
    ("GET", "v1/predictions/instruments/ETE.AT"), ("GET", "v1/predictions/market"), ("GET", "v1/predictions/quality"),
    ("GET", "v1/predictions/models"), ("GET", "v1/profile/questionnaire"), ("GET", "v1/profile"), ("POST", "v1/profile"),
    ("POST", "v1/proposals"), ("GET", "v1/proposals"), ("GET", "v1/proposals/latest"), ("GET", "v1/proposals/12"),
    ("GET", "v1/llm/providers"),
])
def test_planning_routes_are_proxied(client, api, method, path):
    signup(client)
    r = client.request(method, f"/bff/api/{path}", json={} if method == "POST" else None,
                       headers=csrf(client) if method == "POST" else None)
    assert r.status_code == 200 and api.calls[-1].url.path == f"/{path}"


@pytest.mark.parametrize("path", ["v1/proposals/abc", "v1/predictions/instruments", "v1/profile/other"])
def test_planning_route_variants_not_on_the_list_are_refused(client, api, path):
    signup(client)
    assert client.get(f"/bff/api/{path}").status_code == 404 and api.calls == []


@pytest.mark.parametrize("method,path", [
    ("GET", "v1/markets"), ("GET", "v1/instruments/AAPL.US/intraday"), ("GET", "v1/instruments/BTC-EUR/intraday"),
    ("GET", "portfolio/intraday"), ("GET", "portfolio/transactions"), ("POST", "portfolio/buy"), ("POST", "portfolio/sell"),
    ("POST", "portfolio/reset"), ("POST", "v1/coach/pre-trade"), ("GET", "v1/coach/events"), ("GET", "v1/coach/tip"),
    ("GET", "v1/coach/learn/portfolio"), ("GET", "v1/coach/lessons/diversification"),
    ("GET", "portfolio/costs"), ("POST", "portfolio/cost-profile"),
])
def test_practice_trading_routes_are_proxied(client, api, method, path):
    signup(client)
    r = client.request(method, f"/bff/api/{path}", json={} if method == "POST" else None,
                       headers=csrf(client) if method == "POST" else None)
    assert r.status_code == 200 and api.calls[-1].url.path == f"/{path}"
