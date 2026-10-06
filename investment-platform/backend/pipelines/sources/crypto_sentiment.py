"""
Crypto-wide daily series, both free with no key:

  Fear & Greed index (alternative.me, since 2018):  https://api.alternative.me/fng/?limit=0&format=json
  Total DeFi TVL in USD (DefiLlama):                 https://api.llama.fi/v2/historicalChainTvl
"""
from __future__ import annotations

import datetime

from . import get, utc_day

FEAR_GREED_URL = "https://api.alternative.me/fng/"
DEFI_TVL_URL = "https://api.llama.fi/v2/historicalChainTvl"


def parse_fear_greed(payload: dict) -> list[tuple[datetime.date, float]]:
    return sorted((utc_day(int(d["timestamp"])), float(d["value"])) for d in payload.get("data", []))


def fetch_fear_greed() -> list[tuple[datetime.date, float]]:
    return parse_fear_greed(get(FEAR_GREED_URL, params={"limit": 0, "format": "json"}).json())


def parse_defi_tvl(rows: list[dict]) -> list[tuple[datetime.date, float]]:
    return sorted((utc_day(int(r["date"])), float(r["tvl"])) for r in rows)


def fetch_defi_tvl() -> list[tuple[datetime.date, float]]:
    return parse_defi_tvl(get(DEFI_TVL_URL, timeout=60).json())
