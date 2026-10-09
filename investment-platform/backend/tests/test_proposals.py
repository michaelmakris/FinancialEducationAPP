"""Risk questionnaire, allocation engine, narrative guardrails, portfolio comparison and the proposals API."""
import json

import pandas as pd
import pytest
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import (Indicator, IndicatorObservation, Instrument, ModelPrediction, ModelVersion, PipelineRun, PriceBar,
                        Proposal, RiskAssessment)
from pipelines import catalog, market_writer as w
from proposals import analysis, engine, narrative, questionnaire
from tests.conftest import auth_headers
from tests.test_forecasting import garch_prices

CAUTIOUS = dict(horizon="1_3", cushion="lt3", share="gt75", income="variable", drop="sell_some", goal="income",
                range="moderate", knowledge="none")
BOLD = dict(horizon="gt10", cushion="gt6", share="lt25", income="very_stable", drop="buy_more", goal="max_growth",
            range="very_wide", knowledge="complex")


# ---------------------------------------------------------------- questionnaire
def test_profile_is_the_lower_of_capacity_tolerance_and_horizon():
    bold = questionnaire.assess(BOLD)
    assert bold["profile"] == 7 and bold["crypto_allowed"] is True
    cautious = questionnaire.assess(CAUTIOUS)
    assert cautious["profile"] <= 3 and cautious["crypto_allowed"] is False
    short = questionnaire.assess({**BOLD, "horizon": "lt1"})
    assert short["profile"] == 1 and any("short horizon" in r for r in short["reasons"])
    low_capacity = questionnaire.assess({**BOLD, "cushion": "none", "share": "gt75", "income": "unstable"})
    assert low_capacity["profile"] == 1 and low_capacity["emergency_fund_first"] is True


def test_knowledge_gates_crypto_without_changing_the_profile():
    a = questionnaire.assess({**BOLD, "knowledge": "stocks"})
    assert a["profile"] == 7 and a["crypto_allowed"] is False


def test_invalid_answers():
    with pytest.raises(questionnaire.InvalidAnswers, match="missing"):
        questionnaire.assess({"horizon": "gt10"})
    with pytest.raises(questionnaire.InvalidAnswers, match="not an option"):
        questionnaire.assess({**BOLD, "drop": "panic"})
    assert "points" not in json.dumps(questionnaire.public()) and len(questionnaire.public()["questions"]) == 8


# ---------------------------------------------------------------- engine
def _inputs(**kw):
    base = dict(sleeve_vol={"bonds": 0.06, "global_equity": 0.15, "greek_equity": 0.20, "crypto": 0.60},
                correlations={("global_equity", "greek_equity"): 0.6, ("crypto", "global_equity"): 0.3})
    base.update(kw)
    return engine.MarketInputs(**base)


@pytest.mark.parametrize("profile", range(1, 8))
def test_allocations_sum_to_100_and_respect_the_band(profile):
    a = engine.allocate(profile, crypto_allowed=True, m=_inputs())
    assert sum(a["weights"].values()) == pytest.approx(100.0)
    assert a["expected_volatility"] <= engine.VOL_BAND[profile] + 1e-9


def test_crypto_moves_to_global_equity_when_not_allowed():
    a = engine.allocate(6, crypto_allowed=False, m=_inputs())
    assert a["weights"]["crypto"] == 0 and a["weights"]["global_equity"] >= engine.STRATEGIC[6]["global_equity"] + engine.STRATEGIC[6]["crypto"] - 0.1
    assert any(s["step"] == "no_crypto" for s in a["steps"])


def test_stressed_markets_shift_equity_to_cash_for_moderate_profiles_only():
    calm = engine.allocate(4, False, _inputs(conditions_label="calm"))
    stressed = engine.allocate(4, False, _inputs(conditions_label="stressed"))
    assert stressed["weights"]["cash"] == pytest.approx(calm["weights"]["cash"] + engine.STRESS_SHIFT)
    assert any(s["step"] == "stressed_markets" for s in stressed["steps"])
    assert not any(s["step"] == "stressed_markets" for s in engine.allocate(7, True, _inputs(conditions_label="stressed"))["steps"])


def test_volatility_cap_scales_risky_sleeves_into_cash():
    wild = _inputs(sleeve_vol={"bonds": 0.2, "global_equity": 0.6, "greek_equity": 0.8, "crypto": 1.5})
    a = engine.allocate(4, False, wild)
    cap = next(s for s in a["steps"] if s["step"] == "volatility_cap")
    assert a["expected_volatility"] == pytest.approx(engine.VOL_BAND[4], rel=1e-6)
    assert a["weights"]["cash"] > engine.STRATEGIC[4]["cash"] and "scaled" in cap["detail"]


