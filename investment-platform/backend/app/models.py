from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Instrument(Base):
    """A tradeable instrument: equity, ETF, or crypto asset."""
    __tablename__ = "instruments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sector: Mapped[str] = mapped_column(String(100), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)  # equity | etf | crypto
    exchange: Mapped[str] = mapped_column(String(100), default="")
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    # "simulated" = the demo dataset (scripts/generate_dataset.py), which the
    # analytics endpoints assume shares one aligned date grid. Real market data
    # loaded by pipelines/ (yahoo, binance, ...) is kept apart by this column.
    data_source: Mapped[str] = mapped_column(String(20), default="simulated", server_default="simulated", index=True)
    country: Mapped[str] = mapped_column(String(2), default="", server_default="")
    lei: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)  # links ESEF fundamentals
    vendor_symbol: Mapped[str | None] = mapped_column(String(40), nullable=True)

    price_bars: Mapped[list["PriceBar"]] = relationship(back_populates="instrument", cascade="all, delete-orphan")
    financial_facts: Mapped[list["FinancialFact"]] = relationship(back_populates="instrument", cascade="all, delete-orphan")


class PriceBar(Base):
    """One daily bar. The simulated demo only fills `close`; real market data
    also fills open/high/low/volume/adj_close."""
    __tablename__ = "price_bars"
    __table_args__ = (UniqueConstraint("instrument_id", "date", name="uq_price_bar_instrument_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[str] = mapped_column(String(36), ForeignKey("instruments.id"), index=True, nullable=False)
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    adj_close: Mapped[float | None] = mapped_column(Float, nullable=True)  # split/dividend adjusted

    instrument: Mapped["Instrument"] = relationship(back_populates="price_bars")


class ReportedFact(Base):
    """One numeric IFRS fact from an ESEF annual report (consolidated,
    undimensioned), e.g. concept='Revenue'. Kept raw so ratios can be derived
    per industry later (banks have no 'Revenue', industrials no 'InterestIncome')."""
    __tablename__ = "reported_facts"
    __table_args__ = (UniqueConstraint("instrument_id", "concept", "period_start", "period_end", name="uq_reported_fact"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[str] = mapped_column(String(36), ForeignKey("instruments.id"), index=True, nullable=False)
    concept: Mapped[str] = mapped_column(String(200), nullable=False, index=True)  # ifrs-full local name
    period_start: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)  # None = point-in-time (balance sheet)
    period_end: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    filing_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="esef")


class Indicator(Base):
    """Catalog row for a time series: Greek/EU macro, rates, FX, crypto sentiment."""
    __tablename__ = "indicators"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # e.g. hicp_yoy, spread_10y
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    geo: Mapped[str] = mapped_column(String(20), nullable=False, default="")  # EL, EU27_2020, U2, US, GLOBAL
    unit: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    frequency: Mapped[str] = mapped_column(String(1), nullable=False)  # D | M | Q | A
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    source_key: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="macro")


class IndicatorObservation(Base):
    """One observation at the series' native frequency; period_date = start of the reference period."""
    __tablename__ = "indicator_observations"
    __table_args__ = (UniqueConstraint("indicator_id", "period_date", name="uq_indicator_observation"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    indicator_id: Mapped[str] = mapped_column(String(40), ForeignKey("indicators.id"), index=True, nullable=False)
    period_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )


class IndicatorSnapshot(Base):
    """What the platform knew about an indicator on as_of_date: latest value,
    90-day direction, 1y-ago and EU comparators, staleness. One row per
    indicator per run day (re-runs on the same day replace it)."""
    __tablename__ = "indicator_snapshots"
    __table_args__ = (UniqueConstraint("indicator_id", "as_of_date", name="uq_indicator_snapshot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    indicator_id: Mapped[str] = mapped_column(String(40), ForeignKey("indicators.id"), index=True, nullable=False)
    as_of_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    obs_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    value_90d_prior: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction_90d: Mapped[str] = mapped_column(String(10), nullable=False)  # rising | falling | stable
    value_1y: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_eu: Mapped[float | None] = mapped_column(Float, nullable=True)
    staleness_d: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)


class CryptoMarketSnapshot(Base):
    """Daily market-cap / volume / supply snapshot per coin (CoinGecko)."""
    __tablename__ = "crypto_market_snapshots"
    __table_args__ = (UniqueConstraint("instrument_id", "date", name="uq_crypto_snapshot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[str] = mapped_column(String(36), ForeignKey("instruments.id"), index=True, nullable=False)
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    circulating_supply: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FinancialFact(Base):
    """One fiscal year of normalized fundamentals for an equity."""
    __tablename__ = "financial_facts"
    __table_args__ = (UniqueConstraint("instrument_id", "fiscal_year", name="uq_financial_fact_instrument_year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[str] = mapped_column(String(36), ForeignKey("instruments.id"), index=True, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    revenue: Mapped[float] = mapped_column(Float, nullable=False)
    gross_profit: Mapped[float] = mapped_column(Float, nullable=False)
    operating_income: Mapped[float] = mapped_column(Float, nullable=False)
    net_income: Mapped[float] = mapped_column(Float, nullable=False)
    ebitda: Mapped[float] = mapped_column(Float, nullable=False)
    free_cash_flow: Mapped[float] = mapped_column(Float, nullable=False)
    total_assets: Mapped[float] = mapped_column(Float, nullable=False)
    total_equity: Mapped[float] = mapped_column(Float, nullable=False)
    total_debt: Mapped[float] = mapped_column(Float, nullable=False)
    current_assets: Mapped[float] = mapped_column(Float, nullable=False)
    current_liabilities: Mapped[float] = mapped_column(Float, nullable=False)
    interest_expense: Mapped[float] = mapped_column(Float, nullable=False)
    shares_diluted: Mapped[float] = mapped_column(Float, nullable=False)
    eps: Mapped[float] = mapped_column(Float, nullable=False)
    published_at: Mapped[datetime.date] = mapped_column(Date, nullable=False)

    instrument: Mapped["Instrument"] = relationship(back_populates="financial_facts")


class MacroObservation(Base):
    """One monthly macro data point (policy rate, 10Y yield, CPI YoY, a
    volatility index)."""
    __tablename__ = "macro_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime.date] = mapped_column(Date, unique=True, nullable=False, index=True)
    policy_rate: Mapped[float] = mapped_column(Float, nullable=False)
    yield_10y: Mapped[float] = mapped_column(Float, nullable=False)
    cpi_yoy: Mapped[float] = mapped_column(Float, nullable=False)
    vix: Mapped[float] = mapped_column(Float, nullable=False)


class ModelVersion(Base):
    """Registry of every trained forecasting/scoring model (forecasting/).
    status: approved (beats its baseline out of sample, predictions served) |
            rejected (did not beat the baseline, predictions not served) | retired."""
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("model_name", "version", name="uq_model_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(40), nullable=False, index=True)  # volatility | regime | quality | direction
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(80), nullable=False)
    trained_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    data_start: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    data_end: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")    # out-of-sample, model
    baseline_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")   # out-of-sample, baseline
    params_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")     # fitted parameters / config
    status: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    status_reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")


class ModelPrediction(Base):
    """One served number: e.g. target=vol_21d for subject ETE.AT as of a date."""
    __tablename__ = "model_predictions"
    __table_args__ = (UniqueConstraint("model_name", "subject", "target", "as_of_date", name="uq_model_prediction"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_version_id: Mapped[int] = mapped_column(Integer, ForeignKey("model_versions.id"), index=True, nullable=False)
    model_name: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(40), nullable=False, index=True)   # ticker, or "market:GR"
    target: Mapped[str] = mapped_column(String(40), nullable=False)
    as_of_date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class RiskAssessment(Base):
    """One completed risk questionnaire (append-only: the latest one is used, all are kept)."""
    __tablename__ = "risk_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    questionnaire_version: Mapped[int] = mapped_column(Integer, nullable=False)
    answers_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
    profile: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False, index=True)


class Proposal(Base):
    """A generated educational proposal, stored with everything it was built from
    (assessment, model versions, data dates) so it can be explained and audited later."""
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    risk_assessment_id: Mapped[int] = mapped_column(Integer, ForeignKey("risk_assessments.id"), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False, index=True)
    engine_version: Mapped[str] = mapped_column(String(20), nullable=False)
    proposal_json: Mapped[str] = mapped_column(Text, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    narrative_source: Mapped[str] = mapped_column(String(200), nullable=False)


class Portfolio(Base):
    """One virtual portfolio per customer (customer_id = the `sub` of the BFF token).
    Rows created before login existed have customer_id NULL and are never served."""
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
    cash: Mapped[float] = mapped_column(Float, nullable=False, default=10000.0)
    starting_cash: Mapped[float] = mapped_column(Float, nullable=False, default=10000.0)

    positions: Mapped[list["Position"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="portfolio", cascade="all, delete-orphan")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "ticker", name="uq_position_portfolio_ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, ForeignKey("portfolios.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_basis: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    portfolio: Mapped["Portfolio"] = relationship(back_populates="positions")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, ForeignKey("portfolios.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)  # buy | sell
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    executed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    portfolio: Mapped["Portfolio"] = relationship(back_populates="transactions")


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("portfolio_id", "ticker", name="uq_watchlist_portfolio_ticker"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, ForeignKey("portfolios.id"), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)


class ChatInteraction(Base):
    """One row per /chat turn -- the LLM analogue of PipelineRun below. Stores
    the actual question/response (so conversations are auditable/reviewable)
    plus health fields (provider, latency, status) that the monitoring
    dashboard reads directly, the same way it reads pipeline_runs."""
    __tablename__ = "chat_interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), index=True
    )
    customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_reply: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # anthropic | selfhosted
    agents_used: Mapped[str] = mapped_column(String(200), nullable=False, default="")  # comma-separated
    actions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # ok | error
    detail: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class PipelineRun(Base):
    """One row per data-ingestion pipeline invocation (see
    scripts/run_ingestion_scheduler.py) -- the monitoring dashboard reads
    this table directly."""
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # ok | partial | skipped | error
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    finished_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    rows_affected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detail: Mapped[str] = mapped_column(String(500), nullable=False, default="")
