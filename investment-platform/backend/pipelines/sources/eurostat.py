"""
Eurostat dissemination API (JSON-stat 2.0). Free, no key, CC BY 4.0 reuse.

  https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}?format=JSON&lang=EN&geo=EL&...

Filters must pin every non-time dimension to one category; parse_jsonstat()
asserts that, so a wrong filter fails loudly instead of returning a mix of series.
"""
from __future__ import annotations

import datetime

from . import get, parse_period

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"


def parse_jsonstat(js: dict, dataset: str = "") -> list[tuple[datetime.date, float]]:
    dims = js["id"]
    sizes = dict(zip(dims, js["size"]))
    bad = [d for d in dims if d != "time" and sizes[d] != 1]
    if bad:
        raise ValueError(f"{dataset}: dimensions {bad} not pinned to one category -- fix the filters")
    idx2period = {v: k for k, v in js["dimension"]["time"]["category"]["index"].items()}
    # with every other dimension of size 1, the flat value index is the time index
    return sorted((parse_period(idx2period[int(i)]), float(v)) for i, v in js.get("value", {}).items() if v is not None)


def fetch(dataset: str, filters: dict) -> list[tuple[datetime.date, float]]:
    resp = get(BASE + dataset, params={"format": "JSON", "lang": "EN", **filters}, timeout=60)
    return parse_jsonstat(resp.json(), dataset)
