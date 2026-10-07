"""
Run market-data jobs by hand.

    python -m pipelines.run all                    # every job, incremental
    python -m pipelines.run all --full             # full backfill (first load)
    python -m pipelines.run equities --only ETE.AT ALPHA.AT
    python -m pipelines.run snapshots --as-of 2026-09-30

Writes to whatever DATABASE_URL points at (see ../.env).
"""
from __future__ import annotations

import argparse
import datetime
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, engine, init_db  # noqa: E402
from pipelines import jobs  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job", choices=["all", *jobs.JOBS])
    parser.add_argument("--full", action="store_true", help="backfill full history instead of a trailing window")
    parser.add_argument("--only", nargs="+", help="limit to these tickers / indicator ids")
    parser.add_argument("--as-of", type=datetime.date.fromisoformat, help="snapshot date (snapshots job only)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("pipelines").info("database: %s", engine.url.render_as_string(hide_password=True))
    init_db()

    names = jobs.ORDER if args.job == "all" else [args.job]
    failed = 0
    for name in names:
        kwargs = {"full": args.full, "only": args.only}
        if name in ("snapshots", "forecasts") and args.as_of:
            kwargs["as_of"] = args.as_of
        result = jobs.run_job(name, SessionLocal, **kwargs)
        failed += result.status == "error"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
