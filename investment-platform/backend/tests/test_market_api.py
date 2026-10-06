"""/v1 real-market-data API, data-status and market_* metrics, against a small
seeded universe (Athens stock with fundamentals, crypto, US index, indicators)."""
import datetime as dt
import math

import pytest
from sqlalchemy import delete, select

from app import market_repo
from app.db import SessionLocal
from app.models import (
    CryptoMarketSnapshot, Indicator, IndicatorObservation, IndicatorSnapshot, Instrument, PipelineRun, PriceBar,
    ReportedFact,
)
from app.services import market as calc
from pipelines import catalog, market_writer as w, snapshots

D = dt.date
TODAY = dt.date.today()


# ---------------------------------------------------------------- calculations
def _daily(n, start_value=100.0, growth=0.001, weekdays_only=False, end=TODAY):
    out, d, v = [], end - dt.timedelta(days=n), start_value
    while d <= end:
        if not weekdays_only or d.weekday() < 5:
            out.append((d, v))
            v *= 1 + growth
        d += dt.timedelta(days=1)
    return out


def test_period_returns_windows_and_coverage():
    ser = [(D(2025, 12, 31), 100.0), (D(2026, 9, 5), 110.0), (D(2026, 10, 5), 121.0)]
    r = calc.period_returns(ser, as_of=D(2026, 10, 5))
    assert r["1m"] == pytest.approx(0.1)          # vs 2026-09-05
    assert r["ytd"] == pytest.approx(0.21)        # vs 2025-12-31 close
    assert r["1y"] is None                        # series starts after 2025-10-05


def test_volatility_and_drawdown():
    flat = _daily(400, growth=0.0)
    assert calc.annualized_volatility(flat) == pytest.approx(0.0)
    zigzag = [(d, 100.0 * (1.01 if i % 2 else 1.0)) for i, (d, _) in enumerate(_daily(400))]
    vol = calc.annualized_volatility(zigzag)
    assert vol == pytest.approx(math.log(1.01) * math.sqrt(365.25), rel=0.05)
    ser = [(D(2026, 1, 1), 100.0), (D(2026, 2, 1), 120.0), (D(2026, 3, 1), 90.0), (D(2026, 4, 1), 130.0)]
    assert calc.max_drawdown(ser, days=None) == pytest.approx(-0.25)


def test_resample_weekly_and_monthly():
    bars = [{"date": d, "open": v, "high": v + 1, "low": v - 1, "close": v, "volume": 10.0, "adj_close": v}
            for d, v in [(D(2026, 9, 28), 1.0), (D(2026, 9, 30), 3.0), (D(2026, 10, 1), 2.0), (D(2026, 10, 5), 5.0)]]
    weekly = calc.resample_bars(bars, "weekly")
    assert [(b["date"], b["open"], b["high"], b["low"], b["close"], b["volume"]) for b in weekly] == [
        (D(2026, 10, 1), 1.0, 4.0, 0.0, 2.0, 30.0), (D(2026, 10, 5), 5.0, 6.0, 4.0, 5.0, 10.0)]
    monthly = calc.resample_bars(bars, "monthly")
    assert [b["date"] for b in monthly] == [D(2026, 9, 30), D(2026, 10, 5)]


def test_rebase_compare_aligns_calendars_and_carries_forward():
    crypto = [(D(2026, 10, 2), 100.0), (D(2026, 10, 3), 110.0), (D(2026, 10, 4), 120.0), (D(2026, 10, 5), 90.0)]
    stock = [(D(2026, 10, 2), 50.0), (D(2026, 10, 5), 55.0)]   # no weekend sessions
    base, rows = calc.rebase_compare({"BTC": crypto, "ETE": stock})
    assert base == D(2026, 10, 2)
    assert rows[0] == {"date": D(2026, 10, 2), "BTC": 100.0, "ETE": 100.0}
    assert rows[2] == {"date": D(2026, 10, 4), "BTC": 120.0, "ETE": 100.0}  # weekend: stock carried forward
    assert rows[-1] == {"date": D(2026, 10, 5), "BTC": 90.0, "ETE": 110.0}


def test_rebase_starts_when_all_series_exist():
    base, rows = calc.rebase_compare({"A": [(D(2026, 1, 1), 1.0), (D(2026, 1, 3), 2.0)], "B": [(D(2026, 1, 2), 5.0), (D(2026, 1, 3), 10.0)]})
    assert base == D(2026, 1, 2) and rows[0]["A"] == 100.0 and rows[-1] == {"date": D(2026, 1, 3), "A": 200.0, "B": 200.0}


