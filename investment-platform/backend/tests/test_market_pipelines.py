"""Market-data pipelines: source parsers (saved payload shapes), snapshot logic,
upserts, and the jobs end-to-end against fake sources. No network."""
import datetime as dt

import pytest
from sqlalchemy import delete, select

from app import repo
from app.db import SessionLocal
from app.models import (
    CryptoMarketSnapshot, Indicator, IndicatorObservation, IndicatorSnapshot, Instrument, PipelineRun, PriceBar,
    ReportedFact,
)
from pipelines import catalog, jobs, market_writer as w, snapshots
from pipelines.sources import binance, coingecko, crypto_sentiment, ecb, esef, eurostat, parse_period, yahoo

D = dt.date


# ---------------------------------------------------------------- parsers
def test_parse_period_formats():
    assert parse_period("2026-Q3") == D(2026, 7, 1)
    assert parse_period("2026-05") == D(2026, 5, 1)
    assert parse_period("2026-05-12") == D(2026, 5, 12)
    assert parse_period("2024") == D(2024, 1, 1)


def _jsonstat(values, periods, extra_dims=None):
    dims = {"geo": 1, **(extra_dims or {}), "time": len(periods)}
    return {
        "id": list(dims), "size": list(dims.values()),
        "dimension": {"time": {"category": {"index": {p: i for i, p in enumerate(periods)}}}},
        "value": {str(i): v for i, v in enumerate(values) if v is not None},
    }


def test_eurostat_parses_and_skips_missing():
    js = _jsonstat([2.1, None, 3.0], ["2026-06", "2026-07", "2026-08"])
    assert eurostat.parse_jsonstat(js) == [(D(2026, 6, 1), 2.1), (D(2026, 8, 1), 3.0)]


def test_eurostat_rejects_unpinned_filters():
    with pytest.raises(ValueError, match="not pinned"):
        eurostat.parse_jsonstat(_jsonstat([1.0], ["2026-01"], extra_dims={"unit": 2}), "x")


def test_ecb_csv():
    text = "KEY,TIME_PERIOD,OBS_VALUE\nFM.D,2026-10-02,2.0\nFM.D,2026-10-01,2.25\nFM.D,2026-10-03,\n"
    assert ecb.parse_csv(text) == [(D(2026, 10, 1), 2.25), (D(2026, 10, 2), 2.0)]


def test_yahoo_uses_exchange_local_day_and_skips_null_sessions():
    # 2026-10-01 21:30 UTC is already 2026-10-02 in Athens (UTC+3)
    ts = int(dt.datetime(2026, 10, 1, 21, 30, tzinfo=dt.timezone.utc).timestamp())
    payload = {"chart": {"result": [{
        "meta": {"currency": "EUR", "gmtoffset": 10800},
        "timestamp": [ts, ts + 86400],
        "indicators": {"quote": [{"open": [1, None], "high": [2, None], "low": [0.5, None],
                                  "close": [1.5, None], "volume": [100, None]}],
                       "adjclose": [{"adjclose": [1.4, None]}]},
        "events": {"dividends": {}},
    }]}}
    meta, bars = yahoo.parse_chart(payload)
    assert list(bars) == [D(2026, 10, 2)]
    assert bars[D(2026, 10, 2)] == {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0, "adj_close": 1.4}
    assert meta["has_corporate_events"] is True


def test_yahoo_drops_zero_volume_phantom_bars_only():
    def b(close, vol):
        return {"open": close, "high": close, "low": close, "close": close, "volume": vol, "adj_close": close}
    bars = {D(2015, 11, 27): b(12.15, 186930), D(2015, 11, 30): b(182.25, 0), D(2015, 12, 1): b(182.25, 0),
            D(2015, 12, 3): b(12.15, 0), D(2015, 12, 4): b(6.44, 144188),   # -47% on volume: a real move
            D(2015, 12, 7): b(6.66, 0)}                                      # quiet holiday-like day: kept
    kept, dropped = yahoo.drop_phantom_bars(bars)
    assert dropped == [D(2015, 11, 30), D(2015, 12, 1)]
    assert list(kept) == [D(2015, 11, 27), D(2015, 12, 3), D(2015, 12, 4), D(2015, 12, 7)]


def test_yahoo_error_payload_raises():
    with pytest.raises(RuntimeError, match="no data"):
        yahoo.parse_chart({"chart": {"result": None, "error": {"code": "Not Found"}}})


def test_binance_klines():
    ms = int(dt.datetime(2026, 1, 3, tzinfo=dt.timezone.utc).timestamp() * 1000)
    bars = binance.parse_klines([[ms, "1", "2", "0.5", "1.5", "10", 0, "0", 0]])
    assert bars == {D(2026, 1, 3): {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0, "adj_close": 1.5}}


