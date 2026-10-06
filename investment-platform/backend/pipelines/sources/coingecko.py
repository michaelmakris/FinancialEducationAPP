"""
CoinGecko /coins/markets -- current market cap, 24h volume, supply and rank.
Free "Demo" tier: no key needed (an x-cg-demo-api-key raises the rate limit);
attribution to CoinGecko is required when the data is displayed.

  https://api.coingecko.com/api/v3/coins/markets?vs_currency=eur&ids=bitcoin,ethereum
"""
from __future__ import annotations

from . import get

BASE = "https://api.coingecko.com/api/v3/coins/markets"


def parse_markets(rows: list[dict]) -> dict[str, dict]:
    """{coingecko_id: {price, market_cap, volume_24h, circulating_supply, market_cap_rank}}"""
    return {
        r["id"]: {
            "price": r.get("current_price"), "market_cap": r.get("market_cap"),
            "volume_24h": r.get("total_volume"), "circulating_supply": r.get("circulating_supply"),
            "market_cap_rank": r.get("market_cap_rank"),
        }
        for r in rows
    }


def fetch_markets(coin_ids: list[str], vs_currency: str = "eur", api_key: str | None = None) -> dict[str, dict]:
    resp = get(BASE, params={"vs_currency": vs_currency, "ids": ",".join(coin_ids), "per_page": 250, "page": 1},
               headers={"x-cg-demo-api-key": api_key} if api_key else None)
    return parse_markets(resp.json())
