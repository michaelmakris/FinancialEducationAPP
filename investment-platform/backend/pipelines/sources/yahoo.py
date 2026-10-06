"""
Yahoo Finance chart endpoint -- daily OHLCV + adjusted close for Euronext Athens
(".AT" suffix) stocks, the Athens General index (GD.AT) and global benchmarks.

  https://query2.finance.yahoo.com/v8/finance/chart/ETE.AT?period1=...&period2=...&interval=1d&events=div,split

UNOFFICIAL and not licensed for commercial redistribution. Fine for development
and internal research; replace with a licensed feed (Euronext market data, EODHD,
Twelve Data, ...) before showing these prices to customers. The PriceSource
shape in jobs.py makes that a one-module swap.
"""
from __future__ import annotations

import datetime

from . import get

BASE = "https://query2.finance.yahoo.com/v8/finance/chart/"


def parse_chart(payload: dict) -> tuple[dict, dict[datetime.date, dict]]:
    """Returns (meta, {local_date: {open, high, low, close, volume, adj_close}})."""
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        err = (payload.get("chart") or {}).get("error")
        raise RuntimeError(f"Yahoo returned no data: {err}")
    res = result[0]
    meta = dict(res.get("meta", {}))
    # a dividend/split inside the window re-bases every earlier adj_close, so callers refetch full history
    meta["has_corporate_events"] = bool(res.get("events"))
    # timestamps are the session open in UTC; shifting by the exchange offset gives the local trading day
    offset = int(meta.get("gmtoffset") or 0)
    quote = (res.get("indicators", {}).get("quote") or [{}])[0]
    adj = ((res.get("indicators", {}).get("adjclose") or [{}])[0]).get("adjclose") or []
    bars: dict[datetime.date, dict] = {}
    for i, ts in enumerate(res.get("timestamp") or []):
        close = (quote.get("close") or [None])[i] if i < len(quote.get("close") or []) else None
        if close is None:
            continue  # holiday / halted session
        day = datetime.datetime.fromtimestamp(ts + offset, tz=datetime.timezone.utc).date()

        def col(name):
            vals = quote.get(name) or []
            return float(vals[i]) if i < len(vals) and vals[i] is not None else None

        bars[day] = {
            "open": col("open"), "high": col("high"), "low": col("low"), "close": float(close),
            "volume": col("volume"), "adj_close": float(adj[i]) if i < len(adj) and adj[i] is not None else None,
        }
    return meta, bars


def fetch_daily(symbol: str, start: datetime.date) -> tuple[dict, dict[datetime.date, dict]]:
    period1 = int(datetime.datetime.combine(start, datetime.time(), tzinfo=datetime.timezone.utc).timestamp())
    period2 = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    resp = get(BASE + symbol, params={
        "period1": period1, "period2": period2, "interval": "1d",
        "events": "div,split", "includeAdjustedClose": "true",
    }, headers={"User-Agent": "Mozilla/5.0"})
    return parse_chart(resp.json())


def drop_phantom_bars(bars: dict[datetime.date, dict], max_jump: float = 0.5) -> tuple[dict[datetime.date, dict], list[datetime.date]]:
    """Drop zero-volume bars whose close jumps more than max_jump from the last
    TRADED close. Yahoo fills suspended sessions with such placeholder prices
    (e.g. ETE.AT 2015-11-30..12-02 at ~15x the real price during the
    recapitalisation). Real moves, even on thin days, trade some volume."""
    kept, dropped, last_traded = {}, [], None
    for d in sorted(bars):
        b = bars[d]
        if not b.get("volume") and last_traded and abs(b["close"] / last_traded - 1) > max_jump:
            dropped.append(d)
            continue
        kept[d] = b
        if b.get("volume"):
            last_traded = b["close"]
    return kept, dropped
