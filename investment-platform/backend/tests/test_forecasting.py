"""Forecasting models on synthetic data with known answers, the registry rules,
the end-to-end job, and the /v1/predictions API."""
import datetime as dt
import json
import math

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import Instrument, ModelPrediction, ModelVersion, PipelineRun, PriceBar
from forecasting import direction, quality, regime, registry, volatility
from pipelines import market_writer as w

RNG = np.random.default_rng(7)


def garch_prices(n=1800, omega=2e-6, alpha=0.10, beta=0.87, seed=0, start="2018-01-01", freq="B"):
    rng = np.random.default_rng(seed)
    var, r = omega / (1 - alpha - beta), []
    for _ in range(n):
        x = rng.standard_normal() * math.sqrt(var)
        r.append(x)
        var = omega + alpha * x * x + beta * var
    idx = pd.date_range(start, periods=n + 1, freq=freq)
    return pd.Series(100 * np.exp(np.concatenate([[0], np.cumsum(r)])), index=idx)


def random_walk(n=1800, vol=0.01, seed=0, start="2018-01-01", freq="B"):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n + 1, freq=freq)
    return pd.Series(100 * np.exp(np.concatenate([[0], np.cumsum(rng.normal(0, vol, n))])), index=idx)


# ---------------------------------------------------------------- volatility
def test_volatility_models_beat_last_year_vol_on_garch_data():
    panel = {f"A{i}": garch_prices(seed=i) for i in range(3)}
    ev = volatility.evaluate(panel, eval_years=3)
    assert ev["n_forecasts"] > 50 and ev["n_assets"] == 3
    assert ev["qlike"]["garch_1_1"] < ev["qlike"]["historical_252"]
    assert ev["qlike"]["ewma_0.94"] < ev["qlike"]["historical_252"]
    method, approved, reason, p_method = volatility.choose(ev)
    assert approved and method in ("garch_1_1", "ewma_0.94") and "beats" in reason
    rows = volatility.predict(panel, {t: "equity" for t in panel}, method, p_method)
    vols = [r for r in rows if r["target"] == "vol_21d_annualized"]
    assert len(vols) == 3 and all(0.02 < r["value"] < 2 for r in vols)
    assert all(0 <= r["value"] <= 1 for r in rows if r["target"] == "p_loss_10pct_21d")


def test_baseline_is_served_when_no_candidate_wins():
    ev = {"qlike": {"historical_252": -9.0, "ewma_0.94": -8.9, "garch_1_1": float("nan")},
          "brier_p_loss": {"historical_252": 0.02, "ewma_0.94": 0.03, "garch_1_1": float("nan")}, "brier_p_loss_empirical": 0.025}
    method, approved, reason, p_method = volatility.choose(ev)
    assert method == "historical_252" and approved and "baseline" in reason and p_method == "model"


def test_loss_probability_rises_with_volatility():
    assert volatility.p_loss(0.0001) < volatility.p_loss(0.0004) < volatility.p_loss(0.0016) < 0.5
    assert volatility.qlike(1.0, 1.0) == pytest.approx(1.0)


def test_periods_per_year_tells_crypto_from_stocks():
    assert 245 < volatility.periods_per_year(random_walk(800).index) < 265
    assert 355 < volatility.periods_per_year(random_walk(800, freq="D").index) < 370


def test_beta_against_benchmark():
    bench = random_walk(600, seed=1)
    noise = random_walk(600, vol=0.002, seed=2)
    asset = (bench / bench.iloc[0]) ** 1.5 * (noise / noise.iloc[0]) * 100  # ~1.5x the benchmark's moves
    b, corr = volatility.beta(asset, bench)
    assert b == pytest.approx(1.5, abs=0.1) and corr > 0.95


# ---------------------------------------------------------------- regime
def test_macro_values_are_used_only_after_publication():
    s = pd.Series([1.0, 9.0], index=pd.DatetimeIndex(["2026-08-01", "2026-09-01"]))  # monthly periods
    public = regime.known_at(s, "M", 20)                                               # published ~20 days after month end
    assert regime.value_at(public, pd.Timestamp("2026-09-30")) == 1.0   # September value not public on 30 Sep
    assert regime.value_at(public, pd.Timestamp("2026-10-21")) == 9.0


