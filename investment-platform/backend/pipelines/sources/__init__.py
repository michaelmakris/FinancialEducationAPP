"""
Vendor-facing fetchers for the real market-data pipelines. Every module here
only talks HTTP and returns plain Python structures -- no database imports --
so each one can be unit tested against a saved payload (see
tests/test_market_pipelines.py). pipelines/jobs.py wires them to the DB.

See pipelines/SOURCES.md for coverage, refresh cadence and licensing notes.
"""
from __future__ import annotations

import datetime
import time

import requests

USER_AGENT = "FinancialEducationApp/0.1 (data pipelines)"
TIMEOUT = 30


def get(url: str, *, params: dict | None = None, headers: dict | None = None, retries: int = 3, timeout: int = TIMEOUT) -> requests.Response:
    """GET with a User-Agent and simple backoff on 429/5xx and connection errors."""
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, headers=hdrs, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** attempt * 2)
                continue
            resp.raise_for_status()
            return resp
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
            time.sleep(2 ** attempt * 2)
    raise last or RuntimeError(f"GET {url} failed")


def parse_period(p: str) -> datetime.date:
    """Eurostat/ECB period string -> period-start date: 2026-05, 2026-Q1, 2026-05-12, 2026."""
    p = str(p).strip()
    if "-Q" in p:
        y, q = p.split("-Q")
        return datetime.date(int(y), (int(q) - 1) * 3 + 1, 1)
    parts = p.split("-")
    if len(parts) == 1:
        return datetime.date(int(parts[0]), 1, 1)
    if len(parts) == 2:
        return datetime.date(int(parts[0]), int(parts[1]), 1)
    return datetime.date.fromisoformat(p[:10])


def utc_day(ts_seconds: float) -> datetime.date:
    return datetime.datetime.fromtimestamp(ts_seconds, tz=datetime.timezone.utc).date()
