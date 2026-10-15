"""Practice portfolio on real instruments: live prices in EUR, cash after buys and sells,
realised gains, today's value curve, reset, markets and intraday quotes."""
import pytest

from app.services import quotes


@pytest.fixture
def fresh(client, practice_market):
    client.post("/portfolio/reset")
    return practice_market


def test_buy_takes_the_live_price_out_of_cash(client, fresh):
    body = client.post("/portfolio/buy", json={"ticker": "TESTA.AT", "qty": 10}).json()
    assert body["cash"] == pytest.approx(10000 - 10 * 10.0)
    pos = body["positions"][0]
    assert (pos["ticker"], pos["name"], pos["market"], pos["currency"]) == ("TESTA.AT", "Test Athens Co", "athens", "EUR")
    assert pos["avg_cost"] == pytest.approx(10.0) and pos["value"] == pytest.approx(100.0)
    assert pos["day_change_pct"] == pytest.approx(10.0 / 9.0 - 1)   # the stock's own move today
    assert body["total_value"] == pytest.approx(10000)               # bought at the current price: no gain yet


def test_usd_stock_is_converted_to_eur(client, fresh):
    body = client.post("/portfolio/buy", json={"ticker": "TSTUS.US", "qty": 2}).json()
    pos = body["positions"][0]
    assert pos["currency"] == "USD" and pos["price_local"] == pytest.approx(100.0)
    assert pos["price"] == pytest.approx(80.0)                        # 100 USD / 1.25
    assert body["cash"] == pytest.approx(10000 - 160.0)
    tx = client.get("/portfolio/transactions").json()[0]
    assert (tx["side"], tx["currency"], tx["fx_rate"], tx["amount"]) == ("buy", "USD", pytest.approx(0.8), pytest.approx(160.0))
    fresh["USD"] = 1.0                                                # the euro weakens: same dollars, more euros
    assert client.get("/portfolio").json()["positions"][0]["value"] == pytest.approx(200.0)


def test_sell_returns_proceeds_and_records_the_realised_gain(client, fresh):
    client.post("/portfolio/buy", json={"ticker": "TST-EUR", "qty": 4})          # 4 x 50 = 200
    fresh["TST-EUR"] = 60.0
    body = client.post("/portfolio/sell", json={"ticker": "TST-EUR", "qty": 1}).json()
    assert body["cash"] == pytest.approx(10000 - 200 + 60)
    assert body["realized_pnl"] == pytest.approx(10.0)
    assert body["positions"][0]["qty"] == pytest.approx(3) and body["positions"][0]["avg_cost"] == pytest.approx(50.0)
    fresh["TST-EUR"] = 40.0
    body = client.post("/portfolio/sell", json={"ticker": "TST-EUR", "qty": 3}).json()   # a loss this time
    assert body["positions"] == [] and body["cash"] == pytest.approx(10000 - 200 + 60 + 120)
    assert body["realized_pnl"] == pytest.approx(10.0 - 30.0)
    assert body["total_value"] == pytest.approx(9980.0) and body["total_pnl"] == pytest.approx(-20.0)
    sides = [t["side"] for t in client.get("/portfolio/transactions").json()]
    assert sides == ["sell", "sell", "buy"]                                       # newest first


def test_trades_are_refused_when_they_cannot_happen(client, fresh):
    assert client.post("/portfolio/buy", json={"ticker": "TESTA.AT", "qty": 2000}).status_code == 400  # 20,000 > cash
    assert client.post("/portfolio/sell", json={"ticker": "TESTA.AT", "qty": 1}).status_code == 400    # not held
    assert client.post("/portfolio/buy", json={"ticker": "NOPE.AT", "qty": 1}).status_code == 404
    assert client.post("/portfolio/buy", json={"ticker": "AAPL", "qty": 1}).status_code == 404         # demo-only ticker
    assert client.post("/portfolio/buy", json={"ticker": "TESTA.AT", "qty": 0}).status_code == 422