def test_coingecko_and_sentiment_parsers():
    m = coingecko.parse_markets([{"id": "bitcoin", "current_price": 70000, "market_cap": 1.4e12, "total_volume": 3e10,
                                  "circulating_supply": 2e7, "market_cap_rank": 1}])
    assert m["bitcoin"]["market_cap_rank"] == 1 and m["bitcoin"]["volume_24h"] == 3e10
    ts = int(dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc).timestamp())
    assert crypto_sentiment.parse_fear_greed({"data": [{"value": "70", "timestamp": str(ts)}]}) == [(D(2026, 10, 5), 70.0)]
    assert crypto_sentiment.parse_defi_tvl([{"date": ts, "tvl": 1.5e11}]) == [(D(2026, 10, 5), 1.5e11)]


def test_esef_keeps_consolidated_numeric_ifrs_facts():
    doc = {"facts": {
        "f1": {"value": "402709185", "dimensions": {"concept": "ifrs-full:Revenue", "entity": "lei:X",
               "period": "2022-01-01T00:00:00/2023-01-01T00:00:00", "unit": "iso4217:EUR"}},
        "f2": {"value": "1076468668", "dimensions": {"concept": "ifrs-full:Assets", "entity": "lei:X",
               "period": "2023-01-01T00:00:00", "unit": "iso4217:EUR"}},
        "f3": {"value": "5", "dimensions": {"concept": "ifrs-full:Revenue", "entity": "lei:X",  # company-only figure
               "period": "2022-01-01T00:00:00/2023-01-01T00:00:00", "unit": "iso4217:EUR",
               "ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis": "ifrs-full:SeparateMember"}},
        "f4": {"value": "<p>policy</p>", "dimensions": {"concept": "ifrs-full:DisclosureOfX", "entity": "lei:X",
               "period": "2022-01-01T00:00:00/2023-01-01T00:00:00"}},
        "f5": {"value": "0.264", "dimensions": {"concept": "ifrs-full:BasicEarningsLossPerShare", "entity": "lei:X",
               "period": "2022-01-01T00:00:00/2023-01-01T00:00:00", "unit": "iso4217:EUR/xbrli:shares"}},
        "f6": {"value": "9", "dimensions": {"concept": "acme:CustomKpi", "entity": "lei:X", "period": "2023-01-01T00:00:00"}},
    }}
    facts = {f["concept"]: f for f in esef.parse_facts(doc)}
    assert set(facts) == {"Revenue", "Assets", "BasicEarningsLossPerShare"}
    assert facts["Revenue"]["period_start"] == D(2022, 1, 1) and facts["Revenue"]["period_end"] == D(2022, 12, 31)
    assert facts["Revenue"]["value"] == 402709185.0
    assert facts["Assets"]["period_start"] is None and facts["Assets"]["period_end"] == D(2022, 12, 31)  # FY2022 balance sheet
    assert facts["BasicEarningsLossPerShare"]["unit"] == "EUR/shares"


def test_esef_filing_index():
    payload = {"data": [{"attributes": {"fxo_id": "LEI1-2024-12-31-ESEF-GR-0", "json_url": "/a.json", "processed": "p"},
                         "relationships": {"entity": {"data": {"id": "7", "type": "entity"}}}}],
               "included": [{"type": "entity", "id": "7", "attributes": {"identifier": "LEI1", "name": "Co"}}]}
    assert esef.parse_filing_index(payload) == [
        {"filing_id": "LEI1-2024-12-31-ESEF-GR-0", "lei": "LEI1", "entity_name": "Co", "json_url": "/a.json", "processed": "p"}]


# ---------------------------------------------------------------- snapshots
def test_period_end():
    assert snapshots.period_end(D(2026, 1, 1), "Q") == D(2026, 3, 31)
    assert snapshots.period_end(D(2026, 10, 1), "Q") == D(2026, 12, 31)
    assert snapshots.period_end(D(2026, 12, 1), "M") == D(2026, 12, 31)
    assert snapshots.period_end(D(2026, 2, 1), "M") == D(2026, 2, 28)
    assert snapshots.period_end(D(2026, 5, 7), "D") == D(2026, 5, 7)


def test_direction_dead_bands():
    assert snapshots.direction(3.0, 2.9, dead_band=0.2) == "stable"
    assert snapshots.direction(3.0, 2.7, dead_band=0.2) == "rising"
    assert snapshots.direction(2.0, 2.5, dead_band=0.2) == "falling"
    assert snapshots.direction(104, 100, dead_band_rel=0.05) == "stable"
    assert snapshots.direction(110, 100, dead_band_rel=0.05) == "rising"
    assert snapshots.direction(1.0, None) == "stable"


