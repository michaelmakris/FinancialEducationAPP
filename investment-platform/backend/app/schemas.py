from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class InstrumentOut(BaseModel):
    ticker: str
    name: str
    sector: str
    asset_type: str
    price: float
    overall_score: Optional[float] = None
    return_1m: Optional[float] = None
    return_12m: Optional[float] = None
    volatility: Optional[float] = None


class ScoreOut(BaseModel):
    ticker: str
    overall: Optional[float]
    category_scores: dict[str, Optional[float]]
    breakdown: dict[str, list[Any]]


class FinancialsOut(BaseModel):
    ticker: str
    valuation: Optional[dict[str, Any]] = None
    quality: Optional[dict[str, Any]] = None
    growth: Optional[dict[str, Any]] = None
    balance_sheet: Optional[dict[str, Any]] = None
    market: dict[str, Any]


class CompareRequest(BaseModel):
    tickers: list[str] = Field(min_length=2, max_length=5)


class TradeRequest(BaseModel):
    ticker: str
    qty: float = Field(gt=0)


class PositionOut(BaseModel):
    ticker: str
    qty: float
    avg_cost: float
    price: float
    value: float
    unrealized_pnl_pct: float


class PortfolioOut(BaseModel):
    cash: float
    starting_cash: float
    total_value: float
    total_pnl_pct: float
    positions: list[PositionOut]


class SimulationRequest(BaseModel):
    amount: float = Field(gt=0)
    equities_pct: float = Field(ge=0, le=100)
    bonds_pct: float = Field(ge=0, le=100)
    crypto_pct: float = Field(ge=0, le=100)
    cash_pct: float = Field(ge=0, le=100)
    horizon_months: float = Field(gt=0, le=120)

    @model_validator(mode="after")
    def _weights_sum_positive(self):
        if self.equities_pct + self.bonds_pct + self.crypto_pct + self.cash_pct <= 0:
            raise ValueError("At least one of equities_pct/bonds_pct/crypto_pct/cash_pct must be greater than 0")
        return self


class SimulationResponse(BaseModel):
    amount: float
    horizon_months: float
    weights: dict[str, float]
    median: float
    p10: float
    p25: float
    p75: float
    p90: float
    prob_loss: float
    prob_gain_10: float
    assumptions: dict[str, Any]
