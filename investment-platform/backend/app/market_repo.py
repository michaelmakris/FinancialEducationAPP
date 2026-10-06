"""
DB access for the real-market-data API (/v1). Only touches instruments with
data_source != 'simulated'; the demo analytics keep using repo.py.

Every function here is a small number of queries regardless of universe size
(no per-instrument loops) -- against Neon each round trip costs ~100 ms.
"""
from __future__ import annotations

import datetime
import time
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models
from .config import settings

M = models


# ---------------------------------------------------------------- tiny TTL cache
_cache: dict[tuple, tuple[float, Any]] = {}


def cached(key: tuple, fn: Callable[[], Any]) -> Any:
    """Market data changes at most every few hours; cache the expensive
    whole-universe reads for MARKET_CACHE_TTL_S seconds (0 disables)."""
    ttl = settings.market_cache_ttl_s
    now = time.monotonic()
    if ttl > 0 and key in _cache and now - _cache[key][0] < ttl:
        return _cache[key][1]
    value = fn()
    if ttl > 0:
        _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    _cache.clear()


# ---------------------------------------------------------------- instruments
def _real():
    return M.Instrument.data_source != "simulated"


def list_instruments(db: Session) -> list[M.Instrument]:
    return list(db.execute(select(M.Instrument).where(_real()).order_by(M.Instrument.ticker)).scalars())


def get_instrument(db: Session, ticker: str) -> M.Instrument | None:
    return db.execute(
        select(M.Instrument).where(_real(), func.upper(M.Instrument.ticker) == ticker.upper())
    ).scalar_one_or_none()


def get_instruments(db: Session, tickers: list[str]) -> dict[str, M.Instrument]:
    wanted = {t.upper() for t in tickers}
    rows = db.execute(select(M.Instrument).where(_real(), func.upper(M.Instrument.ticker).in_(wanted))).scalars()
    return {i.ticker.upper(): i for i in rows}


def bars(db: Session, instrument_id: str, start: datetime.date | None = None, end: datetime.date | None = None) -> list[dict]:
    q = select(M.PriceBar).where(M.PriceBar.instrument_id == instrument_id)
    if start:
        q = q.where(M.PriceBar.date >= start)
    if end:
        q = q.where(M.PriceBar.date <= end)
    return [
        {"date": b.date, "open": b.open, "high": b.high, "low": b.low, "close": b.close,
         "volume": b.volume, "adj_close": b.adj_close if b.adj_close is not None else b.close}
        for b in db.execute(q.order_by(M.PriceBar.date)).scalars()
    ]


def adj_close_series(db: Session, instrument_ids: list[str], since: datetime.date | None = None) -> dict[str, list[tuple[datetime.date, float]]]:
    """One query for many instruments: {instrument_id: [(date, adj_close or close)]}."""
    if not instrument_ids:
        return {}
    q = select(M.PriceBar.instrument_id, M.PriceBar.date, func.coalesce(M.PriceBar.adj_close, M.PriceBar.close)) \
        .where(M.PriceBar.instrument_id.in_(instrument_ids))
    if since:
        q = q.where(M.PriceBar.date >= since)
    out: dict[str, list] = {i: [] for i in instrument_ids}
    for iid, d, v in db.execute(q.order_by(M.PriceBar.instrument_id, M.PriceBar.date)):
        out[iid].append((d, v))
    return out


def latest_bars(db: Session, instrument_ids: list[str]) -> dict[str, M.PriceBar]:
    if not instrument_ids:
        return {}
    last = select(M.PriceBar.instrument_id, func.max(M.PriceBar.date).label("d")) \
        .where(M.PriceBar.instrument_id.in_(instrument_ids)).group_by(M.PriceBar.instrument_id).subquery()
    rows = db.execute(select(M.PriceBar).join(last, (M.PriceBar.instrument_id == last.c.instrument_id) & (M.PriceBar.date == last.c.d))).scalars()
    return {b.instrument_id: b for b in rows}


def latest_crypto_snapshots(db: Session) -> dict[str, M.CryptoMarketSnapshot]:
    last = select(M.CryptoMarketSnapshot.instrument_id, func.max(M.CryptoMarketSnapshot.date).label("d")) \
        .group_by(M.CryptoMarketSnapshot.instrument_id).subquery()
    rows = db.execute(select(M.CryptoMarketSnapshot).join(
        last, (M.CryptoMarketSnapshot.instrument_id == last.c.instrument_id) & (M.CryptoMarketSnapshot.date == last.c.d))).scalars()
    return {s.instrument_id: s for s in rows}