def test_compute_snapshot_monthly_with_comparator_and_staleness():
    cfg = catalog.INDICATORS_BY_ID["hicp_yoy"]
    series = [(D(2025, m, 1), 2.0 + m / 10) for m in range(1, 13)] + [(D(2026, m, 1), 3.0) for m in range(1, 9)]
    eu = [(D(2026, 8, 1), 2.1)]
    snap = snapshots.compute_snapshot(cfg, series, D(2026, 10, 5), eu)
    assert snap["obs_date"] == D(2026, 8, 1) and snap["value"] == 3.0
    assert snap["value_90d_prior"] == 3.0 and snap["direction_90d"] == "stable"
    assert snap["value_1y"] == pytest.approx(2.8)  # Aug 2025
    assert snap["value_eu"] == 2.1
    assert snap["staleness_d"] == (D(2026, 10, 5) - D(2026, 8, 31)).days  # measured from period END
    assert snap["payload_eligible"] is True
    late = snapshots.compute_snapshot(cfg, series, D(2026, 11, 15), eu)
    assert late["payload_eligible"] is False  # 76 days > 60 cap


def test_compute_snapshot_ignores_future_observations():
    cfg = catalog.INDICATORS_BY_ID["ecb_dfr"]
    snap = snapshots.compute_snapshot(cfg, [(D(2026, 1, 1), 2.0), (D(2026, 9, 1), 2.25)], D(2026, 6, 1))
    assert snap["value"] == 2.0 and snap["value_90d_prior"] is None


def test_derive_spread_on_common_dates():
    gr = [(D(2026, 7, 1), 3.4), (D(2026, 8, 1), 3.5)]
    de = [(D(2026, 8, 1), 2.6)]
    assert snapshots.derive_spread(gr, de, 100.0) == [(D(2026, 8, 1), pytest.approx(90.0))]


# ---------------------------------------------------------------- writers + jobs (temp DB from conftest)
@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.rollback()
    test_ids = [i.id for i in s.execute(select(Instrument).where(Instrument.data_source != "simulated")).scalars()]
    for model in (PriceBar, ReportedFact, CryptoMarketSnapshot):
        s.execute(delete(model).where(model.instrument_id.in_(test_ids)))
    s.execute(delete(Instrument).where(Instrument.id.in_(test_ids)))
    for model in (IndicatorSnapshot, IndicatorObservation, Indicator):
        s.execute(delete(model))
    s.execute(delete(PipelineRun).where(PipelineRun.pipeline.like("market.%")))
    s.commit()
    s.close()


def _greek(db, ticker="TEST.AT", lei="LEI1"):
    return w.ensure_instrument(db, ticker=ticker, name="Test Co", sector="Banks", asset_type="equity",
                               exchange="Euronext Athens", currency="EUR", data_source="yahoo", country="GR", lei=lei)


def test_upsert_bars_is_idempotent_and_applies_changes(db):
    inst = _greek(db)
    bar = {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0, "adj_close": 1.5}
    assert w.upsert_bars(db, inst, {D(2026, 10, 1): bar, D(2026, 10, 2): bar}) == 2
    db.commit()
    assert w.upsert_bars(db, inst, {D(2026, 10, 2): bar}) == 0
    assert w.upsert_bars(db, inst, {D(2026, 10, 2): {**bar, "adj_close": 1.4}}) == 1
    db.commit()
    assert w.last_bar_date(db, inst) == D(2026, 10, 2)
    # prune: a re-fetch that no longer contains 10-01 (filtered phantom bar) removes it
    assert w.upsert_bars(db, inst, {D(2026, 10, 2): {**bar, "adj_close": 1.4}}, prune=True) == 0
    assert w.upsert_bars(db, inst, {D(2026, 9, 30): bar, D(2026, 10, 2): {**bar, "adj_close": 1.4}}, prune=True) == 2
    db.commit()
    dates = sorted(b.date for b in db.execute(select(PriceBar).where(PriceBar.instrument_id == inst.id)).scalars())
    assert dates == [D(2026, 9, 30), D(2026, 10, 2)]


def test_market_instruments_stay_out_of_demo_analytics(db):
    before = {i["ticker"] for i in repo.load_instruments(db)}
    _greek(db)
    db.commit()
    assert {i["ticker"] for i in repo.load_instruments(db)} == before


