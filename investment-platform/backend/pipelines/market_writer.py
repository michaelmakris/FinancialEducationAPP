"""
Upserts for the real market-data tables (see db_writer.py for the demo-era
ones). Same approach as db_writer: load the existing rows for one key, update
or insert in Python -- portable across SQLite and Postgres, and one SELECT per
instrument/indicator rather than one per row, which matters against Neon.

SessionLocal has autoflush off, so every upsert flushes before reading the
existing rows -- otherwise rows added earlier in the same transaction (e.g. the
previous ESEF filing of the same company) are invisible and get inserted twice.
"""
from __future__ import annotations

import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    CryptoMarketSnapshot, Indicator, IndicatorObservation, IndicatorSnapshot, Instrument, PriceBar, ReportedFact,
)

_BAR_FIELDS = ("open", "high", "low", "close", "volume", "adj_close")


def ensure_instrument(
    db: Session, *, ticker: str, name: str, sector: str, asset_type: str, exchange: str,
    currency: str, data_source: str, country: str = "", lei: str | None = None, vendor_symbol: str | None = None,
) -> Instrument:
    inst = db.execute(select(Instrument).where(Instrument.ticker == ticker)).scalar_one_or_none()
    fields = dict(name=name, sector=sector, asset_type=asset_type, exchange=exchange, currency=currency,
                  data_source=data_source, country=country, lei=lei, vendor_symbol=vendor_symbol)
    if inst is None:
        inst = Instrument(id=str(uuid.uuid4()), ticker=ticker, **fields)
        db.add(inst)
        db.flush()
    else:
        for k, v in fields.items():
            setattr(inst, k, v)
    return inst


def last_bar_date(db: Session, instrument: Instrument) -> datetime.date | None:
    return db.execute(select(func.max(PriceBar.date)).where(PriceBar.instrument_id == instrument.id)).scalar()


def upsert_bars(db: Session, instrument: Instrument, bars: dict[datetime.date, dict], prune: bool = False) -> int:
    """bars: {date: {open, high, low, close, volume, adj_close}}. Returns rows inserted, changed or pruned.
    prune=True deletes stored bars inside the fetched date range that the source no longer has
    (or that were filtered out as bad data), so the window mirrors the cleaned source."""
    if not bars:
        return 0
    db.flush()
    lo = min(bars)
    existing = {
        b.date: b for b in db.execute(
            select(PriceBar).where(PriceBar.instrument_id == instrument.id, PriceBar.date >= lo)
        ).scalars()
    }
    count = 0
    if prune:
        hi = max(bars)
        for d, row in existing.items():
            if d <= hi and d not in bars:
                db.delete(row)
                count += 1
    for d, vals in bars.items():
        row = existing.get(d)
        if row is None:
            db.add(PriceBar(instrument_id=instrument.id, date=d, **{k: vals.get(k) for k in _BAR_FIELDS}))
            count += 1
        elif any(getattr(row, k) != vals.get(k) for k in _BAR_FIELDS):
            for k in _BAR_FIELDS:
                setattr(row, k, vals.get(k))
            count += 1
    return count


def ensure_indicator(db: Session, cfg: dict) -> Indicator:
    source_key = cfg.get("key") or (f"{cfg['dataset']}?" + "&".join(f"{k}={v}" for k, v in cfg["filters"].items())
                                    if cfg.get("dataset") else "")
    if cfg.get("formula"):
        a, b, scale = cfg["formula"]
        source_key = f"({a} - {b}) * {scale:g}"
    fields = dict(name=cfg["name"], geo=cfg["geo"], unit=cfg["unit"], frequency=cfg["frequency"],
                  source=cfg["source"], source_key=source_key[:300], category=cfg.get("category", "macro"))
    ind = db.get(Indicator, cfg["id"])
    if ind is None:
        ind = Indicator(id=cfg["id"], **fields)
        db.add(ind)
        db.flush()
    else:
        for k, v in fields.items():
            setattr(ind, k, v)
    return ind


def upsert_observations(db: Session, indicator_id: str, series: list[tuple[datetime.date, float]]) -> int:
    if not series:
        return 0
    db.flush()
    existing = {
        o.period_date: o for o in db.execute(
            select(IndicatorObservation).where(IndicatorObservation.indicator_id == indicator_id)
        ).scalars()
    }
    now = datetime.datetime.now(datetime.timezone.utc)
    count = 0
    for d, v in series:
        row = existing.get(d)
        if row is None:
            db.add(IndicatorObservation(indicator_id=indicator_id, period_date=d, value=v, fetched_at=now))
            count += 1
        elif row.value != v:  # data revision
            row.value, row.fetched_at = v, now
            count += 1
    return count


def load_series(db: Session, indicator_id: str) -> list[tuple[datetime.date, float]]:
    return [
        (o.period_date, o.value) for o in db.execute(
            select(IndicatorObservation).where(IndicatorObservation.indicator_id == indicator_id)
            .order_by(IndicatorObservation.period_date)
        ).scalars()
    ]


def upsert_snapshot(db: Session, indicator_id: str, snap: dict) -> None:
    db.flush()
    row = db.execute(select(IndicatorSnapshot).where(
        IndicatorSnapshot.indicator_id == indicator_id, IndicatorSnapshot.as_of_date == snap["as_of_date"],
    )).scalar_one_or_none()
    if row is None:
        db.add(IndicatorSnapshot(indicator_id=indicator_id, **snap))
    else:
        for k, v in snap.items():
            setattr(row, k, v)


def ingested_filing_ids(db: Session, instrument: Instrument) -> set[str]:
    return set(db.execute(
        select(ReportedFact.filing_id).where(ReportedFact.instrument_id == instrument.id).distinct()
    ).scalars())


def upsert_reported_facts(db: Session, instrument: Instrument, facts: list[dict], filing_id: str) -> int:
    if not facts:
        return 0
    db.flush()
    existing = {
        (f.concept, f.period_start, f.period_end): f for f in db.execute(
            select(ReportedFact).where(ReportedFact.instrument_id == instrument.id)
        ).scalars()
    }
    count = 0
    for f in facts:
        key = (f["concept"], f["period_start"], f["period_end"])
        row = existing.get(key)
        if row is None:
            row = ReportedFact(instrument_id=instrument.id, filing_id=filing_id, source="esef", **f)
            db.add(row)
            existing[key] = row
        else:  # a later filing (restatement or the next year's comparatives) wins
            row.value, row.unit, row.filing_id = f["value"], f["unit"], filing_id
        count += 1
    return count


def upsert_crypto_snapshot(db: Session, instrument: Instrument, day: datetime.date, currency: str, vals: dict) -> None:
    db.flush()
    row = db.execute(select(CryptoMarketSnapshot).where(
        CryptoMarketSnapshot.instrument_id == instrument.id, CryptoMarketSnapshot.date == day,
    )).scalar_one_or_none()
    if row is None:
        db.add(CryptoMarketSnapshot(instrument_id=instrument.id, date=day, currency=currency, **vals))
    else:
        for k, v in vals.items():
            setattr(row, k, v)
