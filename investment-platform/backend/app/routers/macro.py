"""
Greek / EU / global indicators (/v1/macro): catalog, native-frequency series,
and the daily snapshot (latest value, 90-day direction, 1y-ago and EU-27
comparators, staleness) computed by pipelines/snapshots.py.
"""
from __future__ import annotations

import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import market_repo as mr
from .. import market_schemas as s
from ..db import get_db

router = APIRouter(prefix="/v1/macro", tags=["macro indicators"])


def _out(ind, snap, last_obs) -> s.IndicatorOut:
    return s.IndicatorOut(
        id=ind.id, name=ind.name, geo=ind.geo, unit=ind.unit, frequency=ind.frequency, category=ind.category,
        source=ind.source, source_key=ind.source_key, last_observation=last_obs,
        snapshot=s.IndicatorSnapshotOut.model_validate(snap, from_attributes=True) if snap else None,
    )


@router.get("/indicators", response_model=list[s.IndicatorOut])
def list_indicators(
    category: Optional[str] = Query(None, description="macro | rates | fx | sentiment | commodities | crypto"),
    geo: Optional[str] = Query(None, description="EL, EU27_2020, U2, GR, DE, US, GLOBAL"),
    db: Session = Depends(get_db),
):
    as_of = mr.latest_snapshot_date(db)
    snaps = mr.snapshots_on(db, as_of) if as_of else {}
    last = mr.indicator_last_observations(db)
    return [
        _out(i, snaps.get(i.id), last.get(i.id)) for i in mr.list_indicators(db)
        if (not category or i.category == category) and (not geo or i.geo.upper() == geo.upper())
    ]


@router.get("/indicators/{indicator_id}", response_model=s.IndicatorOut)
def get_indicator(indicator_id: str, db: Session = Depends(get_db)):
    ind = mr.get_indicator(db, indicator_id)
    if ind is None:
        raise HTTPException(404, f"Unknown indicator '{indicator_id}'. See GET /v1/macro/indicators.")
    as_of = mr.latest_snapshot_date(db)
    snap = mr.snapshots_on(db, as_of).get(ind.id) if as_of else None
    return _out(ind, snap, mr.indicator_last_observations(db).get(ind.id))


@router.get("/indicators/{indicator_id}/series", response_model=s.IndicatorSeries)
def indicator_series(
    indicator_id: str,
    start: Optional[datetime.date] = Query(None, description="default: 5 years before end"),
    end: Optional[datetime.date] = None,
    db: Session = Depends(get_db),
):
    ind = mr.get_indicator(db, indicator_id)
    if ind is None:
        raise HTTPException(404, f"Unknown indicator '{indicator_id}'. See GET /v1/macro/indicators.")
    if start and end and start > end:
        raise HTTPException(422, "start must be on or before end")
    if start is None:
        start = (end or datetime.date.today()) - datetime.timedelta(days=5 * 365)
    points = [{"period_date": d, "value": v} for d, v in mr.indicator_series(db, ind.id, start, end)]
    return s.IndicatorSeries(id=ind.id, unit=ind.unit, frequency=ind.frequency, points=points)


@router.get("/snapshot", response_model=s.MacroSnapshot)
def snapshot(
    as_of: Optional[datetime.date] = Query(None, description="default: latest computed day; earlier dates return the snapshot on or before"),
    eligible_only: bool = Query(False, description="only indicators fresh enough to quote (payload_eligible)"),
    db: Session = Depends(get_db),
):
    day = mr.latest_snapshot_date(db, on_or_before=as_of)
    if day is None:
        return s.MacroSnapshot(as_of_date=None, indicators=[])
    snaps = mr.snapshots_on(db, day)
    last = mr.indicator_last_observations(db)
    rows = [_out(i, snaps[i.id], last.get(i.id)) for i in mr.list_indicators(db) if i.id in snaps]
    if eligible_only:
        rows = [r for r in rows if r.snapshot and r.snapshot.payload_eligible]
    return s.MacroSnapshot(as_of_date=day, indicators=rows)