def _fact(concept, year, value, instant=False):
    return {"concept": concept, "period_start": None if instant else D(year, 1, 1), "period_end": D(year, 12, 31),
            "value": value, "unit": "EUR"}


def test_normalize_fundamentals_fallbacks_ratios_and_bank_metrics():
    facts = [
        _fact("Revenue", 2024, 1000.0), _fact("Revenue", 2023, 800.0),
        _fact("ProfitLoss", 2024, 120.0), _fact("ProfitLossAttributableToOwnersOfParent", 2024, 100.0),
        _fact("ProfitLossAttributableToOwnersOfParent", 2023, 80.0),
        _fact("Equity", 2024, 600.0, True), _fact("EquityAttributableToOwnersOfParent", 2024, 500.0, True),
        _fact("EquityAttributableToOwnersOfParent", 2023, 300.0, True),
        _fact("Assets", 2024, 2000.0, True), _fact("CashFlowsFromUsedInOperatingActivities", 2024, 150.0),
        _fact("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", 2024, -50.0),
        _fact("DividendsPaidClassifiedAsFinancingActivities", 2024, -40.0),
        _fact("BasicEarningsLossPerShare", 2024, 2.0), _fact("WeightedAverageShares", 2024, 50.0),
        _fact("LoansAndAdvancesToCustomers", 2024, 900.0, True), _fact("DepositsFromCustomers", 2024, 1000.0, True),
        {"concept": "Revenue", "period_start": D(2024, 7, 1), "period_end": D(2024, 12, 31), "value": 9.0, "unit": "EUR"},  # half-year: ignored
    ]
    years = calc.normalize_fundamentals(facts)
    assert [y["fiscal_year_end"] for y in years] == [D(2024, 12, 31), D(2023, 12, 31)]
    m, r = years[0]["metrics"], years[0]["ratios"]
    assert m["net_income"] == 100.0 and years[0]["sources"]["net_income"] == "ProfitLossAttributableToOwnersOfParent"
    assert m["equity"] == 500.0 and m["capex"] == 50.0 and m["dividends_paid"] == 40.0
    assert r["roe"] == pytest.approx(100 / 400)       # average equity
    assert r["net_margin"] == pytest.approx(0.1) and r["revenue_growth"] == pytest.approx(0.25)
    assert r["free_cash_flow"] == 100.0 and r["payout_ratio"] == pytest.approx(0.4)
    assert r["loan_to_deposit"] == pytest.approx(0.9)
    mr_ = calc.market_ratios(years[0], price=30.0)
    assert mr_["pe"] == 15.0 and mr_["market_cap_approx"] == 1500.0 and mr_["pb"] == 3.0
    assert mr_["dividend_yield"] == pytest.approx(40 / 1500)


