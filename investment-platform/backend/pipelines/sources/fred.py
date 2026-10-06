"""
FRED (St. Louis Fed) observations API. Free key required (FRED_API_KEY).

  https://api.stlouisfed.org/fred/series/observations?series_id=DGS10&api_key=...&file_type=json
"""
from __future__ import annotations

import datetime

from . import get

BASE = "https://api.stlouisfed.org/fred/series/observations"


def parse(payload: dict) -> list[tuple[datetime.date, float]]:
    return sorted(
        (datetime.date.fromisoformat(o["date"]), float(o["value"]))
        for o in payload.get("observations", [])
        if o.get("value") not in (".", "", None)  # "." is FRED's missing-value marker
    )


def fetch(series_id: str, api_key: str, start: str = "2010-01-01") -> list[tuple[datetime.date, float]]:
    resp = get(BASE, params={"series_id": series_id, "api_key": api_key, "file_type": "json", "observation_start": start}, timeout=60)
    return parse(resp.json())
