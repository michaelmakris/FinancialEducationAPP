"""Read the inputs the models need from the database, as pandas objects."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import market_repo as mr
from app.models import Instrument, PriceBar
from app.services import market as calc

MIN_HISTORY_DAYS = 300  # instruments with less daily history are skipped


def price_panel(db: Session, asset_types: tuple[str, ...] = ("equity", "index", "etf", "crypto")) -> dict[str, pd.Series]:
    """{ticker: adjusted close series (DatetimeIndex)} for real instruments with enough history."""
    insts = [i for i in mr.list_instruments(db) if i.asset_type in asset_types]
    series = mr.adj_close_series(db, [i.id for i in insts])
    out = {}
    for i in insts:
        s = series.get(i.id) or []
        if len(s) >= MIN_HISTORY_DAYS:
            out[i.ticker] = pd.Series([v for _, v in s], index=pd.DatetimeIndex([d for d, _ in s]), name=i.ticker).astype(float)
    return out


def instruments_by_ticker(db: Session) -> dict[str, Instrument]:
    return {i.ticker: i for i in mr.list_instruments(db)}


def indicator(db: Session, indicator_id: str) -> pd.Series:
    s = mr.indicator_series(db, indicator_id)
    return pd.Series([v for _, v in s], index=pd.DatetimeIndex([d for d, _ in s]), name=indicator_id, dtype=float)


def latest_fundamentals(db: Session) -> dict[str, dict]:
    """{ticker: newest fiscal year from normalize_fundamentals} for equities with ESEF data."""
    out = {}
    for i in mr.list_instruments(db):
        if i.asset_type != "equity":
            continue
        years = calc.normalize_fundamentals(mr.reported_facts(db, i.id))
        if years:
            out[i.ticker] = {**years[0], "sector": i.sector, "history": years}
    return out


def last_price_date(db: Session):
    return db.execute(select(func.max(PriceBar.date))).scalar()
