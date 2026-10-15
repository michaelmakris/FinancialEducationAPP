"""
Real market-data jobs. Each job takes a DB session and returns a JobResult;
run_job() wraps it with a pipeline_runs row so the Grafana dashboard sees it.

Jobs are incremental by default (re-fetch a short trailing window to pick up
revisions) and backfill from scratch with full=True or when the table is empty.
One failing series never stops the rest of its job: it is recorded in the
detail and the run is marked "partial".

    python -m pipelines.run indicators            # one job
    python -m pipelines.run all --full            # full backfill of everything
"""
from __future__ import annotations

import datetime
import logging
import re
import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Instrument, PipelineRun
from pipelines import catalog, market_writer as w, snapshots
from pipelines.sources import binance, coingecko, crypto_sentiment, ecb, esef, eurostat, fred, yahoo

log = logging.getLogger("pipelines")

EQUITY_HISTORY_START = datetime.date(2015, 1, 1)
CRYPTO_HISTORY_START = datetime.date(2020, 1, 1)  # Binance EUR pairs begin in 2020
SERIES_HISTORY_START = "2010-01-01"
EQUITY_LOOKBACK_D = 10
CRYPTO_LOOKBACK_D = 3
SERIES_LOOKBACK_D = 400  # ECB/FRED: re-read ~a year so revisions land
REQUEST_PAUSE_S = 0.4    # be polite to free endpoints


@dataclass
class JobResult:
    rows: int = 0
    items: int = 0
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def fail(self, what: str, e: Exception) -> None:
        self.errors.append(f"{what}: {type(e).__name__}: {str(e)[:160]}")
        log.warning("  %s failed: %s", what, e)

    @property
    def status(self) -> str:
        if not self.errors:
            return "ok"
        return "partial" if self.items else "error"

    def detail(self) -> str:
        parts = [f"{self.rows} rows across {self.items} series"] + self.notes
        if self.errors:
            parts.append(f"{len(self.errors)} failed: " + "; ".join(self.errors))
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Indicators: Eurostat, ECB, FRED, crypto sentiment, derived spreads
# ---------------------------------------------------------------------------
def _fetch_indicator(cfg: dict, last: datetime.date | None, full: bool) -> list[tuple[datetime.date, float]]:
    start = SERIES_HISTORY_START if full or last is None else str(last - datetime.timedelta(days=SERIES_LOOKBACK_D))
    src = cfg["source"]
    if src == "eurostat":
        return eurostat.fetch(cfg["dataset"], cfg["filters"])  # small series: always the full history
    if src == "ecb":
        return ecb.fetch(cfg["key"], start=start)
    if src == "fred":
        if not settings.fred_api_key:
            raise RuntimeError("FRED_API_KEY not set")
        return fred.fetch(cfg["key"], settings.fred_api_key, start=start)
    if src == "fear_greed":
        return crypto_sentiment.fetch_fear_greed()
    if src == "defillama":
        return crypto_sentiment.fetch_defi_tvl()
    raise ValueError(f"unknown source {src}")


def load_indicators(db: Session, full: bool = False, only: list[str] | None = None) -> JobResult:
    res = JobResult()
    cfgs = [c for c in catalog.INDICATORS if not only or c["id"] in only]
    for cfg in cfgs:
        w.ensure_indicator(db, cfg)
    db.flush()
    for cfg in (c for c in cfgs if c["source"] != "derived"):
        try:
            existing = w.load_series(db, cfg["id"])
            series = _fetch_indicator(cfg, existing[-1][0] if existing else None, full)
            if not series:
                raise RuntimeError("source returned no observations (check filters/key)")
            res.rows += w.upsert_observations(db, cfg["id"], series)
            res.items += 1
            db.commit()
        except Exception as e:
            db.rollback()
            res.fail(cfg["id"], e)
        time.sleep(REQUEST_PAUSE_S)
    for cfg in (c for c in cfgs if c["source"] == "derived"):
        try:
            a, b, scale = cfg["formula"]
            series = snapshots.derive_spread(w.load_series(db, a), w.load_series(db, b), scale)
            res.rows += w.upsert_observations(db, cfg["id"], series)
            res.items += 1
            db.commit()
        except Exception as e:
            db.rollback()
            res.fail(cfg["id"], e)
    return res


def compute_snapshots(db: Session, full: bool = False, only: list[str] | None = None,
                      as_of: datetime.date | None = None) -> JobResult:
    as_of = as_of or datetime.date.today()
    res = JobResult(notes=[f"as_of={as_of}"])
    stale = []
    for cfg in (c for c in catalog.INDICATORS if c.get("snapshot") and (not only or c["id"] in only)):
        try:
            comparator = w.load_series(db, cfg["comparator"]) if cfg.get("comparator") else None
            snap = snapshots.compute_snapshot(cfg, w.load_series(db, cfg["id"]), as_of, comparator)
            if snap is None:
                raise RuntimeError("no observations loaded yet")
            w.upsert_snapshot(db, cfg["id"], snap)
            if not snap["payload_eligible"]:
                stale.append(f"{cfg['id']}({snap['staleness_d']}d)")
            res.rows += 1
            res.items += 1
        except Exception as e:
            res.fail(cfg["id"], e)
    db.commit()
    if stale:
        res.notes.append("stale/not eligible: " + ", ".join(stale))
    return res