# ---------------------------------------------------------------- API (seeded DB)
@pytest.fixture
def market(client):
    db = SessionLocal()
    ete = w.ensure_instrument(db, ticker="ETE.AT", name="National Bank of Greece", sector="Banks", asset_type="equity",
                              exchange="Euronext Athens", currency="EUR", data_source="yahoo", country="GR",
                              lei="5UMCZOEYKCVFAW8ZLO05", vendor_symbol="ETE.AT")
    btc = w.ensure_instrument(db, ticker="BTC-EUR", name="Bitcoin", sector="Crypto", asset_type="crypto",
                              exchange="Binance", currency="EUR", data_source="binance", vendor_symbol="BTCEUR")
    spx = w.ensure_instrument(db, ticker="^GSPC", name="S&P 500", sector="Index", asset_type="index",
                              exchange="", currency="USD", data_source="yahoo", country="US", vendor_symbol="^GSPC")

    def bars(series):
        return {d: {"open": v, "high": v, "low": v, "close": v, "volume": 1.0, "adj_close": v} for d, v in series}

    w.upsert_bars(db, ete, bars(_daily(800, 10.0, 0.001, weekdays_only=True)))
    w.upsert_bars(db, btc, bars(_daily(800, 50000.0, 0.002)))
    w.upsert_bars(db, spx, bars(_daily(800, 5000.0, 0.0005, weekdays_only=True, end=TODAY - dt.timedelta(days=10))))  # stale
    w.upsert_reported_facts(db, ete, [_fact("ProfitLossAttributableToOwnersOfParent", 2024, 1158e6),
                                      _fact("EquityAttributableToOwnersOfParent", 2024, 9e9, True),
                                      _fact("BasicEarningsLossPerShare", 2024, 1.27)], "F-2024")
    w.upsert_crypto_snapshot(db, btc, TODAY, "EUR", {"price": 76000.0, "market_cap": 1.5e12, "volume_24h": 3e10,
                                                     "circulating_supply": 2e7, "market_cap_rank": 1})
    for cfg_id in ("hicp_yoy", "hicp_yoy_eu", "crypto_fear_greed"):
        w.ensure_indicator(db, catalog.INDICATORS_BY_ID[cfg_id])
    w.upsert_observations(db, "hicp_yoy", [(D(2025, 9, 1), 1.8), (D(2026, 6, 1), 3.0), (D(2026, 9, 1), 5.1)])
    w.upsert_observations(db, "hicp_yoy_eu", [(D(2026, 9, 1), 3.2)])
    w.upsert_observations(db, "crypto_fear_greed", [(TODAY - dt.timedelta(days=1), 70.0)])
    for cfg_id, comp in (("hicp_yoy", "hicp_yoy_eu"), ("crypto_fear_greed", None)):
        cfg = catalog.INDICATORS_BY_ID[cfg_id]
        snap = snapshots.compute_snapshot(cfg, w.load_series(db, cfg_id), TODAY, w.load_series(db, comp) if comp else None)
        w.upsert_snapshot(db, cfg_id, snap)
    now = dt.datetime.now()
    for job, status, hours_ago in (("equities", "ok", 2), ("crypto", "error", 1), ("crypto", "ok", 30), ("indicators", "partial", 3)):
        t = now - dt.timedelta(hours=hours_ago)
        db.add(PipelineRun(pipeline=f"market.{job}", status=status, started_at=t, finished_at=t, rows_affected=5, detail="seed"))
    db.commit()
    market_repo.clear_cache()
    yield {"ete": ete.id}
    ids = [i.id for i in db.execute(select(Instrument).where(Instrument.data_source != "simulated")).scalars()]
    for model in (PriceBar, ReportedFact, CryptoMarketSnapshot):
        db.execute(delete(model).where(model.instrument_id.in_(ids)))
    db.execute(delete(Instrument).where(Instrument.id.in_(ids)))
    for model in (IndicatorSnapshot, IndicatorObservation, Indicator):
        db.execute(delete(model))
    db.execute(delete(PipelineRun).where(PipelineRun.pipeline.like("market.%")))
    db.commit()
    db.close()


def test_list_instruments_and_filters(client, market):
    rows = client.get("/v1/instruments").json()
    assert {r["ticker"] for r in rows} == {"ETE.AT", "BTC-EUR", "^GSPC"}  # demo instruments excluded
    ete = next(r for r in rows if r["ticker"] == "ETE.AT")
    assert ete["has_fundamentals"] is True and ete["last_date"] <= TODAY.isoformat()
    assert ete["change_1d"] == pytest.approx(0.001) and ete["return_1y"] > 0
    assert [r["ticker"] for r in client.get("/v1/instruments", params={"asset_type": "crypto"}).json()] == ["BTC-EUR"]
    assert [r["ticker"] for r in client.get("/v1/instruments", params={"country": "gr", "q": "national"}).json()] == ["ETE.AT"]
    assert client.get("/v1/instruments", params={"asset_type": "bond"}).status_code == 422


def test_instrument_detail_prices_and_performance(client, market):
    d = client.get("/v1/instruments/ete.at").json()   # case-insensitive
    assert d["lei"] == "5UMCZOEYKCVFAW8ZLO05" and d["returns"]["y1"] > 0 and d["volatility_1y"] == pytest.approx(0.0, abs=1e-6)
    btc = client.get("/v1/instruments/BTC-EUR").json()
    assert btc["crypto_market"]["market_cap_rank"] == 1
    p = client.get("/v1/instruments/BTC-EUR/prices", params={"interval": "monthly", "start": "2026-01-01", "end": "2026-03-31"}).json()
    assert p["currency"] == "EUR" and [b["date"][:7] for b in p["bars"]] == ["2026-01", "2026-02", "2026-03"]
    assert client.get("/v1/instruments/BTC-EUR/prices", params={"start": "2026-02-01", "end": "2026-01-01"}).status_code == 422
    perf = client.get("/v1/instruments/^GSPC/performance").json()
    spx_last = TODAY - dt.timedelta(days=10)
    while spx_last.weekday() >= 5:  # seeded S&P series has weekday bars only
        spx_last -= dt.timedelta(days=1)
    assert perf["as_of"] == spx_last.isoformat() and perf["max_drawdown_all"] == 0.0
    assert client.get("/v1/instruments/NOPE.AT").status_code == 404


