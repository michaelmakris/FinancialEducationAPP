"""
Runs all four data-ingestion pipelines (SEC fundamentals, CoinGecko crypto
prices, Alpha Vantage equity/ETF prices, FRED macro data) on a recurring
schedule and writes the results into the database via pipelines/db_writer.py.

Each pipeline runs in its own try/except so one failing source (e.g. a rate
limit or an outage) never stops the others. Runs once immediately on start,
then on the configured interval.

Usage:
    python -m scripts.run_ingestion_scheduler                 # every 60 min
    python -m scripts.run_ingestion_scheduler --minutes 15    # custom interval
    python -m scripts.run_ingestion_scheduler --once           # single run, then exit (for testing)
"""
from __future__ import annotations

import argparse
import datetime
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from app.config import settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.models import PipelineRun  # noqa: E402
from pipelines import crypto_ingest, db_writer, macro_ingest, prices_ingest, sec_ingest  # noqa: E402
from scripts.generate_dataset import CRYPTO, EQUITIES, ETFS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("ingestion")

# Alpha Vantage's free tier is capped at 25 requests/day -- ingesting all
# 12 equities+ETFs every tick would blow through that in half a day. Instead
# we round-robin one ticker per tick, so at an hourly cadence the full
# universe refreshes roughly every 12 hours while staying well under budget.
_PRICE_TICKERS = [e["ticker"] for e in EQUITIES] + [e["ticker"] for e in ETFS]
_price_cursor = 0


class Skipped(Exception):
    """Raised by a pipeline to indicate a deliberate no-op (e.g. missing API
    key) rather than a failure -- logged as status='skipped', not 'error'."""


def _run_macro(db) -> tuple[int, str]:
    if not settings.fred_api_key:
        raise Skipped("no FRED_API_KEY")
    policy_rate = macro_ingest.fetch_fred_series(macro_ingest.FRED_SERIES["policy_rate"], settings.fred_api_key)
    yield_10y = macro_ingest.fetch_fred_series(macro_ingest.FRED_SERIES["yield_10y"], settings.fred_api_key)
    cpi_index = macro_ingest.fetch_fred_series(macro_ingest.FRED_SERIES["cpi_index"], settings.fred_api_key)
    vix = macro_ingest.fetch_fred_series(macro_ingest.FRED_SERIES["vix"], settings.fred_api_key)
    cpi_yoy = macro_ingest.cpi_index_to_yoy(cpi_index)
    aligned = macro_ingest.align_monthly(policy_rate, yield_10y, cpi_yoy, vix)
    n = db_writer.upsert_macro_observations(db, aligned)
    return n, f"{n} monthly observations upserted"


def _run_crypto(db) -> tuple[int, str]:
    tickers = [c["ticker"] for c in CRYPTO]
    by_ticker = crypto_ingest.ingest_crypto(tickers, days=30, api_key=settings.coingecko_api_key)
    total = 0
    for c in CRYPTO:
        inst = db_writer.get_or_create_instrument(
            db, c["ticker"], c["name"], c["sector"], "crypto", exchange="Major venues (demo)",
        )
        total += db_writer.upsert_price_bars(db, inst, by_ticker.get(c["ticker"], {}))
    return total, f"{total} price bars upserted across {len(tickers)} coins"


def _run_sec(db) -> tuple[int, str]:
    total_rows, missing = 0, []
    for e in EQUITIES:
        cik = sec_ingest.lookup_cik(e["ticker"])
        if not cik:
            missing.append(e["ticker"])
            continue
        rows = sec_ingest.normalize_company_facts(cik, e["ticker"])
        inst = db_writer.get_or_create_instrument(
            db, e["ticker"], e["name"], e["sector"], "equity", exchange="NASDAQ/NYSE (demo)",
        )
        total_rows += db_writer.upsert_financial_facts(db, inst, rows)
    suffix = f", no CIK found for {missing}" if missing else ""
    return total_rows, f"{total_rows} fiscal-year rows upserted across {len(EQUITIES)} equities{suffix}"


def _run_prices(db) -> tuple[int, str]:
    global _price_cursor
    if not settings.alpha_vantage_api_key:
        raise Skipped("no ALPHA_VANTAGE_API_KEY")
    ticker = _PRICE_TICKERS[_price_cursor % len(_PRICE_TICKERS)]
    _price_cursor += 1
    vendor = prices_ingest.AlphaVantageVendor(settings.alpha_vantage_api_key)
    closes = vendor.get_daily_close(ticker, outputsize="compact")
    meta = next((e for e in EQUITIES if e["ticker"] == ticker), None) or next(e for e in ETFS if e["ticker"] == ticker)
    asset_type = "equity" if meta in EQUITIES else "etf"
    inst = db_writer.get_or_create_instrument(db, ticker, meta["name"], meta["sector"], asset_type)
    n = db_writer.upsert_price_bars(db, inst, closes)
    return n, f"{n} price bars upserted for {ticker} (round-robin {_price_cursor}/{len(_PRICE_TICKERS)})"


def run_all():
    init_db()
    db = SessionLocal()
    started = datetime.datetime.now()
    log.info("=== ingestion run starting ===")
    for name, fn in [("macro", _run_macro), ("crypto", _run_crypto),
                      ("fundamentals", _run_sec), ("prices", _run_prices)]:
        pipeline_started = datetime.datetime.now()
        try:
            rows, detail = fn(db)
            db.commit()
            status = "ok"
            log.info(f"  [ok]   {name}: {detail}")
        except Skipped as e:
            db.rollback()
            rows, detail, status = 0, str(e), "skipped"
            log.info(f"  [skip] {name}: {detail}")
        except Exception as e:
            db.rollback()
            rows, detail, status = 0, f"{type(e).__name__}: {e}", "error"
            log.error(f"  [FAIL] {name}: {detail}")
        db.add(PipelineRun(
            pipeline=name, status=status, started_at=pipeline_started,
            finished_at=datetime.datetime.now(), rows_affected=rows, detail=detail[:500],
        ))
        db.commit()
    db.close()
    elapsed = (datetime.datetime.now() - started).total_seconds()
    log.info(f"=== ingestion run finished in {elapsed:.1f}s ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=60, help="Interval between runs (default: 60)")
    parser.add_argument("--once", action="store_true", help="Run once and exit, instead of scheduling")
    args = parser.parse_args()

    if args.once:
        run_all()
        sys.exit(0)

    scheduler = BlockingScheduler()
    scheduler.add_job(run_all, "interval", minutes=args.minutes, next_run_time=datetime.datetime.now())
    log.info(f"Scheduler started -- running every {args.minutes} minute(s). Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")