def reported_facts(db: Session, instrument_id: str) -> list[dict]:
    return [
        {"concept": f.concept, "period_start": f.period_start, "period_end": f.period_end, "value": f.value, "unit": f.unit}
        for f in db.execute(select(M.ReportedFact).where(M.ReportedFact.instrument_id == instrument_id)).scalars()
    ]


# ---------------------------------------------------------------- indicators
def list_indicators(db: Session) -> list[M.Indicator]:
    return list(db.execute(select(M.Indicator).order_by(M.Indicator.category, M.Indicator.id)).scalars())


def get_indicator(db: Session, indicator_id: str) -> M.Indicator | None:
    return db.get(M.Indicator, indicator_id)


def indicator_series(db: Session, indicator_id: str, start: datetime.date | None = None,
                     end: datetime.date | None = None) -> list[tuple[datetime.date, float]]:
    q = select(M.IndicatorObservation.period_date, M.IndicatorObservation.value) \
        .where(M.IndicatorObservation.indicator_id == indicator_id)
    if start:
        q = q.where(M.IndicatorObservation.period_date >= start)
    if end:
        q = q.where(M.IndicatorObservation.period_date <= end)
    return [(d, v) for d, v in db.execute(q.order_by(M.IndicatorObservation.period_date))]


def latest_snapshot_date(db: Session, on_or_before: datetime.date | None = None) -> datetime.date | None:
    q = select(func.max(M.IndicatorSnapshot.as_of_date))
    if on_or_before:
        q = q.where(M.IndicatorSnapshot.as_of_date <= on_or_before)
    return db.execute(q).scalar()


def snapshots_on(db: Session, as_of: datetime.date) -> dict[str, M.IndicatorSnapshot]:
    rows = db.execute(select(M.IndicatorSnapshot).where(M.IndicatorSnapshot.as_of_date == as_of)).scalars()
    return {s.indicator_id: s for s in rows}


def indicator_last_observations(db: Session) -> dict[str, datetime.date]:
    rows = db.execute(select(M.IndicatorObservation.indicator_id, func.max(M.IndicatorObservation.period_date))
                      .group_by(M.IndicatorObservation.indicator_id))
    return {i: d for i, d in rows}


# ---------------------------------------------------------------- monitoring
def last_bar_dates(db: Session) -> list[tuple[M.Instrument, datetime.date | None]]:
    rows = db.execute(
        select(M.Instrument, func.max(M.PriceBar.date)).outerjoin(M.PriceBar, M.PriceBar.instrument_id == M.Instrument.id)
        .where(_real()).group_by(M.Instrument.id)
    ).all()
    return [(i, d) for i, d in rows]


def latest_fiscal_year_ends(db: Session) -> dict[str, datetime.date]:
    rows = db.execute(select(M.ReportedFact.instrument_id, func.max(M.ReportedFact.period_end)).group_by(M.ReportedFact.instrument_id))
    return {i: d for i, d in rows}


def pipeline_runs_by_job(db: Session, prefix: str = "market.") -> dict[str, dict]:
    """{job: {last: PipelineRun, last_success_at: datetime|None}} for jobs named prefix*."""
    last_q = select(M.PipelineRun.pipeline, func.max(M.PipelineRun.started_at).label("t")) \
        .where(M.PipelineRun.pipeline.like(f"{prefix}%")).group_by(M.PipelineRun.pipeline).subquery()
    lasts = db.execute(select(M.PipelineRun).join(
        last_q, (M.PipelineRun.pipeline == last_q.c.pipeline) & (M.PipelineRun.started_at == last_q.c.t))).scalars()
    ok = dict(db.execute(select(M.PipelineRun.pipeline, func.max(M.PipelineRun.finished_at))
                         .where(M.PipelineRun.pipeline.like(f"{prefix}%"), M.PipelineRun.status.in_(["ok", "partial"]))
                         .group_by(M.PipelineRun.pipeline)).all())
    return {r.pipeline[len(prefix):]: {"last": r, "last_success_at": ok.get(r.pipeline)} for r in lasts}