def test_compare_rebases_mixed_assets(client, market):
    r = client.get("/v1/compare", params={"tickers": "BTC-EUR,ETE.AT,^GSPC", "start": (TODAY - dt.timedelta(days=60)).isoformat()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tickers"] == ["BTC-EUR", "ETE.AT", "^GSPC"]
    assert body["points"][0]["BTC-EUR"] == 100.0 and body["points"][0]["^GSPC"] == 100.0
    assert "no FX conversion" in body["note"]                       # EUR + USD
    assert body["total_return"]["BTC-EUR"] > body["total_return"]["ETE.AT"] > 0
    assert client.get("/v1/compare", params={"tickers": "BTC-EUR"}).status_code == 422
    missing = client.get("/v1/compare", params={"tickers": "BTC-EUR,FAKE"})
    assert missing.status_code == 404 and "FAKE" in missing.json()["detail"]


def test_fundamentals(client, market):
    f = client.get("/v1/instruments/ETE.AT/fundamentals").json()
    assert f["years"][0]["metrics"]["net_income"] == 1158e6 and f["years"][0]["fiscal_year_end"] == "2024-12-31"
    price = client.get("/v1/instruments/ETE.AT").json()["last_close"]
    assert f["market_ratios"]["pe"] == pytest.approx(price / 1.27)
    assert client.get("/v1/instruments/BTC-EUR/fundamentals").status_code == 422


def test_macro_endpoints(client, market):
    inds = {i["id"]: i for i in client.get("/v1/macro/indicators").json()}
    h = inds["hicp_yoy"]
    assert h["snapshot"]["value"] == 5.1 and h["snapshot"]["direction_90d"] == "rising" and h["snapshot"]["value_eu"] == 3.2
    assert h["last_observation"] == "2026-09-01"
    assert [i["id"] for i in client.get("/v1/macro/indicators", params={"category": "crypto"}).json()] == ["crypto_fear_greed"]
    ser = client.get("/v1/macro/indicators/hicp_yoy/series", params={"start": "2026-01-01"}).json()
    assert [p["value"] for p in ser["points"]] == [3.0, 5.1]
    assert client.get("/v1/macro/indicators/nope").status_code == 404
    snap = client.get("/v1/macro/snapshot").json()
    assert snap["as_of_date"] == TODAY.isoformat() and {i["id"] for i in snap["indicators"]} == {"hicp_yoy", "crypto_fear_greed"}
    assert client.get("/v1/macro/snapshot", params={"as_of": "2000-01-01"}).json() == {"as_of_date": None, "indicators": []}


def test_crypto_market_overview(client, market):
    c = client.get("/v1/crypto/market").json()
    assert [x["ticker"] for x in c["coins"]] == ["BTC-EUR"] and c["markets"]["BTC-EUR"]["price"] == 76000.0
    assert c["fear_greed"]["value"] == 70.0


def test_data_status_flags_stale_series_and_jobs(staff_client, market):
    client = staff_client  # data-status needs ops:read
    s = client.get("/v1/data-status").json()
    assert s["overall"] == "critical"                               # ^GSPC 10 days old + daily jobs never ran
    assert s["datasets"]["equities"]["stale_items"] == ["^GSPC"]
    assert s["datasets"]["crypto"]["stale"] == 0
    jobs = {p["job"]: p for p in s["pipelines"]}
    assert jobs["crypto"]["last_status"] == "error" and jobs["crypto"]["overdue"] is True   # last success 30 h ago > 7 h
    assert jobs["equities"]["overdue"] is False and jobs["indicators"]["last_status"] == "partial"
    assert jobs["snapshots"]["last_run_at"] is None and jobs["snapshots"]["overdue"] is True


def test_metrics_expose_market_gauges(client, market):
    text = client.get("/metrics").text
    assert "market_monitoring_scrape_ok 1.0" in text
    assert 'market_data_stale{dataset="equities",item="^GSPC"} 1.0' in text
    assert 'market_pipeline_last_status{job="crypto",status="error"} 1.0' in text
    assert 'market_pipeline_overdue{job="equities"} 0.0' in text
    assert "market_data_overall 2.0" in text
