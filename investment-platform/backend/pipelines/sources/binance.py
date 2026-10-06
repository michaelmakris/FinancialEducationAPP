"""
Binance public market data -- daily OHLCV klines, no key.

  https://api.binance.com/api/v3/klines?symbol=BTCEUR&interval=1d&startTime=<ms>&limit=1000

EUR pairs start in 2020 (BTCEUR: 2020-01-03). The candle for the current UTC
day is still forming; it is stored and simply overwritten on the next run.
"""
from __future__ import annotations

import datetime

from . import get, utc_day

BASE = "https://api.binance.com/api/v3/klines"
LIMIT = 1000


def parse_klines(rows: list) -> dict[datetime.date, dict]:
    # [open_time_ms, open, high, low, close, volume, close_time, quote_volume, ...]
    return {
        utc_day(r[0] / 1000): {
            "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]),
            "volume": float(r[5]), "adj_close": float(r[4]),
        }
        for r in rows
    }


def fetch_daily(pair: str, start: datetime.date) -> dict[datetime.date, dict]:
    start_ms = int(datetime.datetime.combine(start, datetime.time(), tzinfo=datetime.timezone.utc).timestamp() * 1000)
    out: dict[datetime.date, dict] = {}
    while True:
        rows = get(BASE, params={"symbol": pair, "interval": "1d", "startTime": start_ms, "limit": LIMIT}).json()
        if not rows:
            break
        out.update(parse_klines(rows))
        if len(rows) < LIMIT:
            break
        start_ms = rows[-1][0] + 24 * 3600 * 1000
    return out