def test_portfolio_vol_and_stress_arithmetic():
    m = _inputs()
    assert engine.portfolio_vol({"global_equity": 1.0}, m) == pytest.approx(0.15)
    assert engine.portfolio_vol({"cash": 1.0}, m) == 0
    res = {s["scenario"]: s for s in engine.stress({"cash": 50, "global_equity": 50}, m)}
    assert res["equity_crash"]["portfolio_return"] == pytest.approx(-0.15) and res["equity_crash"]["on_10000_eur"] == -1500


# ---------------------------------------------------------------- narrative guardrails
SOURCE = "Your mix has expected volatility about 11% a year; worst case loses 33%, or €3,333 on €10,000."


def test_validator_accepts_a_faithful_rewrite():
    ok = "Expect swings of about 11% a year. In a bad crash you could lose 33% (€3,333 of €10,000)."
    assert narrative.validate(ok, SOURCE) is None


@pytest.mark.parametrize("bad,reason", [
    ("Expect about 12% a year of swings.", "numbers not in the facts"),
    ("You should buy more Greek shares; volatility is 11%.", "advice"),
    ("This mix will rise over time, 11%.", "advice"),
    ("Returns are guaranteed at 11%.", "advice"),
    ("This mix could return 11% a year.", "advice"),
    ("Expect gains of 33% next year.", "advice"),
    ("The expected return is 11%.", "advice"),
    ("", "empty"),
])
def test_validator_rejects_invented_numbers_and_advice(bad, reason):
    assert reason in (narrative.validate(bad, SOURCE) or "")


def test_ai_rewrite_falls_back_to_the_template(monkeypatch):
    monkeypatch.setattr(narrative, "_call_llm", lambda s, u: "You should buy now, it will rise 50%.")
    text, src = narrative.ai_rewrite(SOURCE, {})
    assert text == SOURCE and src.startswith("template (ai rejected")

    def down(s, u):
        raise ConnectionError("llm offline")
    monkeypatch.setattr(narrative, "_call_llm", down)
    text, src = narrative.ai_rewrite(SOURCE, {})
    assert text == SOURCE and "ai unavailable" in src
    monkeypatch.setattr(narrative, "_call_llm", lambda s, u: "Swings of about 11% a year are normal for this mix.")
    assert narrative.ai_rewrite(SOURCE, {}) == ("Swings of about 11% a year are normal for this mix.", "ai")


# ---------------------------------------------------------------- practice-portfolio comparison
def test_analysis_maps_holdings_and_flags_concentration():
    pf = {"total_value": 10000, "cash": 2000, "positions": [
        {"ticker": "NVDA", "value": 6000}, {"ticker": "AGG", "value": 1000}, {"ticker": "BTC", "value": 1000}]}
    close = list(range(100, 400))
    inst = {"NVDA": {"asset_type": "equity", "sector": "Technology", "close": close},
            "AGG": {"asset_type": "etf", "sector": "Broad Market Bonds", "close": close},
            "BTC": {"asset_type": "crypto", "sector": "Crypto", "close": close}}
    res = analysis.analyse(pf, inst, {"cash": 10, "bonds": 35, "global_equity": 40, "greek_equity": 15, "crypto": 0})
    assert res["weights_pct"] == {"cash": 20.0, "bonds": 10.0, "global_equity": 60.0, "greek_equity": 0.0, "crypto": 10.0}
    codes = {f["code"] for f in res["flags"]}
    assert {"concentration", "bonds_under", "global_equity_over", "crypto_outside_profile"} <= codes


