"""
Daily equity/ETF price ingestion.

Designed as a small vendor abstraction (`PriceVendor`) so you can swap in
whichever data vendor your budget/coverage needs call for (Alpha Vantage,
Twelve Data, Polygon.io, IEX Cloud, etc.) without touching the rest of the
pipeline. The concrete example below targets Alpha Vantage's free-tier
TIME_SERIES_DAILY endpoint (verified against its current documentation):

  https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={ticker}&outputsize=full&apikey={key}

Response shape: {"Time Series (Daily)": {"YYYY-MM-DD": {"4. close": "123.45", ...}, ...}}

IMPORTANT: this sandbox's network egress does not include alphavantage.co,
so this has NOT been run against the live API. Alpha Vantage's free tier is
also rate-limited to a handful of calls/minute -- a real ingestion job needs
a queue and backoff, not a tight loop over tickers.
"""
from __future__ import annotations

import datetime
from typing import Protocol

import requests


class PriceVendor(Protocol):
    def get_daily_close(self, ticker: str, outputsize: str = "compact") -> dict[datetime.date, float]:
        """Returns {date: close_price} for one ticker."""
        ...


class AlphaVantageVendor:
    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_daily_close(self, ticker: str, outputsize: str = "compact") -> dict[datetime.date, float]:
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": ticker,
            "outputsize": outputsize,  # "compact" = last 100 days, "full" = full history
            "apikey": self.api_key,
            "datatype": "json",
        }
        resp = requests.get(self.BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if "Time Series (Daily)" not in payload:
            raise RuntimeError(f"Unexpected Alpha Vantage response for {ticker}: {payload}")
        series = payload["Time Series (Daily)"]
        return {
            datetime.date.fromisoformat(day): float(fields["4. close"])
            for day, fields in series.items()
        }


def ingest_prices(vendor: PriceVendor, tickers: list[str], outputsize: str = "compact") -> dict[str, dict[datetime.date, float]]:
    """Fetches daily closes for a list of tickers. Caller is responsible for
    upserting the results into PriceBar rows (see app/models.py) -- keep this
    function vendor-facing only, no DB import here, so it stays easy to unit
    test with a fake vendor."""
    out = {}
    for ticker in tickers:
        out[ticker] = vendor.get_daily_close(ticker, outputsize=outputsize)
    return out


if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        print("Set ALPHA_VANTAGE_API_KEY to run this against the live API.")
        sys.exit(1)
    tickers = sys.argv[1:] or ["AAPL"]
    result = ingest_prices(AlphaVantageVendor(api_key), tickers, outputsize="compact")
    for ticker, series in result.items():
        latest_date = max(series)
        print(f"{ticker}: {len(series)} days, latest {latest_date} = {series[latest_date]}")
