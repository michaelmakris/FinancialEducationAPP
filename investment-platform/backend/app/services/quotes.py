"""
Live quotes for the practice portfolio: today's 5-minute prices and the latest price.

  stocks, ETFs, indices  Yahoo chart API, range=1d interval=5m (exchange-delayed, ~15 min
                         for most; unofficial and unlicensed -- development only, like the
                         daily loads in pipelines/sources/yahoo.py)
  crypto                 Binance 5m klines since midnight Athens time (live)
  USD -> EUR             Yahoo EURUSD=X, falling back to the ECB daily rate in the database

Everything is cached for QUOTE_CACHE_TTL_S seconds so a page refresh or a trade
does not hit the providers again. When a provider is unreachable the latest
daily close from the database is used and `live` is False.
"""
from __future__ import annotations

import datetime
import threading
import time
import zoneinfo
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings

ATHENS = zoneinfo.ZoneInfo("Europe/Athens")
YAHOO = "https://query2.finance.yahoo.com/v8/finance/chart/"
BINANCE = "https://api.binance.com/api/v3/klines"
FX_SYMBOL = {"USD": "EURUSD=X"}  # Yahoo quotes it as USD per 1 EUR

_cache: dict[tuple, tuple[float, object]] = {}
_lock = threading.Lock()


@dataclass
class Intraday:
    ticker: str
    currency: str
    prev_close: float | None                     # the reference for "today's change"
    points: list[tuple[datetime.datetime, float]] = field(default_factory=list)  # UTC, ascending
    market_open: bool = False
    live: bool = True                            # False = provider failed, daily close used

    @property
    def last(self) -> float | None:
        return self.points[-1][1] if self.points else self.prev_close

    @property
    def as_of(self) -> datetime.datetime | None:
        return self.points[-1][0] if self.points else None


def _cached(key: tuple, fn):
    ttl = settings.quote_cache_ttl_s
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if ttl > 0 and hit and now - hit[0] < ttl:
            return hit[1]
    value = fn()
    if ttl > 0:
        with _lock:
            _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def athens_midnight_utc(now: datetime.datetime | None = None) -> datetime.datetime:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    local = now.astimezone(ATHENS)
    return datetime.datetime.combine(local.date(), datetime.time(), tzinfo=ATHENS).astimezone(datetime.timezone.utc)


# ---------------------------------------------------------------- providers (patched in tests)
def _http_get(url: str, params: dict):
    from pipelines.sources import get  # retries + backoff, same as the daily loads
    return get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, retries=2, timeout=10).json()


def parse_yahoo_intraday(ticker: str, payload: dict) -> Intraday:
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError(f"Yahoo returned no intraday data for {ticker}")
    res = result[0]
    meta = res.get("meta", {})
    closes = ((res.get("indicators", {}).get("quote") or [{}])[0]).get("close") or []
    pts = []
    for ts, c in zip(res.get("timestamp") or [], closes):
        if c is not None:
            pts.append((datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc), float(c)))
    last_price = meta.get("regularMarketPrice")
    last_time = meta.get("regularMarketTime")
    if last_price is not None and last_time and (not pts or last_time > pts[-1][0].timestamp()):
        pts.append((datetime.datetime.fromtimestamp(last_time, tz=datetime.timezone.utc), float(last_price)))
    period = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    now = time.time()
    is_open = bool(period) and period.get("start", 0) <= now <= period.get("end", 0)
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    return Intraday(ticker=ticker, currency=meta.get("currency") or "", prev_close=float(prev) if prev else None,
                    points=pts, market_open=is_open)


def fetch_yahoo_intraday(ticker: str, symbol: str) -> Intraday:
    return parse_yahoo_intraday(ticker, _http_get(YAHOO + symbol, {"range": "1d", "interval": "5m"}))