# ---------------------------------------------------------------- API end to end (temp DB)
@pytest.fixture
def market(client):
    db = SessionLocal()
    for t, kind, freq in (("URTH", "etf", "B"), ("GD.AT", "index", "B"), ("BTC-EUR", "crypto", "D"), ("BELA.AT", "equity", "B")):
        inst = w.ensure_instrument(db, ticker=t, name=t, sector="Retail" if t == "BELA.AT" else "Index", asset_type=kind,
                                   exchange="", currency="EUR", data_source="yahoo", country="GR")
        px = garch_prices(1400, seed=hash(t) % 100, start="2019-06-03", freq=freq)
        w.upsert_bars(db, inst, {d.date(): {"open": v, "high": v, "low": v, "close": v, "volume": 1.0, "adj_close": v} for d, v in px.items()})
    w.ensure_indicator(db, catalog.INDICATORS_BY_ID["ggb_10y"])
    months = pd.date_range("2018-01-01", "2026-09-01", freq="MS")
    w.upsert_observations(db, "ggb_10y", [(d.date(), 4.0 + 0.1 * (i % 7)) for i, d in enumerate(months)])
    db.commit()
    from pipelines import jobs
    jobs.run_job("forecasts", SessionLocal, only=["volatility", "regime"])
    yield
    db.execute(delete(Proposal))
    db.execute(delete(RiskAssessment))
    db.execute(delete(ModelPrediction))
    db.execute(delete(ModelVersion))
    ids = [i.id for i in db.execute(select(Instrument).where(Instrument.data_source != "simulated")).scalars()]
    db.execute(delete(PriceBar).where(PriceBar.instrument_id.in_(ids)))
    db.execute(delete(Instrument).where(Instrument.id.in_(ids)))
    db.execute(delete(IndicatorObservation))
    db.execute(delete(Indicator))
    db.execute(delete(PipelineRun).where(PipelineRun.pipeline.like("market.%")))
    db.commit()
    db.close()


def test_proposal_flow_end_to_end(raw_client, market):
    me = auth_headers(sub="planner-1")
    assert raw_client.get("/v1/profile/questionnaire", headers=me).json()["version"] == 1
    assert raw_client.get("/v1/profile", headers=me).status_code == 404
    assert raw_client.post("/v1/proposals", headers=auth_headers(sub="planner-1"), json={}).status_code == 409
    assert raw_client.post("/v1/profile", headers=auth_headers(sub="planner-1"), json={"answers": {"horizon": "gt10"}}).status_code == 422
    prof = raw_client.post("/v1/profile", headers=auth_headers(sub="planner-1"), json={"answers": BOLD})
    assert prof.status_code == 201 and prof.json()["profile"] == 7

    r = raw_client.post("/v1/proposals", headers=auth_headers(sub="planner-1"), json={})
    assert r.status_code == 201, r.text
    p = r.json()
    assert sum(a["weight_pct"] for a in p["allocation"]) == pytest.approx(100)
    assert p["expected_volatility"] <= p["volatility_band"] and p["narrative_source"] == "template"
    assert "not investment advice" in p["disclaimer"] and p["sources"]["proxies"]["global_equity"].startswith("URTH")
    assert any(s["historical"] for s in p["stress_tests"])           # the real 2020 replay is included
    assert p["current"]["weights_pct"]["cash"] == 100.0               # fresh practice portfolio is all cash
    assert "all cash" in p["narrative"]

    latest = raw_client.get("/v1/proposals/latest", headers=auth_headers(sub="planner-1")).json()
    assert latest["id"] == p["id"]
    assert [x["id"] for x in raw_client.get("/v1/proposals", headers=auth_headers(sub="planner-1")).json()] == [p["id"]]
    # someone else can't read it
    assert raw_client.get(f"/v1/proposals/{p['id']}", headers=auth_headers(sub="someone-else")).status_code == 404
    # read-only callers (e.g. a read-only MCP key) can read but not generate
    ro = auth_headers(sub="planner-1", scope="market:read portfolio:read")
    assert raw_client.get("/v1/proposals/latest", headers=ro).status_code == 200
    assert raw_client.post("/v1/proposals", headers=ro, json={}).status_code == 403


def test_ai_narrative_is_rejected_when_it_invents_numbers(raw_client, market, monkeypatch):
    raw_client.post("/v1/profile", headers=auth_headers(sub="planner-2"), json={"answers": CAUTIOUS})
    # an invented number
    monkeypatch.setattr(narrative, "_call_llm", lambda s, u: "Your portfolio is 37% safer than average.")
    p = raw_client.post("/v1/proposals", headers=auth_headers(sub="planner-2"), json={"use_ai": True}).json()
    assert "numbers not in the facts" in p["narrative_source"] and "37%" not in p["narrative"]
    # a real number from the facts (cash is 25% for this profile) turned into a promise
    monkeypatch.setattr(narrative, "_call_llm", lambda s, u: "Your portfolio could return 25% next year.")
    p = raw_client.post("/v1/proposals", headers=auth_headers(sub="planner-2"), json={"use_ai": True}).json()
    assert "advice/promise language" in p["narrative_source"] and "next year" not in p["narrative"]
