from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
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

    price_bars: Mapped[list["PriceBar"]] = relationship(back_populates="instrument", cascade="all, delete-orphan")
    financial_facts: Mapped[list["FinancialFact"]] = relationship(back_populates="instrument", cascade="all, delete-orphan")


class PriceBar(Base):
    """One daily close price. Simplified vs. a full OHLCV schema -- see README
    'What's simplified vs. the full plan' for how to extend this."""
    __tablename__ = "price_bars"
    __table_args__ = (UniqueConstraint("instrument_id", "date", name="uq_price_bar_instrument_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[str] = mapped_column(String(36), ForeignKey("instruments.id"), index=True, nullable=False)
    date: Mapped[datetime.date] = mapped_column(Date, nullable=False, index=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)

    instrument: Mapped["Instrument"] = relationship(back_populates="price_bars")


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


class Portfolio(Base):
    """Single-user demo: one row. Add a user_id + auth before multi-tenant use."""
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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


class PipelineRun(Base):
    """One row per data-ingestion pipeline invocation (see
    scripts/run_ingestion_scheduler.py) -- the monitoring dashboard reads
    this table directly."""
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # ok | error
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False, index=True)
    finished_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    rows_affected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detail: Mapped[str] = mapped_column(String(500), nullable=False, default="")
