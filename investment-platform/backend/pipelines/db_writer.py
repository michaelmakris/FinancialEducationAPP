"""
Upsert helpers that take each pipeline's normalized output (plain dicts, no
DB knowledge -- see prices_ingest.py / crypto_ingest.py / sec_ingest.py /
macro_ingest.py) and write it into the database. Kept separate from the
pipelines themselves so they stay easy to unit test with fake vendors.

Every write here is "get existing row, update if found, else insert" rather
than a dialect-specific ON CONFLICT upsert, so the same code works
unmodified against both SQLite (local dev) and Postgres (production).
"""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FinancialFact, Instrument, MacroObservation, PriceBar


def get_or_create_instrument(
    db: Session, ticker: str, name: str, sector: str, asset_type: str,
    exchange: str = "", currency: str = "USD",
) -> Instrument:
    inst = db.execute(select(Instrument).where(Instrument.ticker == ticker)).scalar_one_or_none()
    if inst is None:
        inst = Instrument(
            id=str(uuid.uuid4()), ticker=ticker, name=name, sector=sector,
            asset_type=asset_type, exchange=exchange, currency=currency,
        )
        db.add(inst)
        db.flush()  # assign inst.id-backed relationships before price/fact rows reference it
    return inst


def upsert_price_bars(db: Session, instrument: Instrument, closes: dict[datetime.date, float]) -> int:
    """closes: {date: close_price}. Returns the number of rows written (new + updated)."""
    if not closes:
        return 0
    existing = {
        b.date: b for b in db.execute(
            select(PriceBar).where(PriceBar.instrument_id == instrument.id)
        ).scalars()
    }
    count = 0
    for d, close in closes.items():
        row = existing.get(d)
        if row is None:
            db.add(PriceBar(instrument_id=instrument.id, date=d, close=close))
        elif row.close != close:
            row.close = close
        else:
            continue
        count += 1
    return count


def upsert_financial_facts(db: Session, instrument: Instrument, rows: list[dict]) -> int:
    """rows: SEC-ingest-shaped dicts, one per fiscal_year (see sec_ingest.normalize_company_facts)."""
    if not rows:
        return 0
    existing = {
        f.fiscal_year: f for f in db.execute(
            select(FinancialFact).where(FinancialFact.instrument_id == instrument.id)
        ).scalars()
    }
    fields = [
        "revenue", "gross_profit", "operating_income", "net_income", "ebitda",
        "free_cash_flow", "total_assets", "total_equity", "total_debt",
        "current_assets", "current_liabilities", "interest_expense", "shares_diluted", "eps",
    ]
    count = 0
    for r in rows:
        fy = r["fiscal_year"]
        row = existing.get(fy)
        if row is None:
            db.add(FinancialFact(
                instrument_id=instrument.id, fiscal_year=fy,
                published_at=datetime.date.today(),
                **{k: r[k] for k in fields},
            ))
        else:
            for k in fields:
                setattr(row, k, r[k])
        count += 1
    return count


def upsert_macro_observations(db: Session, rows: dict[datetime.date, dict[str, float]]) -> int:
    """rows: {date: {policy_rate, yield_10y, cpi_yoy, vix}} (see macro_ingest.align_monthly)."""
    if not rows:
        return 0
    existing = {
        m.date: m for m in db.execute(select(MacroObservation)).scalars()
    }
    count = 0
    for d, vals in rows.items():
        row = existing.get(d)
        if row is None:
            db.add(MacroObservation(date=d, **vals))
        else:
            for k, v in vals.items():
                setattr(row, k, v)
        count += 1
    return count
