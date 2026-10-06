"""
Daily indicator snapshot: latest value, 90-day direction, 1y-ago and EU-27
comparators, staleness and payload eligibility. Ported from the Databricks
macro-indicators notebook (fetch/normalize/direction logic unchanged); the
EL/EN descriptor templates are intentionally left out.

Pure functions only -- jobs.compute_snapshots() reads series from the DB and
writes the result.
"""
from __future__ import annotations

import datetime
from typing import Optional

Series = list[tuple[datetime.date, float]]

DIRECTION_WINDOW_D = 90  # consistent with the FRI windows in the notebook
COMPARATOR_TOLERANCE_D = 45


def period_end(d: datetime.date, freq: str) -> datetime.date:
    """Last day of the reference period that starts at d. Staleness is measured
    from here, so a Q1 GDP figure published in June still counts as fresh."""
    if freq == "D":
        return d
    months = {"M": 1, "Q": 3, "A": 12}[freq]
    y, m = d.year, d.month + months
    while m > 12:
        y, m = y + 1, m - 12
    return datetime.date(y, m, 1) - datetime.timedelta(days=1)


def latest_and_prior(series: Series, window_d: int = DIRECTION_WINDOW_D):
    """(latest_date, latest_value, prior_value): prior = the observation nearest
    to latest_date - window_d; None if there is only one observation."""
    d1, v1 = series[-1]
    target = d1 - datetime.timedelta(days=window_d)
    prior = min(series[:-1], key=lambda t: abs((t[0] - target).days), default=None)
    return d1, v1, (prior[1] if prior else None)


def value_near(series: Series, target: datetime.date, tol_d: int = COMPARATOR_TOLERANCE_D) -> Optional[float]:
    if not series:
        return None
    d, v = min(series, key=lambda t: abs((t[0] - target).days))
    return v if abs((d - target).days) <= tol_d else None


def direction(v_now: float, v_prior: Optional[float], dead_band: float = 0.0, dead_band_rel: float | None = None) -> str:
    if v_prior is None:
        return "stable"
    delta = v_now - v_prior
    band = abs(v_prior) * dead_band_rel if dead_band_rel is not None else dead_band
    return "stable" if abs(delta) <= band else ("rising" if delta > 0 else "falling")


def derive_spread(a: Series, b: Series, scale: float) -> Series:
    """(a - b) * scale on common dates, e.g. GR-DE 10y spread in bps."""
    bd = dict(b)
    return [(d, (v - bd[d]) * scale) for d, v in a if d in bd]


def compute_snapshot(cfg: dict, series: Series, as_of: datetime.date, comparator: Series | None = None) -> dict | None:
    """One indicator_snapshots row (without ids), or None if the series is empty."""
    series = sorted(s for s in series if s[0] <= as_of)
    if not series:
        return None
    snap = cfg["snapshot"]
    d1, v1, prior = latest_and_prior(series)
    age = max(0, (as_of - period_end(d1, cfg["frequency"])).days)
    return {
        "as_of_date": as_of,
        "obs_date": d1,
        "value": round(float(v1), 6),
        "value_90d_prior": prior,
        "direction_90d": direction(v1, prior, snap.get("dead_band", 0.0), snap.get("dead_band_rel")),
        "value_1y": value_near(series, d1 - datetime.timedelta(days=365)),
        "value_eu": value_near(comparator or [], d1),
        "staleness_d": int(age),
        "payload_eligible": age <= snap["staleness_cap_d"],
    }