def test_observations_record_revisions(db):
    w.ensure_indicator(db, catalog.INDICATORS_BY_ID["unemp"])
    assert w.upsert_observations(db, "unemp", [(D(2026, 7, 1), 8.1), (D(2026, 8, 1), 8.0)]) == 2
    db.commit()
    assert w.upsert_observations(db, "unemp", [(D(2026, 7, 1), 8.1), (D(2026, 8, 1), 7.9)]) == 1
    assert w.load_series(db, "unemp")[-1] == (D(2026, 8, 1), 7.9)


def test_later_filing_restates_comparatives(db):
    inst = _greek(db)
    old = [{"concept": "Revenue", "period_start": D(2023, 1, 1), "period_end": D(2023, 12, 31), "value": 100.0, "unit": "EUR"}]
    new = [{**old[0], "value": 105.0},
           {"concept": "Revenue", "period_start": D(2024, 1, 1), "period_end": D(2024, 12, 31), "value": 120.0, "unit": "EUR"}]
    w.upsert_reported_facts(db, inst, old, "F-2023")
    w.upsert_reported_facts(db, inst, new, "F-2024")
    db.commit()
    rows = {r.period_end.year: (r.value, r.filing_id) for r in db.execute(select(ReportedFact).where(ReportedFact.instrument_id == inst.id)).scalars()}
    assert rows == {2023: (105.0, "F-2024"), 2024: (120.0, "F-2024")}
    assert "F-2024" in w.ingested_filing_ids(db, inst)


def test_indicator_job_derives_spread_and_reports_partial(db, monkeypatch):
    def fake_ecb(key, start=None):
        if "IRS/M.GR" in key:
            return [(D(2026, 7, 1), 3.4), (D(2026, 8, 1), 3.5)]
        if "IRS/M.DE" in key:
            return [(D(2026, 7, 1), 2.7), (D(2026, 8, 1), 2.6)]
        raise RuntimeError("ECB down")

    monkeypatch.setattr(jobs.ecb, "fetch", fake_ecb)
    monkeypatch.setattr(jobs.time, "sleep", lambda s: None)
    res = jobs.load_indicators(db, only=["ggb_10y", "bund_10y", "spread_10y", "ecb_dfr"])
    assert res.status == "partial" and any("ecb_dfr" in e for e in res.errors)
    assert w.load_series(db, "spread_10y") == [(D(2026, 7, 1), pytest.approx(70.0)), (D(2026, 8, 1), pytest.approx(90.0))]

    snap = jobs.compute_snapshots(db, only=["spread_10y"], as_of=D(2026, 10, 5))
    assert snap.status == "ok"
    row = db.execute(select(IndicatorSnapshot).where(IndicatorSnapshot.indicator_id == "spread_10y")).scalar_one()
    assert row.value == pytest.approx(90.0) and row.direction_90d == "rising"  # +20bps vs Jul, dead band 10
    assert row.payload_eligible is True


def test_equities_job_backfills_then_rebases_on_dividend(db, monkeypatch):
    calls = []
    bar = {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0, "adj_close": 1.0}

    def fake_fetch(symbol, start):
        calls.append(start)
        return {"currency": "EUR", "has_corporate_events": len(calls) == 2}, {D(2026, 10, 1): bar, D(2026, 10, 2): bar}

    monkeypatch.setattr(jobs.yahoo, "fetch_daily", fake_fetch)
    monkeypatch.setattr(jobs.time, "sleep", lambda s: None)
    assert jobs.load_equities(db, only=["ETE.AT"]).rows == 2
    assert calls == [jobs.EQUITY_HISTORY_START]          # empty table -> full history
    res = jobs.load_equities(db, only=["ETE.AT"])
    assert calls[1] == D(2026, 10, 2) - dt.timedelta(days=jobs.EQUITY_LOOKBACK_D)
    assert calls[2] == jobs.EQUITY_HISTORY_START and "re-based" in res.detail()
    inst = db.execute(select(Instrument).where(Instrument.ticker == "ETE.AT")).scalar_one()
    assert (inst.data_source, inst.country, inst.lei) == ("yahoo", "GR", "5UMCZOEYKCVFAW8ZLO05")


def test_run_job_logs_pipeline_run(db, monkeypatch):
    monkeypatch.setattr(jobs.crypto_sentiment, "fetch_fear_greed", lambda: [(D(2026, 10, 5), 70.0)])
    monkeypatch.setattr(jobs.time, "sleep", lambda s: None)
    jobs.run_job("indicators", SessionLocal, only=["crypto_fear_greed"])
    run = db.execute(select(PipelineRun).where(PipelineRun.pipeline == "market.indicators")).scalars().all()[-1]
    assert run.status == "ok" and run.rows_affected == 1