# ---------------------------------------------------------------------------
# Euronext Athens equities + benchmarks (Yahoo)
# ---------------------------------------------------------------------------
def _exchange(symbol: str) -> tuple[str, str]:
    for suffix, (exchange, country) in catalog.EXCHANGES.items():
        if symbol.endswith(suffix):
            return exchange, country
    return "", ""


def _equity_universe() -> list[dict]:
    """Every Yahoo-priced instrument: ticker (ours), symbol (Yahoo's), market, exchange, country."""
    out = []
    for t, n, s, lei in catalog.GREEK_EQUITIES:
        out.append(dict(ticker=t, symbol=t, name=n, sector=s, asset_type="equity", market="athens", lei=lei))
    for t, n, s in catalog.ATHENS_MORE:
        out.append(dict(ticker=t, symbol=t, name=n, sector=s, asset_type="equity", market="athens", lei=None))
    for t, n, s in catalog.EUROPE_EQUITIES:
        out.append(dict(ticker=t, symbol=t, name=n, sector=s, asset_type="equity", market="europe", lei=None))
    for sym, n, s, exch in catalog.US_EQUITIES:
        out.append(dict(ticker=f"{sym}.US", symbol=sym, name=n, sector=s, asset_type="equity", market="us",
                        lei=None, exchange=exch, country="US", currency="USD"))
    for t, n, s in catalog.ETFS:
        out.append(dict(ticker=t, symbol=t, name=n, sector=s, asset_type="etf", market="etf", lei=None, country=""))
    for t, n, s, a, c, cur in catalog.BENCHMARKS:
        out.append(dict(ticker=t, symbol=t, name=n, sector=s, asset_type=a, market="index", lei=None,
                        exchange="", country=c, currency=cur))
    for spec in out:
        exchange, country = _exchange(spec["symbol"])
        spec.setdefault("exchange", exchange)
        spec.setdefault("country", country)
        spec.setdefault("currency", "EUR")
    return out


def load_equities(db: Session, full: bool = False, only: list[str] | None = None) -> JobResult:
    res = JobResult()
    for spec in _equity_universe():
        if only and spec["ticker"] not in only:
            continue
        try:
            inst = w.ensure_instrument(
                db, ticker=spec["ticker"], name=spec["name"], sector=spec["sector"], asset_type=spec["asset_type"],
                exchange=spec["exchange"], currency=spec["currency"], data_source="yahoo", country=spec["country"],
                lei=spec["lei"], vendor_symbol=spec["symbol"], market=spec["market"],
            )
            last = None if full else w.last_bar_date(db, inst)
            start = EQUITY_HISTORY_START if last is None else last - datetime.timedelta(days=EQUITY_LOOKBACK_D)
            meta, bars = yahoo.fetch_daily(spec["symbol"], start)
            if last is not None and meta.get("has_corporate_events"):
                # dividend/split in the window: adjusted closes before it changed too
                meta, bars = yahoo.fetch_daily(spec["symbol"], EQUITY_HISTORY_START)
                res.notes.append(f"{spec['ticker']} re-based (dividend/split)")
            bars, dropped = yahoo.drop_phantom_bars(bars)
            if dropped:
                res.notes.append(f"{spec['ticker']}: dropped {len(dropped)} zero-volume phantom bar(s) {dropped[0]}..{dropped[-1]}")
            if not bars:
                raise RuntimeError("no bars returned")
            if meta.get("currency") and meta["currency"] != inst.currency:
                inst.currency = meta["currency"]
            res.rows += w.upsert_bars(db, inst, bars, prune=True)
            res.items += 1
            db.commit()
        except Exception as e:
            db.rollback()
            res.fail(spec["ticker"], e)
        time.sleep(REQUEST_PAUSE_S)
    return res


