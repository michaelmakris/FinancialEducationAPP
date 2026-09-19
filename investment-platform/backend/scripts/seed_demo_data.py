"""
Seeds the database with the same simulated demo dataset used by the browser
artifact, so the backend API and the demo agree exactly.

Usage:
    python -m scripts.seed_demo_data
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import FinancialFact, Instrument, MacroObservation, PriceBar  # noqa: E402
from scripts.generate_dataset import build  # noqa: E402


def seed():
    init_db()
    dataset = build()
    db = SessionLocal()
    try:
        if db.query(Instrument).count() > 0:
            print("Database already has instruments -- skipping seed. "
                  "Delete the DB file (or drop tables) to reseed from scratch.")
            return

        dates = [datetime.date.fromisoformat(d) for d in dataset["dates"]]

        for inst in dataset["instruments"]:
            row = Instrument(
                id=inst["instrument_id"], ticker=inst["ticker"], name=inst["name"],
                sector=inst["sector"], asset_type=inst["asset_type"],
                exchange=inst["exchange"], currency=inst["currency"],
            )
            db.add(row)
            for d, close in zip(dates, inst["close"]):
                db.add(PriceBar(instrument_id=row.id, date=d, close=close))
            for f in inst["fundamentals"]:
                db.add(FinancialFact(
                    instrument_id=row.id, fiscal_year=f["fiscal_year"], revenue=f["revenue"],
                    gross_profit=f["gross_profit"], operating_income=f["operating_income"],
                    net_income=f["net_income"], ebitda=f["ebitda"], free_cash_flow=f["free_cash_flow"],
                    total_assets=f["total_assets"], total_equity=f["total_equity"], total_debt=f["total_debt"],
                    current_assets=f["current_assets"], current_liabilities=f["current_liabilities"],
                    interest_expense=f["interest_expense"], shares_diluted=f["shares_diluted"], eps=f["eps"],
                    published_at=datetime.date.fromisoformat(f["published_at"]),
                ))

        for m in dataset["macro"]:
            db.add(MacroObservation(
                date=datetime.date.fromisoformat(m["date"]), policy_rate=m["policy_rate"],
                yield_10y=m["yield_10y"], cpi_yoy=m["cpi_yoy"], vix=m["vix"],
            ))

        db.commit()
        print(f"Seeded {len(dataset['instruments'])} instruments, "
              f"{len(dates)} price dates each, {len(dataset['macro'])} macro observations.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
