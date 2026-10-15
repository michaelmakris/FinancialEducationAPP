"""Transaction costs in the practice portfolio: estimates, ranges, what trades actually charge."""
import pytest

from app.services import costs


@pytest.fixture
def fresh(client, practice_market):
    client.post("/portfolio/reset")
    yield practice_market
    client.post("/portfolio/cost-profile", json={"profile": "none"})


def test_estimate_uses_percent_with_a_minimum():
    small = costs.estimate("athens", 100, "typical")          # 0.25% = 0.25 -> minimum 8
    assert small["commission"] == 8 and small["exchange"] == 0.03 and small["spread"] == 0.2
    assert small["total"] == pytest.approx(8.23) and small["pct"] == pytest.approx(0.0823)
    big = costs.estimate("athens", 10_000, "typical")         # 0.25% = 25 > 8
    assert big["commission"] == 25 and big["pct"] < 0.005
    us = costs.estimate("us", 1000, "high")
    assert us["fx"] == 10 and us["commission"] == 20
    assert costs.estimate("athens", 1000, "none")["total"] == 0
    r = costs.ranges("crypto", 1000)
    assert r["low"]["total"] < r["typical"]["total"] < r["high"]["total"]


def test_trades_charge_the_profile_costs(client, fresh):
    client.post("/portfolio/cost-profile", json={"profile": "typical"})
    est = client.get("/portfolio/costs", params={"ticker": "TESTA.AT", "qty": 10}).json()   # 10 x 10 = 100
    assert est["profile"] == "typical" and est["costs"]["total"] == pytest.approx(8.23)
    assert set(est["range"]) == {"low", "typical", "high"} and "typical" in est["profiles"]
    body = client.post("/portfolio/buy", json={"ticker": "TESTA.AT", "qty": 10}).json()
    assert body["cash"] == pytest.approx(10000 - 100 - 8.23)
    assert body["fees_paid"] == pytest.approx(8.23) and body["cost_profile"] == "typical"
    assert body["positions"][0]["avg_cost"] == pytest.approx(10.823)          # costs are part of what it cost
    assert body["total_value"] == pytest.approx(10000 - 8.23)                 # you start the trade down by the costs
    sold = client.post("/portfolio/sell", json={"ticker": "TESTA.AT", "qty": 10}).json()
    assert sold["cash"] == pytest.approx(10000 - 2 * 8.23)                    # selling costs the same again
    assert sold["realized_pnl"] == pytest.approx(-2 * 8.23) and sold["fees_paid"] == pytest.approx(16.46)
    log = client.get("/portfolio/transactions").json()
    assert [t["fees"] for t in log] == [pytest.approx(8.23), pytest.approx(8.23)]
    day = client.get("/portfolio/intraday").json()
    assert day["points"][-1]["cash"] == pytest.approx(10000 - 16.46)          # the replay includes costs


def test_costs_can_push_a_buy_over_the_cash(client, fresh):
    client.post("/portfolio/cost-profile", json={"profile": "high"})
    r = client.post("/portfolio/buy", json={"ticker": "TESTA.AT", "qty": 1000})   # 10,000 + costs > cash
    assert r.status_code == 400 and "costs" in r.json()["detail"]
    assert client.post("/portfolio/cost-profile", json={"profile": "luxury"}).status_code == 422


def test_tsimp_warns_about_costly_small_trades(client, fresh):
    client.post("/portfolio/cost-profile", json={"profile": "typical"})
    out = client.post("/v1/coach/pre-trade", json={"side": "buy", "ticker": "TST-EUR", "qty": 1, "lang": "en"}).json()
    assert "costly_trade" not in [n["id"] for n in out]                     # crypto: 0.65% of 50, no minimum
    small = client.post("/v1/coach/pre-trade", json={"side": "buy", "ticker": "TSTUS.US", "qty": 1, "lang": "en"}).json()
    assert "costly_trade" in [n["id"] for n in small]                       # 80 EUR with a 7 EUR minimum = ~9.5%


def test_chat_explains_costs_and_rates(client, fresh, monkeypatch):
    from app.services.agents import orchestrator
    monkeypatch.setattr(orchestrator, "run_chat", lambda m, h, lang="en": ("ai", [], []))
    r = client.post("/chat", json={"message": "what are transaction costs?", "history": []}).json()
    assert r["source"] == "rules" and r["lesson"]["id"] == "transaction_costs"
    r = client.post("/chat", json={"message": "σταθερό ή κυμαινόμενο επιτόκιο;", "history": [], "lang": "el"}).json()
    assert r["lesson"]["id"] == "fixed_vs_variable"
    r = client.post("/chat", json={"message": "how much have I paid in costs?", "history": []}).json()
    assert "Transaction costs so far" in r["reply"]
    assert client.get("/v1/coach/learn/loans", params={"lang": "el"}).json()["text"].startswith("Εδώ βλέπεις")
