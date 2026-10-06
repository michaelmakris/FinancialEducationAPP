"""
ECB Data Portal (SDMX REST, csvdata flavour). Free, no key; reuse allowed with source attribution.

  https://data-api.ecb.europa.eu/service/data/{flow}/{key}?format=csvdata&startPeriod=2015-01-01

series_key is 'FLOW/KEY', e.g. 'FM/D.U2.EUR.4F.KR.DFR.LEV' (deposit facility rate).
"""
from __future__ import annotations

import csv
import datetime
import io

from . import get, parse_period

BASE = "https://data-api.ecb.europa.eu/service/data/"


def parse_csv(text: str) -> list[tuple[datetime.date, float]]:
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        period, value = row.get("TIME_PERIOD"), row.get("OBS_VALUE")
        if period and value not in (None, "", "NaN"):
            out.append((parse_period(period), float(value)))
    return sorted(out)


def fetch(series_key: str, start: str | None = "2010-01-01") -> list[tuple[datetime.date, float]]:
    params = {"format": "csvdata"}
    if start:
        params["startPeriod"] = start
    return parse_csv(get(BASE + series_key, params=params, timeout=60).text)