def parse_binance_intraday(ticker: str, rows: list) -> Intraday:
    # [open_time_ms, open, high, low, close, ...]; the last candle is still forming = the live price
    pts = [(datetime.datetime.fromtimestamp(r[0] / 1000 + 300, tz=datetime.timezone.utc), float(r[4])) for r in rows]
    now = datetime.datetime.now(datetime.timezone.utc)
    if pts and pts[-1][0] > now:
        pts[-1] = (now, pts[-1][1])
    prev = float(rows[0][1]) if rows else None  # price at midnight Athens time
    return Intraday(ticker=ticker, currency="EUR", prev_close=prev, points=pts, market_open=True)


def fetch_binance_intraday(ticker: str, pair: str) -> Intraday:
    start_ms = int(athens_midnight_utc().timestamp() * 1000)
    return parse_binance_intraday(ticker, _http_get(BINANCE, {"symbol": pair, "interval": "5m", "startTime": start_ms, "limit": 1000}))


# ---------------------------------------------------------------- public API
def _daily_fallback(db: Session, inst: M.Instrument) -> Intraday:
    bars = db.execute(select(M.PriceBar.date, M.PriceBar.close).where(M.PriceBar.instrument_id == inst.id)
                      .order_by(M.PriceBar.date.desc()).limit(2)).all()
    last = bars[0][1] if bars else None
    pts = []
    if bars:
        pts = [(datetime.datetime.combine(bars[0][0], datetime.time(15), tzinfo=datetime.timezone.utc), float(last))]
    prev = float(bars[1][1]) if len(bars) > 1 else (float(last) if last is not None else None)
    return Intraday(ticker=inst.ticker, currency=inst.currency, prev_close=prev, points=pts, market_open=False, live=False)


def intraday(db: Session, inst: M.Instrument) -> Intraday:
    """Today's 5-minute prices for one instrument (cached)."""
    def build():
        try:
            if inst.data_source == "binance":
                out = fetch_binance_intraday(inst.ticker, inst.vendor_symbol or "")
            else:
                out = fetch_yahoo_intraday(inst.ticker, inst.vendor_symbol or inst.ticker)
            if not out.points:
                raise RuntimeError("no prices today")
            out.currency = out.currency or inst.currency
            return out
        except Exception:
            return _daily_fallback(db, inst)
    return _cached(("intraday", inst.ticker), build)


def _ecb_eur_per(db: Session, currency: str) -> float:
    if currency != "USD":
        raise RuntimeError(f"no FX source for {currency}")
    row = db.execute(select(M.IndicatorObservation.value).where(M.IndicatorObservation.indicator_id == "eurusd")
                     .order_by(M.IndicatorObservation.period_date.desc()).limit(1)).scalar()
    if not row:
        raise RuntimeError("no EUR/USD rate available")
    return 1.0 / float(row)


def fx_intraday(db: Session, currency: str) -> Intraday:
    """EUR per 1 unit of `currency` through today (constant 1.0 for EUR)."""
    if currency in ("", "EUR"):
        return Intraday(ticker="EUR", currency="EUR", prev_close=1.0,
                        points=[(datetime.datetime.now(datetime.timezone.utc), 1.0)], market_open=True)

    def build():
        try:
            q = fetch_yahoo_intraday(currency, FX_SYMBOL[currency])
            if not q.points:
                raise RuntimeError("no FX points")
            inv = Intraday(ticker=currency, currency="EUR", prev_close=1 / q.prev_close if q.prev_close else None,
                           points=[(t, 1 / p) for t, p in q.points if p], market_open=q.market_open)
            return inv
        except Exception:
            rate = _ecb_eur_per(db, currency)
            return Intraday(ticker=currency, currency="EUR", prev_close=rate,
                            points=[(datetime.datetime.now(datetime.timezone.utc), rate)], live=False)
    return _cached(("fx", currency), build)


def price_at(points: list[tuple[datetime.datetime, float]], t: datetime.datetime, default: float | None) -> float | None:
    """Last price at or before t (step function), `default` before the first point."""
    out = default
    for pt, p in points:
        if pt > t:
            break
        out = p
    return out
