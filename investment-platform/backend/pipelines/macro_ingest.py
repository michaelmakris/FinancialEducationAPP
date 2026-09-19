"""
Macro data ingestion: FRED (US Federal Reserve) and the ECB Data Portal.

FRED (verified against current API docs):
  https://api.stlouisfed.org/fred/series/observations
      ?series_id=FEDFUNDS&api_key={key}&file_type=json
  Common series used here: FEDFUNDS (effective fed funds rate), DGS10 (10Y
  Treasury yield), CPIAUCSL (CPI, needs YoY transform), VIXCLS (VIX).
  Requires a free FRED API key (https://fred.stlouisfed.org/docs/api/api_key.html).

ECB Data Portal (verified against current API docs):
  https://data-api.ecb.europa.eu/service/data/{flowRef}/{key}?format=csvdata&startPeriod=YYYY-MM-DD
  No key required. Example flow: ICP.M.U2.N.000000.4.ANR (euro-area HICP YoY).

IMPORTANT: this sandbox's network egress does not include stlouisfed.org or
ecb.europa.eu, so this has NOT been run against either live API.
"""
from __future__ import annotations

import csv
import datetime
import io
from typing import Optional

import requests

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
ECB_BASE = "https://data-api.ecb.europa.eu/service/data"

FRED_SERIES = {
    "policy_rate": "FEDFUNDS",
    "yield_10y": "DGS10",
    "cpi_index": "CPIAUCSL",  # index level; caller computes YoY % change
    "vix": "VIXCLS",
}


def fetch_fred_series(series_id: str, api_key: str, start: str = "2015-01-01") -> dict[datetime.date, float]:
    resp = requests.get(FRED_BASE, params={
        "series_id": series_id, "api_key": api_key, "file_type": "json",
        "observation_start": start,
    }, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    out = {}
    for obs in payload.get("observations", []):
        if obs["value"] == ".":  # FRED's marker for a missing observation
            continue
        out[datetime.date.fromisoformat(obs["date"])] = float(obs["value"])
    return out


def cpi_index_to_yoy(cpi_index: dict[datetime.date, float]) -> dict[datetime.date, float]:
    """FRED publishes the CPI index level, not the YoY % change our schema
    wants -- compute it from the index 12 months apart."""
    sorted_dates = sorted(cpi_index)
    out = {}
    for d in sorted_dates:
        prior = datetime.date(d.year - 1, d.month, 1)
        if prior in cpi_index:
            out[d] = cpi_index[d] / cpi_index[prior] - 1
    return out


def align_monthly(
    policy_rate: dict[datetime.date, float],
    yield_10y: dict[datetime.date, float],
    cpi_yoy: dict[datetime.date, float],
    vix: dict[datetime.date, float],
) -> dict[datetime.date, dict[str, float]]:
    """FRED mixes monthly series (FEDFUNDS, CPIAUCSL) with daily ones (DGS10,
    VIXCLS), but MacroObservation wants one row per month with all four
    fields. Anchor on the months where the monthly series have data, and for
    the daily series take the last observation on or before that month's end
    (a month-end snapshot) -- only emitting a row where all four are present,
    since the schema requires it."""
    out: dict[datetime.date, dict[str, float]] = {}
    daily_sorted = {
        "yield_10y": sorted(yield_10y.items()),
        "vix": sorted(vix.items()),
    }

    def last_on_or_before(series: list[tuple[datetime.date, float]], cutoff: datetime.date) -> Optional[float]:
        val = None
        for d, v in series:
            if d > cutoff:
                break
            val = v
        return val

    months = set(policy_rate) & set(cpi_yoy)
    for month_start in months:
        if month_start.month == 12:
            month_end = datetime.date(month_start.year, 12, 31)
        else:
            month_end = datetime.date(month_start.year, month_start.month + 1, 1) - datetime.timedelta(days=1)
        y10 = last_on_or_before(daily_sorted["yield_10y"], month_end)
        vx = last_on_or_before(daily_sorted["vix"], month_end)
        if y10 is None or vx is None:
            continue
        out[month_start] = {
            "policy_rate": policy_rate[month_start], "yield_10y": y10,
            "cpi_yoy": cpi_yoy[month_start], "vix": vx,
        }
    return out


def fetch_ecb_series(flow_ref: str, key: str, start: str = "2015-01-01") -> dict[datetime.date, float]:
    """`key` is the ECB series key within the flow, e.g. 'M.U2.N.000000.4.ANR'
    for euro-area HICP YoY under flow 'ICP'."""
    resp = requests.get(f"{ECB_BASE}/{flow_ref}/{key}", params={"format": "csvdata", "startPeriod": start}, timeout=30)
    resp.raise_for_status()
    reader = csv.DictReader(io.StringIO(resp.text))
    out = {}
    for row in reader:
        period = row.get("TIME_PERIOD")
        value = row.get("OBS_VALUE")
        if period and value:
            # ECB monthly periods look like "2026-07" -- normalize to the 1st of month
            year, month = period.split("-")[:2]
            out[datetime.date(int(year), int(month), 1)] = float(value)
    return out


if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

    key = os.environ.get("FRED_API_KEY")
    if not key:
        print("Set FRED_API_KEY to run this against the live API.")
        sys.exit(1)
    series_name = sys.argv[1] if len(sys.argv) > 1 else "policy_rate"
    data = fetch_fred_series(FRED_SERIES[series_name], key)
    latest = max(data)
    print(f"{series_name}: {len(data)} observations, latest {latest} = {data[latest]}")
