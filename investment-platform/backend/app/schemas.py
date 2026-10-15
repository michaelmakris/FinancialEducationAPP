from __future__ import annotations

import datetime

from typing import Any, Literal, Optional

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
    avg_cost: float                      # EUR per unit
    price: float                         # latest, EUR per unit
    value: float                         # EUR
    unrealized_pnl_pct: float
    name: str = ""
    market: str = ""
    currency: str = ""                   # the instrument's own currency
    price_local: Optional[float] = None  # latest, in `currency`
    unrealized_pnl: float = 0.0
    day_change_pct: Optional[float] = None
    market_open: bool = False
    live: bool = False                   # False = provider unavailable, last daily close used
    as_of: Optional[datetime.datetime] = None


class PortfolioOut(BaseModel):
    cash: float
    starting_cash: float
    total_value: float
    total_pnl_pct: float
    positions: list[PositionOut]
    holdings_value: float = 0.0
    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0                 # all transaction costs so far, EUR
    cost_profile: str = "typical"          # services/costs.py PROFILES
    day_change: float = 0.0
    day_change_pct: float = 0.0
    currency: str = "EUR"


class TransactionOut(BaseModel):
    id: int
    ticker: str
    side: str
    qty: float
    price: float                         # EUR per unit
    price_local: Optional[float] = None
    currency: str = "EUR"
    fx_rate: float = 1.0
    amount: float                        # EUR, before costs
    fees: float = 0.0                    # transaction costs, EUR
    realized_pnl: Optional[float] = None
    executed_at: datetime.datetime


class ValuePoint(BaseModel):
    t: datetime.datetime
    value: float
    cash: float


class PortfolioIntradayOut(BaseModel):
    date: datetime.date
    start_value: float
    points: list[ValuePoint]
    trades: list[TransactionOut]


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


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    provider: Optional[str] = None  # one of GET /v1/llm/providers; default LLM_PROVIDER
    lang: Literal["el", "en"] = "en"  # the language Tsimp answers in


class ChatAction(BaseModel):
    type: str
    page: Optional[str] = None
    ticker: Optional[str] = None
    tickers: Optional[list[str]] = None
    side: Optional[str] = None
    qty: Optional[float] = None


class ChatResponse(BaseModel):
    reply: str
    actions: list[ChatAction] = []
    source: Literal["rules", "ai"] = "ai"   # rules = fixed wording with real numbers, no AI call
    lesson: Optional[dict] = None           # a lesson the app shows with its follow-up buttons


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