def _regime_frame(signal: bool, months=140, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2012-01-31", periods=months, freq="ME")
    df = pd.DataFrame({f: rng.normal(size=months) for f in regime.FEATURES}, index=idx)
    logits = 2.5 * df["vix"] - 1.5 if signal else np.full(months, -1.2)
    df["stress"] = (rng.random(months) < 1 / (1 + np.exp(-logits))).astype(float)
    df["outcome_end"] = idx + pd.Timedelta(days=28)
    return df


def test_regime_model_approved_only_when_there_is_signal():
    ev = regime.evaluate(_regime_frame(signal=True))
    ok, reason = regime.decide(ev)
    assert ok and ev["auc"] > 0.7 and ev["bss"] > 0, reason
    ev_noise = regime.evaluate(_regime_frame(signal=False))
    ok_noise, reason_noise = regime.decide(ev_noise)
    assert not ok_noise and "did not beat" in reason_noise


def test_regime_prediction_explains_its_drivers():
    row, params = regime.fit_and_predict(_regime_frame(signal=True))
    assert row["subject"] == "market:GR" and 0 <= row["value"] <= 1
    coefs = params["coefficients"]
    assert max(coefs, key=lambda f: abs(coefs[f])) == "vix" and coefs["vix"] > 0   # the planted signal dominates
    drivers = list(row["details"]["drivers_log_odds"].values())                    # this month's contributions,
    assert drivers == sorted(drivers, key=abs, reverse=True) and len(drivers) == len(regime.FEATURES)  # largest first
    assert row["details"]["current_regime"] in ("calm", "normal", "stressed")


def test_regime_dataset_labels_and_no_future_leak():
    px = random_walk(1500, seed=5)
    ds = regime.build_dataset(px, {"vix": pd.Series([20.0], index=pd.DatetimeIndex(["2017-01-02"]))})
    labelled = ds.dropna(subset=["stress"])
    assert set(labelled["stress"].unique()) <= {0.0, 1.0}
    assert (labelled["outcome_end"] > labelled.index).all()   # outcome strictly after the feature date
    assert pd.isna(ds["stress"].iloc[-1])                    # last month still open


# ---------------------------------------------------------------- direction
def test_direction_model_is_rejected_on_a_random_walk():
    panel = {f"R{i}": random_walk(2500, seed=10 + i) for i in range(6)}
    df = direction.build_panel(panel, panel["R0"])
    ev = direction.evaluate(df)
    ok, reason = direction.decide(ev)
    assert ev["n_test_months"] >= direction.MIN_TEST_MONTHS
    assert not ok and "not served" in reason


# ---------------------------------------------------------------- quality
def _fund(sector, **ratios):
    base = {"roe": None, "roa": None, "net_margin": None, "operating_margin": None, "equity_ratio": None,
            "current_ratio": None, "revenue_growth": None, "net_income_growth": None, "payout_ratio": None, "free_cash_flow": None}
    return {"sector": sector, "fiscal_year_end": dt.date(2024, 12, 31), "ratios": {**base, **ratios}, "metrics": {"revenue": 100.0}}


def test_quality_ranks_within_peer_groups():
    funds = {
        "BANK1": _fund("Banks", roe=0.15, roa=0.012, equity_ratio=0.11),
        "BANK2": _fund("Banks", roe=0.08, roa=0.006, equity_ratio=0.08),
        "BANK3": _fund("Banks", roe=0.11, roa=0.009, equity_ratio=0.09),
        "IND1": _fund("Industrials", roe=0.20, operating_margin=0.15, net_margin=0.1, equity_ratio=0.5),
        "IND2": _fund("Retail", roe=0.05, operating_margin=0.03, net_margin=0.02, equity_ratio=0.3),
        "IND3": _fund("Energy", roe=0.10, operating_margin=0.08, net_margin=0.05, equity_ratio=0.4),
        "THIN": _fund("Energy", roe=0.30),  # one component only: not scored
    }
    scores = {r["subject"]: r for r in quality.score(funds)}
    assert "THIN" not in scores
    assert scores["BANK1"]["value"] == 100 and scores["BANK2"]["value"] < scores["BANK3"]["value"]
    assert scores["IND1"]["value"] > scores["IND3"]["value"] > scores["IND2"]["value"]
    assert scores["BANK1"]["details"]["peer_group"] == "banks" and scores["IND1"]["details"]["peer_group"] == "non-banks"


# ---------------------------------------------------------------- registry, job and API (temp DB)
@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.rollback()
    s.execute(delete(ModelPrediction))
    s.execute(delete(ModelVersion))
    ids = [i.id for i in s.execute(select(Instrument).where(Instrument.data_source != "simulated")).scalars()]
    s.execute(delete(PriceBar).where(PriceBar.instrument_id.in_(ids)))
    s.execute(delete(Instrument).where(Instrument.id.in_(ids)))
    s.execute(delete(PipelineRun).where(PipelineRun.pipeline.like("market.%")))
    s.commit()
    s.close()


def test_registry_versions_and_serving_rules(db):
    a = registry.register(db, model_name="m", algorithm="x", metrics={"auc": float("nan")}, baseline={}, params={},
                          approved=False, reason="did not beat baseline")
    with pytest.raises(ValueError):
        registry.save_predictions(db, a, dt.date(2026, 10, 1), [{"subject": "S", "target": "t", "value": 1.0}])
    b = registry.register(db, model_name="m", algorithm="x", metrics={}, baseline={}, params={}, approved=True, reason="ok")
    assert (a.version, b.version) == (1, 2)
    assert json.loads(a.metrics_json) == {"auc": None}  # NaN stored as null
    registry.save_predictions(db, b, dt.date(2026, 10, 1), [{"subject": "S", "target": "t", "value": 1.0},
                                                             {"subject": "S", "target": "u", "value": float("nan")}])
    registry.save_predictions(db, b, dt.date(2026, 10, 1), [{"subject": "S", "target": "t", "value": 2.0}])  # same day: replaced
    db.commit()
    preds = registry.latest_predictions(db, "m", "S")
    assert [(p.target, p.value) for p in preds] == [("t", 2.0)]
    assert registry.latest_versions(db)["m"].version == 2


def _load(db, ticker, prices, asset_type="equity", sector="Banks"):
    inst = w.ensure_instrument(db, ticker=ticker, name=ticker, sector=sector, asset_type=asset_type, exchange="",
                               currency="EUR", data_source="yahoo", country="GR")
    w.upsert_bars(db, inst, {d.date(): {"open": v, "high": v, "low": v, "close": v, "volume": 1.0, "adj_close": v}
                             for d, v in prices.items()})
    return inst


def test_forecast_job_end_to_end_and_api(db, client, staff_client):
    _load(db, "GD.AT", garch_prices(1300, seed=1), asset_type="index", sector="Index")
    _load(db, "ETE.AT", garch_prices(1300, seed=2))
    _load(db, "BTC-EUR", garch_prices(1300, seed=3, freq="D"), asset_type="crypto", sector="Crypto")
    db.commit()
    from pipelines import jobs
    res = jobs.run_job("forecasts", SessionLocal)
    assert res.items == 4, res.detail()            # every model ran (some may be rejected)
    assert registry.latest_versions(db)["conditions"].status == "approved"
    versions = registry.latest_versions(db)
    assert versions["volatility"].status == "approved"
    assert versions["quality"].status == "rejected"  # no annual reports in this DB
    run = db.execute(select(PipelineRun).where(PipelineRun.pipeline == "market.forecasts")).scalars().all()[-1]
    assert run.status == "ok"

    r = client.get("/v1/predictions/instruments/ETE.AT").json()
    assert 0 < r["risk"]["vol_21d_annualized"]["value"] < 2
    assert r["risk"]["vol_21d_annualized"]["details"]["benchmark"] == "GD.AT"
    assert r["quality"]["status"] == "not_available"
    assert r["direction"]["status"] in ("not_served", "not_available") or "value" in r["direction"]
    assert r["models"]["volatility"]["status"] == "approved" and "not investment advice" in r["disclaimer"]
    crypto = client.get("/v1/predictions/instruments/BTC-EUR").json()
    assert crypto["quality"]["status"] == "not_applicable"
    m = client.get("/v1/predictions/models").json()
    vol = next(x for x in m["models"] if x["model_name"] == "volatility")
    assert "qlike" in vol["metrics"] and "per_asset_qlike" not in vol["params"]
    mk = client.get("/v1/predictions/market").json()
    assert "regime" in mk and mk["current_conditions"]["details"]["label"] in ("calm", "normal", "stressed")
    assert client.get("/v1/predictions/instruments/NOPE").status_code == 404


def test_short_histories_use_the_model_probability_not_their_own_frequency():
    rising = pd.Series(100 * np.exp(np.linspace(0, 0.6, 500) + RNG.normal(0, 0.02, 500)),
                       index=pd.date_range("2024-01-01", periods=500, freq="B"))  # short, mostly rising, volatile
    rows = volatility.predict({"NEW": rising}, {"NEW": "equity"}, "historical_252", "empirical")
    p = next(r for r in rows if r["target"] == "p_loss_10pct_21d")
    assert p["details"]["method"] == "model" and p["value"] > 0.05
