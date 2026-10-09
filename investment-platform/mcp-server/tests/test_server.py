import json

import httpx2
import pytest

from tests.conftest import client_for, connect, raw_http, run, running


def _data(result):
    """Structured content if present, else the JSON text block."""
    if getattr(result, "structured_content", None) is not None:
        sc = result.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(result.content[0].text)


def _text(result):
    return " ".join(getattr(c, "text", "") for c in result.content)


def test_lists_all_tools_with_hints(mcp_app):
    async def go():
        async with connect(mcp_app, "fea_mcp_read_key") as c:
            return (await c.list_tools()).tools
    tools = {t.name: t for t in run(go())}
    assert len(tools) == 18
    assert tools["get_risk_estimates"].annotations.read_only_hint is True
    assert tools["get_fundamentals"].annotations.read_only_hint is True
    assert tools["place_virtual_trade"].annotations.read_only_hint is False


def test_missing_or_invalid_key_is_rejected(mcp_app):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    accept = {"Accept": "application/json, text/event-stream"}

    async def go():
        async with running(mcp_app), raw_http(mcp_app) as hc:
            return [await hc.post("/mcp", json=body, headers={**accept, **h}) for h in
                    ({}, {"Authorization": "Bearer fea_mcp_unknown"}, {"Authorization": "Bearer some-other-token"})]
    none, unknown, other = run(go())
    assert none.status_code == 401 and "resource_metadata" in none.headers.get("www-authenticate", "")
    assert unknown.status_code == 401 and other.status_code == 401


def test_read_tool_calls_api_as_the_customer_with_key_scopes(mcp_app, backends):
    async def go():
        async with connect(mcp_app, "fea_mcp_read_key") as c:
            return await c.call_tool("search_instruments", {"query": "bank", "country": "GR"})
    result = run(go())
    assert not result.is_error and _data(result)[0]["ticker"] == "ETE.AT"
    request, claims = backends.api_calls[-1]
    assert claims["sub"] == "cust-1" and claims["iss"] == "mcp"
    assert claims["scope"] == "market:read portfolio:read" and claims["exp"] - claims["iat"] == 60
    assert dict(request.url.params) == {"q": "bank", "country": "GR"}  # None-valued filters not sent


def test_read_only_key_cannot_trade(mcp_app, backends):
    async def go():
        async with connect(mcp_app, "fea_mcp_read_key") as c:
            return await c.call_tool("place_virtual_trade", {"side": "buy", "ticker": "AAPL", "quantity": 1})
    result = run(go())
    assert result.is_error and "read-only" in _text(result)
    assert backends.api_calls == []  # refused before reaching the API


def test_trade_key_can_trade(mcp_app, backends):
    async def go():
        async with connect(mcp_app, "fea_mcp_trade_key") as c:
            return await c.call_tool("place_virtual_trade", {"side": "buy", "ticker": "AAPL", "quantity": 1})
    result = run(go())
    assert not result.is_error and _data(result)["cash"] == 9000
    request, claims = backends.api_calls[-1]
    assert request.url.path == "/portfolio/buy" and json.loads(request.content) == {"ticker": "AAPL", "qty": 1}
    assert claims["sub"] == "cust-2" and "portfolio:write" in claims["scope"]


def test_api_errors_become_clear_tool_errors(mcp_app, backends):
    async def go():
        async with connect(mcp_app, "fea_mcp_read_key") as c:
            missing = await c.call_tool("get_instrument", {"ticker": "XYZ"})
            backends.api_status = 503
            down = await c.call_tool("get_instrument", {"ticker": "ETE.AT"})
            return missing, down
    missing, down = run(go())
    assert missing.is_error and "Unknown ticker 'XYZ'" in _text(missing)
    assert down.is_error and "market data service had an error" in _text(down)


def test_large_outputs_are_bounded(mcp_app, backends):
    async def go():
        async with connect(mcp_app, "fea_mcp_read_key") as c:
            prices = await c.call_tool("get_price_history", {"ticker": "BTC-EUR", "start": "2020-01-01", "end": "2026-10-01"})
            comp = await c.call_tool("compare_instruments", {"tickers": ["A", "B"]})
            return prices, comp
    prices, comp = run(go())
    p = _data(prices)
    assert p["interval"] == "monthly" and len(p["bars"]) == 400 and p["truncated"] is True
    pts = _data(comp)["points"]
    assert len(pts) == 120 and pts[0]["date"] == "0" and pts[-1]["date"] == "365"


def test_key_checks_are_cached_and_revocation_applies_after_expiry(mcp_app, backends):
    from app import auth

    async def go():
        async with running(mcp_app):
            async with client_for(mcp_app, "fea_mcp_read_key") as c:
                for _ in range(3):
                    await c.call_tool("get_crypto_market", {})
            first = backends.introspections
            backends.revoked.add("fea_mcp_read_key")
            for v in [o for o in __import__("gc").get_objects() if isinstance(o, auth.AccessKeyVerifier)]:
                v._cache.clear()   # simulate the 30 s cache expiring
            async with raw_http(mcp_app, {"Authorization": "Bearer fea_mcp_read_key"}) as hc:
                r = await hc.post("/mcp", headers={"Accept": "application/json, text/event-stream"},
                                  json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            return first, r.status_code
    first, status = run(go())
    assert first == 1      # one BFF check for several calls
    assert status == 401   # revoked key refused once the cache entry is gone


def test_bff_outage_fails_closed(mcp_app, backends):
    backends.bff_down = True
    with pytest.raises(Exception):
        async def go():
            async with connect(mcp_app, "fea_mcp_read_key") as c:
                await c.list_tools()
        run(go())


def test_per_key_rate_limit(mcp_app, backends, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "calls_per_minute", 2)

    async def go():
        async with connect(mcp_app, "fea_mcp_read_key") as c:
            return [await c.call_tool("get_crypto_market", {}) for _ in range(3)]
    results = run(go())
    assert [r.is_error for r in results] == [False, False, True] and "Too many requests" in _text(results[2])


def test_metrics_and_health(mcp_app, backends):
    async def go():
        async with running(mcp_app):
            async with client_for(mcp_app, "fea_mcp_read_key") as c:
                await c.call_tool("get_crypto_market", {})
            async with raw_http(mcp_app) as hc:
                return (await hc.get("/health")).json(), (await hc.get("/metrics")).text
    health, metrics = run(go())
    assert health == {"status": "ok"}
    assert 'mcp_tool_calls_total{outcome="ok",tool="get_crypto_market"}' in metrics
    assert 'mcp_auth_total{result="valid"}' in metrics
