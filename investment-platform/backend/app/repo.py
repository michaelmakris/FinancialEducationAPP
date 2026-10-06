from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import models


def load_instruments(db: Session) -> list[dict]:
    """Loads every instrument with its price series (ordered by date) and
    fundamentals (ordered by fiscal year) into the plain-dict shape the
    services layer (analytics/risk/factors/simulate) expects.

    Eagerly loads price_bars/financial_facts via selectinload rather than
    relying on lazy-loaded relationships -- lazy-loading is invisible on
    local SQLite (near-zero round-trip latency) but turns into an N+1 query
    storm against a real network database (one extra round trip per
    instrument per relationship), which is where this was actually caught:
    a 15-instrument universe took 5-7s per request against Postgres before
    this fix."""
    instruments = db.execute(
        select(models.Instrument)
        # The analytics services assume one shared, aligned date grid, which only
        # the simulated demo universe has. Real market data (data_source != simulated)
        # is served by its own endpoints instead.
        .where(models.Instrument.data_source == "simulated")
        .options(
            selectinload(models.Instrument.price_bars),
            selectinload(models.Instrument.financial_facts),
        )
    ).scalars().all()
    out = []
    for inst in instruments:
        bars = sorted(inst.price_bars, key=lambda b: b.date)
        facts = sorted(inst.financial_facts, key=lambda f: f.fiscal_year)
        out.append({
            "ticker": inst.ticker, "name": inst.name, "sector": inst.sector,
            "asset_type": inst.asset_type,
            "close": [b.close for b in bars],
            "fundamentals": [
                {
                    "fiscal_year": f.fiscal_year, "revenue": f.revenue, "gross_profit": f.gross_profit,
                    "operating_income": f.operating_income, "net_income": f.net_income, "ebitda": f.ebitda,
                    "free_cash_flow": f.free_cash_flow, "total_assets": f.total_assets,
                    "total_equity": f.total_equity, "total_debt": f.total_debt,
                    "current_assets": f.current_assets, "current_liabilities": f.current_liabilities,
                    "interest_expense": f.interest_expense, "shares_diluted": f.shares_diluted, "eps": f.eps,
                }
                for f in facts
            ],
        })
    return out


def record_chat_interaction(
    db: Session,
    *,
    customer_id: str | None = None,
    user_message: str,
    assistant_reply: str,
    provider: str,
    agents_used: list[str],
    actions_json: str,
    status: str,
    detail: str,
    latency_ms: float,
) -> None:
    db.add(models.ChatInteraction(
        customer_id=customer_id,
        user_message=user_message[:10000], assistant_reply=assistant_reply[:10000],
        provider=provider, agents_used=",".join(agents_used)[:200], actions_json=actions_json,
        status=status, detail=detail[:500], latency_ms=latency_ms,
    ))
    db.commit()


def get_or_create_portfolio(db: Session, customer_id: str) -> models.Portfolio:
    """Each customer (the `sub` of the caller's token) has their own virtual
    portfolio, created with the default starting cash on first use."""
    portfolio = db.execute(
        select(models.Portfolio).where(models.Portfolio.customer_id == customer_id)
    ).scalar_one_or_none()
    if portfolio is None:
        portfolio = models.Portfolio(customer_id=customer_id, cash=10000.0, starting_cash=10000.0)
        db.add(portfolio)
        db.commit()
        db.refresh(portfolio)
    return portfolio
