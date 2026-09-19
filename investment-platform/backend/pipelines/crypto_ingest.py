"""
Crypto ingestion via CoinGecko's public API (verified against current docs).

  Current prices/market data:  https://api.coingecko.com/api/v3/coins/markets
      ?vs_currency=usd&ids=bitcoin,ethereum,solana&order=market_cap_desc&per_page=250&page=1

  Historical daily closes:     https://api.coingecko.com/api/v3/coins/{id}/market_chart
      ?vs_currency=usd&days=365&interval=daily

CoinGecko's free ("Demo") tier requires no key for basic endpoints but is
rate-limited (roughly 30 calls/minute) and appreciates an
`x-cg-demo-api-key` header if you register for a free demo key; the paid
tier uses `pro-api.coingecko.com` with `x-cg-pro-api-key`.

IMPORTANT: this sandbox's network egress does not include coingecko.com, so
this has NOT been run against the live API.
"""
from __future__ import annotations

import datetime

import requests

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# CoinGecko's asset ids != tickers -- keep an explicit mapping rather than guessing.
TICKER_TO_COINGECKO_ID = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}


def _headers(api_key: str | None) -> dict:
    return {"x-cg-demo-api-key": api_key} if api_key else {}


def fetch_market_snapshot(coin_ids: list[str], vs_currency: str = "usd", api_key: str | None = None) -> list[dict]:
    """Current price/market-cap/24h-change snapshot for a list of CoinGecko ids."""
    resp = requests.get(
        f"{COINGECKO_BASE}/coins/markets",
        params={"vs_currency": vs_currency, "ids": ",".join(coin_ids), "order": "market_cap_desc",
                "per_page": len(coin_ids), "page": 1},
        headers=_headers(api_key), timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_daily_close(coin_id: str, days: int = 365, vs_currency: str = "usd", api_key: str | None = None) -> dict[datetime.date, float]:
    """Historical daily close prices for one coin over the trailing `days`."""
    resp = requests.get(
        f"{COINGECKO_BASE}/coins/{coin_id}/market_chart",
        params={"vs_currency": vs_currency, "days": days, "interval": "daily"},
        headers=_headers(api_key), timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    # payload["prices"] is a list of [unix_ms_timestamp, price]
    out = {}
    for ts_ms, price in payload.get("prices", []):
        day = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=datetime.timezone.utc).date()
        out[day] = float(price)
    return out


def ingest_crypto(tickers: list[str], days: int = 365, api_key: str | None = None) -> dict[str, dict[datetime.date, float]]:
    out = {}
    for ticker in tickers:
        coin_id = TICKER_TO_COINGECKO_ID.get(ticker.upper())
        if not coin_id:
            raise ValueError(f"No CoinGecko id mapping for '{ticker}' -- add it to TICKER_TO_COINGECKO_ID")
        out[ticker.upper()] = fetch_daily_close(coin_id, days=days, api_key=api_key)
    return out


if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

    tickers = sys.argv[1:] or ["BTC", "ETH", "SOL"]
    result = ingest_crypto(tickers, days=30, api_key=os.environ.get("COINGECKO_API_KEY"))
    for ticker, series in result.items():
        latest_date = max(series)
        print(f"{ticker}: {len(series)} days, latest {latest_date} = {series[latest_date]}")
