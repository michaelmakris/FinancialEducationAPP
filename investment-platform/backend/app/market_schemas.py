"""Response models for the real-market-data API (/v1)."""
from __future__ import annotations

import datetime
from typing import Optional

from pydantic import BaseModel


class Returns(BaseModel):
    w1: Optional[float] = None
    m1: Optional[float] = None
    m3: Optional[float] = None
    m6: Optional[float] = None
    ytd: Optional[float] = None
    y1: Optional[float] = None
    y3: Optional[float] = None
    y5: Optional[float] = None


class InstrumentSummary(BaseModel):
    ticker: str
    name: str
    asset_type: str
    sector: str
    country: str
    exchange: str
    currency: str
    data_source: str
    last_date: Optional[datetime.date] = None
    last_close: Optional[float] = None
    change_1d: Optional[float] = None
    return_1m: Optional[float] = None
    return_1y: Optional[float] = None
    has_fundamentals: bool = False


class CryptoMarket(BaseModel):
    date: datetime.date
    currency: str
    price: Optional[float] = None
    market_cap: Optional[float] = None
    volume_24h: Optional[float] = None
    circulating_supply: Optional[float] = None
    market_cap_rank: Optional[int] = None


class InstrumentDetail(InstrumentSummary):
    lei: Optional[str] = None
    vendor_symbol: Optional[str] = None
    first_date: Optional[datetime.date] = None
    returns: Returns
    volatility_1y: Optional[float] = None
    max_drawdown_1y: Optional[float] = None
    crypto_market: Optional[CryptoMarket] = None


class Bar(BaseModel):
    date: datetime.date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: float
    adj_close: Optional[float] = None
    volume: Optional[float] = None


class PriceSeries(BaseModel):
    ticker: str
    currency: str
    interval: str
    bars: list[Bar]


class Performance(BaseModel):
    ticker: str
    as_of: Optional[datetime.date]
    returns: Returns
    volatility_1y: Optional[float] = None
    max_drawdown_1y: Optional[float] = None
    max_drawdown_all: Optional[float] = None


class CompareResponse(BaseModel):
    tickers: list[str]
    currencies: dict[str, str]
    base_date: Optional[datetime.date]
    note: str
    total_return: dict[str, Optional[float]]
    points: list[dict]


class FiscalYear(BaseModel):
    fiscal_year_end: datetime.date
    metrics: dict[str, Optional[float]]
    ratios: dict[str, Optional[float]]
    sources: dict[str, str]


class Fundamentals(BaseModel):
    ticker: str
    currency: str
    source: str
    years: list[FiscalYear]
    market_ratios: dict[str, Optional[float]]
    price_date: Optional[datetime.date] = None


class IndicatorSnapshotOut(BaseModel):
    as_of_date: datetime.date
    obs_date: datetime.date
    value: float
    value_90d_prior: Optional[float] = None
    direction_90d: str
    value_1y: Optional[float] = None
    value_eu: Optional[float] = None
    staleness_d: int
    payload_eligible: bool


class IndicatorOut(BaseModel):
    id: str
    name: str
    geo: str
    unit: str
    frequency: str
    category: str
    source: str
    source_key: str
    last_observation: Optional[datetime.date] = None
    snapshot: Optional[IndicatorSnapshotOut] = None


class IndicatorSeries(BaseModel):
    id: str
    unit: str
    frequency: str
    points: list[dict]


class MacroSnapshot(BaseModel):
    as_of_date: Optional[datetime.date]
    indicators: list[IndicatorOut]


class CryptoOverview(BaseModel):
    as_of: Optional[datetime.date]
    fear_greed: Optional[IndicatorSnapshotOut] = None
    defi_tvl: Optional[IndicatorSnapshotOut] = None
    coins: list[InstrumentSummary]
    markets: dict[str, CryptoMarket]