# ---------------------------------------------------------------------------
# Crypto: Binance OHLCV + CoinGecko market snapshot
# ---------------------------------------------------------------------------
def load_crypto(db: Session, full: bool = False, only: list[str] | None = None) -> JobResult:
    res = JobResult()
    insts = {}
    for ticker, name, pair, cg_id in catalog.CRYPTO_ASSETS:
        if only and ticker not in only:
            continue
        try:
            inst = w.ensure_instrument(
                db, ticker=ticker, name=name, sector="Crypto", asset_type="crypto", exchange="Binance",
                currency="EUR", data_source="binance", vendor_symbol=pair, market="crypto",
            )
            insts[cg_id] = inst
            last = None if full else w.last_bar_date(db, inst)
            start = CRYPTO_HISTORY_START if last is None else last - datetime.timedelta(days=CRYPTO_LOOKBACK_D)
            res.rows += w.upsert_bars(db, inst, binance.fetch_daily(pair, start))
            res.items += 1
            db.commit()
        except Exception as e:
            db.rollback()
            res.fail(ticker, e)
        time.sleep(REQUEST_PAUSE_S)
    if insts:
        try:
            markets = coingecko.fetch_markets(list(insts), "eur", settings.coingecko_api_key)
            today = datetime.date.today()
            for cg_id, vals in markets.items():
                if cg_id in insts:
                    w.upsert_crypto_snapshot(db, insts[cg_id], today, "EUR", vals)
            db.commit()
            res.notes.append(f"{len(markets)} CoinGecko market snapshots")
        except Exception as e:
            db.rollback()
            res.fail("coingecko markets", e)
    return res


# ---------------------------------------------------------------------------
# ESEF fundamentals for the Greek universe
# ---------------------------------------------------------------------------
def _filing_period(f: dict) -> str:
    m = re.search(r"(\d{4}-\d{2}-\d{2})-[a-z]{2}\.json$", f["json_url"]) or re.search(r"-(\d{4}-\d{2}-\d{2})-ESEF", f["filing_id"])
    return m.group(1) if m else "0000-00-00"


def load_fundamentals(db: Session, full: bool = False, only: list[str] | None = None) -> JobResult:
    res = JobResult()
    index = esef.fetch_filing_index("GR")
    by_lei: dict[str, list[dict]] = {}
    for f in index:
        if f["lei"]:
            by_lei.setdefault(f["lei"], []).append(f)
    universe = db.execute(select(Instrument).where(Instrument.lei.is_not(None), Instrument.data_source == "yahoo")).scalars().all()
    if not universe:
        res.notes.append("no Greek instruments yet -- run the equities job first")
    for inst in universe:
        if only and inst.ticker not in only:
            continue
        filings = sorted(by_lei.get(inst.lei, []), key=lambda f: (_filing_period(f), f["processed"]))
        if not filings:
            res.notes.append(f"{inst.ticker}: no ESEF filings indexed")
            continue
        # Each filing restates the prior year's comparatives, so filings are applied oldest -> newest.
        # Skip the company when its newest filing is already applied.
        if not full and filings[-1]["filing_id"] in w.ingested_filing_ids(db, inst):
            continue
        try:
            for f in filings:
                res.rows += w.upsert_reported_facts(db, inst, esef.fetch_facts(f["json_url"]), f["filing_id"])
                time.sleep(REQUEST_PAUSE_S)
            res.items += 1
            db.commit()
        except Exception as e:
            db.rollback()
            res.fail(inst.ticker, e)
    return res


# ---------------------------------------------------------------------------
# Forecasting models (forecasting/): imported lazily -- forecasting imports this module
# ---------------------------------------------------------------------------
def run_forecasts(db: Session, full: bool = False, only: list[str] | None = None,
                  as_of: datetime.date | None = None) -> JobResult:
    from forecasting.jobs import run_forecasts as _run
    return _run(db, full=full, only=only, as_of=as_of)


# ---------------------------------------------------------------------------
# Registry + runner
# ---------------------------------------------------------------------------
# cron fields are APScheduler's (Europe/Athens). Athens closes 17:20 local.
JOBS = {
    "indicators":   dict(fn=load_indicators,   cron=dict(hour=7, minute=15)),
    "equities":     dict(fn=load_equities,     cron=dict(day_of_week="mon-fri", hour=18, minute=30)),
    "crypto":       dict(fn=load_crypto,       cron=dict(hour="*/6", minute=5)),
    "fundamentals": dict(fn=load_fundamentals, cron=dict(day_of_week="sun", hour=6, minute=0)),
    "snapshots":    dict(fn=compute_snapshots, cron=dict(hour=7, minute=45)),
    # after the Athens close load (18:30); retrains + re-evaluates every model, publishes approved ones
    "forecasts":    dict(fn=run_forecasts,     cron=dict(hour=19, minute=30)),
}
ORDER = ["indicators", "equities", "crypto", "fundamentals", "snapshots", "forecasts"]


def run_job(name: str, session_factory, **kwargs) -> JobResult:
    db = session_factory()
    started = datetime.datetime.now()
    log.info("[%s] starting %s", name, kwargs or "")
    try:
        result = JOBS[name]["fn"](db, **kwargs)
    except Exception as e:  # the job itself blew up (e.g. the filing index is down)
        db.rollback()
        result = JobResult()
        result.fail(name, e)
    detail = result.detail()
    db.add(PipelineRun(
        pipeline=f"market.{name}", status=result.status, started_at=started,
        finished_at=datetime.datetime.now(), rows_affected=result.rows, detail=detail[:500],
    ))
    db.commit()
    db.close()
    log.info("[%s] %s: %s", name, result.status, detail)
    return result
