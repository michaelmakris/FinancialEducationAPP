from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, repo, schemas
from ..auth import Principal, require
from ..db import get_db
from ..services import costs, practice

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("", response_model=schemas.PortfolioOut)
def get_portfolio(db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:read"))):
    """Cash, positions at live prices (EUR), total and today's change."""
    portfolio = repo.get_or_create_portfolio(db, principal.subject)
    return practice.summary(db, portfolio)


@router.get("/intraday", response_model=schemas.PortfolioIntradayOut)
def get_intraday(db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:read"))):
    """Portfolio value through today (Athens time), replaying today's trades over 5-minute prices."""
    portfolio = repo.get_or_create_portfolio(db, principal.subject)
    return practice.intraday(db, portfolio)


@router.get("/transactions", response_model=list[schemas.TransactionOut])
def get_transactions(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
                     principal: Principal = Depends(require("portfolio:read"))):
    portfolio = repo.get_or_create_portfolio(db, principal.subject)
    return practice.transactions(db, portfolio, limit)


@router.get("/costs")
def get_costs(ticker: str, qty: float = Query(..., gt=0), db: Session = Depends(get_db),
              principal: Principal = Depends(require("portfolio:read"))):
    """What a trade would cost now (illustrative): with your broker profile, and the low/typical/high range."""
    portfolio = repo.get_or_create_portfolio(db, principal.subject)
    out = practice.trade_costs(db, portfolio, ticker, qty)
    out["profiles"] = costs.PROFILES
    return out


class CostProfileIn(BaseModel):
    profile: str


@router.post("/cost-profile", response_model=schemas.PortfolioOut)
def post_cost_profile(body: CostProfileIn, db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:write"))):
    """Choose the broker cost profile used for your next trades: none | low | typical | high."""
    portfolio = repo.get_or_create_portfolio(db, principal.subject)
    practice.set_cost_profile(db, portfolio, body.profile)
    return practice.summary(db, portfolio)


@router.post("/buy", response_model=schemas.PortfolioOut)
def buy(payload: schemas.TradeRequest, db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:write"))):
    """Buy at the latest price; the cost in EUR leaves virtual cash."""
    portfolio = repo.get_or_create_portfolio(db, principal.subject)
    practice.buy(db, portfolio, payload.ticker, payload.qty)
    return practice.summary(db, portfolio)


@router.post("/sell", response_model=schemas.PortfolioOut)
def sell(payload: schemas.TradeRequest, db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:write"))):
    """Sell at the latest price; the proceeds in EUR return to virtual cash."""
    portfolio = repo.get_or_create_portfolio(db, principal.subject)
    practice.sell(db, portfolio, payload.ticker, payload.qty)
    return practice.summary(db, portfolio)


@router.post("/reset", response_model=schemas.PortfolioOut)
def reset(db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:write"))):
    """Start again: no positions, no history, EUR 10,000 cash."""
    portfolio = repo.get_or_create_portfolio(db, principal.subject)
    practice.reset(db, portfolio)
    return practice.summary(db, portfolio)


@router.get("/watchlist")
def get_watchlist(db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:read"))):
    portfolio = repo.get_or_create_portfolio(db, principal.subject)
    items = db.execute(select(models.WatchlistItem).where(models.WatchlistItem.portfolio_id == portfolio.id)).scalars().all()
    return [i.ticker for i in items]


@router.post("/watchlist/{ticker}")
def add_watchlist(ticker: str, db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:write"))):
    ticker = ticker.upper()
    portfolio = repo.get_or_create_portfolio(db, principal.subject)
    existing = db.execute(
        select(models.WatchlistItem).where(models.WatchlistItem.portfolio_id == portfolio.id, models.WatchlistItem.ticker == ticker)
    ).scalar_one_or_none()
    if existing is None:
        db.add(models.WatchlistItem(portfolio_id=portfolio.id, ticker=ticker))
        db.commit()
    return {"ok": True}


@router.delete("/watchlist/{ticker}")
def remove_watchlist(ticker: str, db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:write"))):
    ticker = ticker.upper()
    portfolio = repo.get_or_create_portfolio(db, principal.subject)
    existing = db.execute(
        select(models.WatchlistItem).where(models.WatchlistItem.portfolio_id == portfolio.id, models.WatchlistItem.ticker == ticker)
    ).scalar_one_or_none()
    if existing is not None:
        db.delete(existing)
        db.commit()
    return {"ok": True}