def test_intraday_curve_follows_trades_and_prices(client, fresh):
    flat = client.get("/portfolio/intraday").json()
    assert flat["start_value"] == pytest.approx(10000) and {p["value"] for p in flat["points"]} == {10000}

    client.post("/portfolio/buy", json={"ticker": "TESTA.AT", "qty": 100})       # 1,000 EUR at 10.00
    fresh["TESTA.AT"] = 12.0
    day = client.get("/portfolio/intraday").json()
    assert day["start_value"] == pytest.approx(10000)                            # nothing was held this morning
    assert day["points"][-1]["value"] == pytest.approx(10000 + 100 * 2.0)
    assert day["points"][-1]["cash"] == pytest.approx(9000)
    assert [t["side"] for t in day["trades"]] == ["buy"]
    values = [p["value"] for p in day["points"]]
    assert values[0] == pytest.approx(10000) and max(values) == pytest.approx(10200)
    summary = client.get("/portfolio").json()
    assert summary["day_change"] == pytest.approx(200.0)                          # same replay as the chart


def test_reset_starts_again_from_ten_thousand(client, fresh):
    client.post("/portfolio/buy", json={"ticker": "TESTA.AT", "qty": 50})
    client.post("/portfolio/sell", json={"ticker": "TESTA.AT", "qty": 10})
    body = client.post("/portfolio/reset").json()
    assert body["cash"] == body["total_value"] == 10000 and body["positions"] == [] and body["realized_pnl"] == 0
    assert client.get("/portfolio/transactions").json() == []


def test_markets_and_market_filter(client, fresh):
    markets = {m["id"]: m for m in client.get("/v1/markets").json()}
    assert {"athens", "us", "crypto"} <= set(markets) and markets["us"]["currency"] == "USD"
    assert all(m["tradable"] for k, m in markets.items() if k != "index")
    us = client.get("/v1/instruments", params={"market": "us"}).json()
    assert [r["ticker"] for r in us] == ["TSTUS.US"] and us[0]["market"] == "us"


def test_instrument_intraday_quote(client, fresh):
    q = client.get("/v1/instruments/TSTUS.US/intraday").json()
    assert q["currency"] == "USD" and q["last"] == pytest.approx(100.0) and q["last_eur"] == pytest.approx(80.0)
    assert q["tradable"] and q["live"] and len(q["points"]) == 2
    a = client.get("/v1/instruments/TESTA.AT/intraday").json()
    assert a["change_pct"] == pytest.approx(10.0 / 9.0 - 1)


def test_provider_outage_falls_back_to_the_daily_close(client, fresh, monkeypatch):
    def down(*a, **k):
        raise RuntimeError("provider down")

    from app.db import SessionLocal
    from app.models import Instrument
    from pipelines import market_writer as w
    import datetime as dt
    db = SessionLocal()
    inst = db.query(Instrument).filter_by(ticker="TESTA.AT").one()
    w.upsert_bars(db, inst, {dt.date.today() - dt.timedelta(days=1): {"close": 8.0}, dt.date.today(): {"close": 8.5}})
    db.commit()
    db.close()
    monkeypatch.setattr(quotes, "fetch_yahoo_intraday", down)
    q = client.get("/v1/instruments/TESTA.AT/intraday").json()
    assert q["live"] is False and q["last"] == pytest.approx(8.5) and q["prev_close"] == pytest.approx(8.0)
    assert client.post("/portfolio/buy", json={"ticker": "TESTA.AT", "qty": 1}).json()["cash"] == pytest.approx(10000 - 8.5)


def test_yahoo_and_binance_payloads_are_parsed():
    payload = {"chart": {"result": [{"meta": {"currency": "EUR", "chartPreviousClose": 9.5, "regularMarketPrice": 10.2,
                                              "regularMarketTime": 1_791_600_000,
                                              "currentTradingPeriod": {"regular": {"start": 0, "end": 1}}},
                                     "timestamp": [1_791_590_000, 1_791_590_300, 1_791_590_600],
                                     "indicators": {"quote": [{"close": [10.0, None, 10.1]}]}}]}}
    q = quotes.parse_yahoo_intraday("X.AT", payload)
    assert [p for _, p in q.points] == [10.0, 10.1, 10.2] and q.prev_close == 9.5 and q.market_open is False
    rows = [[1_791_590_000_000, "100", "0", "0", "101"], [1_791_590_300_000, "101", "0", "0", "99"]]
    b = quotes.parse_binance_intraday("B-EUR", rows)
    assert b.prev_close == 100.0 and b.last == 99.0 and b.market_open
