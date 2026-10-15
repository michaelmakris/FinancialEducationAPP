import pytest


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_instruments(client):
    r = client.get("/instruments")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 15
    tickers = {d["ticker"] for d in data}
    assert "AAPL" in tickers and "BTC" in tickers and "SPY" in tickers


def test_get_score_known_ticker(client):
    r = client.get("/scores/NVDA")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "NVDA"
    assert set(body["category_scores"].keys()) == {"value", "quality", "growth", "momentum", "risk", "macro"}
    assert "value" in body["breakdown"] and len(body["breakdown"]["value"]) > 0


def test_get_score_unknown_ticker_404(client):
    r = client.get("/scores/NOTATICKER")
    assert r.status_code == 404


def test_get_financials(client):
    r = client.get("/financials/AAPL")
    assert r.status_code == 200
    body = r.json()
    assert body["valuation"]["pe"] is not None
    assert body["market"]["last_close"] > 0


def test_compare_requires_at_least_two_tickers(client):
    r = client.post("/compare", json={"tickers": ["AAPL"]})
    assert r.status_code == 422  # pydantic min_length violation


def test_compare_two_tickers(client):
    r = client.post("/compare", json={"tickers": ["AAPL", "MSFT"]})
    assert r.status_code == 200
    body = r.json()
    assert "AAPL" in body and "MSFT" in body


def test_portfolio_lifecycle_buy_sell_reset(client, practice_market):
    r = client.post("/portfolio/reset")
    assert r.status_code == 200
    start = r.json()
    assert start["cash"] == start["starting_cash"] == 10000
    assert start["positions"] == []

    r = client.post("/portfolio/buy", json={"ticker": "TESTA.AT", "qty": 5})
    assert r.status_code == 200
    body = r.json()
    assert len(body["positions"]) == 1
    assert body["positions"][0]["qty"] == 5
    assert body["cash"] == pytest.approx(start["cash"] - 5 * 10.0)

    r = client.post("/portfolio/sell", json={"ticker": "TESTA.AT", "qty": 2})
    assert r.status_code == 200
    assert r.json()["positions"][0]["qty"] == 3

    r = client.post("/portfolio/sell", json={"ticker": "TESTA.AT", "qty": 100})
    assert r.status_code == 400

    r = client.post("/portfolio/reset")
    assert r.json()["positions"] == []


def test_watchlist_add_and_remove(client):
    client.post("/portfolio/watchlist/NVDA")
    r = client.get("/portfolio/watchlist")
    assert "NVDA" in r.json()
    client.delete("/portfolio/watchlist/NVDA")
    r = client.get("/portfolio/watchlist")
    assert "NVDA" not in r.json()


def test_simulate_endpoint(client):
    r = client.post("/simulate", json={
        "amount": 10000, "equities_pct": 60, "bonds_pct": 25, "crypto_pct": 10, "cash_pct": 5,
        "horizon_months": 12,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["p10"] <= body["median"] <= body["p90"]
    assert 0 <= body["prob_loss"] <= 1
