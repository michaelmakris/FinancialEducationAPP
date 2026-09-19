from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, repo, schemas
from ..db import get_db
from ..services.factors import build_universe_metrics

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _portfolio_out(db: Session, portfolio: models.Portfolio) -> schemas.PortfolioOut:
    instruments = repo.load_instruments(db)
    universe = build_universe_metrics(instruments)
    positions_out = []
    holdings_value = 0.0
    for p in portfolio.positions:
        if p.qty <= 0:
            continue
        price = universe[p.ticker]["price"] if p.ticker in universe else 0.0
        value = p.qty * price
        holdings_value += value
        avg_cost = p.cost_basis / p.qty if p.qty else 0.0
        positions_out.append(schemas.PositionOut(
            ticker=p.ticker, qty=p.qty, avg_cost=avg_cost, price=price, value=value,
            unrealized_pnl_pct=(value / p.cost_basis - 1) if p.cost_basis > 0 else 0.0,
        ))
    total_value = portfolio.cash + holdings_value
    return schemas.PortfolioOut(
        cash=portfolio.cash, starting_cash=portfolio.starting_cash, total_value=total_value,
        total_pnl_pct=(total_value / portfolio.starting_cash - 1) if portfolio.starting_cash > 0 else 0.0,
        positions=positions_out,
    )


@router.get("", response_model=schemas.PortfolioOut)
def get_portfolio(db: Session = Depends(get_db)):
    portfolio = repo.get_or_create_portfolio(db)
    return _portfolio_out(db, portfolio)


@router.post("/buy", response_model=schemas.PortfolioOut)
def buy(payload: schemas.TradeRequest, db: Session = Depends(get_db)):
    ticker = payload.ticker.upper()
    portfolio = repo.get_or_create_portfolio(db)
    instruments = repo.load_instruments(db)
    universe = build_universe_metrics(instruments)
    if ticker not in universe:
        raise HTTPException(status_code=404, detail=f"Unknown ticker '{ticker}'")
    price = universe[ticker]["price"]
    cost = payload.qty * price
    if cost > portfolio.cash:
        raise HTTPException(status_code=400, detail="Insufficient virtual cash for this buy")

    position = db.execute(
        select(models.Position).where(models.Position.portfolio_id == portfolio.id, models.Position.ticker == ticker)
    ).scalar_one_or_none()
    if position is None:
        position = models.Position(portfolio_id=portfolio.id, ticker=ticker, qty=0.0, cost_basis=0.0)
        db.add(position)
    position.qty += payload.qty
    position.cost_basis += cost
    portfolio.cash -= cost
    db.add(models.Transaction(portfolio_id=portfolio.id, ticker=ticker, side="buy", qty=payload.qty, price=price))
    db.commit()
    db.refresh(portfolio)
    return _portfolio_out(db, portfolio)


@router.post("/sell", response_model=schemas.PortfolioOut)
def sell(payload: schemas.TradeRequest, db: Session = Depends(get_db)):
    ticker = payload.ticker.upper()
    portfolio = repo.get_or_create_portfolio(db)
    instruments = repo.load_instruments(db)
    universe = build_universe_metrics(instruments)
    if ticker not in universe:
        raise HTTPException(status_code=404, detail=f"Unknown ticker '{ticker}'")
    position = db.execute(
        select(models.Position).where(models.Position.portfolio_id == portfolio.id, models.Position.ticker == ticker)
    ).scalar_one_or_none()
    if position is None or payload.qty > position.qty:
        raise HTTPException(status_code=400, detail="Not enough shares held to sell that quantity")

    price = universe[ticker]["price"]
    avg_cost = position.cost_basis / position.qty if position.qty else 0.0
    proceeds = payload.qty * price
    position.qty -= payload.qty
    position.cost_basis -= avg_cost * payload.qty
    portfolio.cash += proceeds
    db.add(models.Transaction(portfolio_id=portfolio.id, ticker=ticker, side="sell", qty=payload.qty, price=price))
    db.commit()
    db.refresh(portfolio)
    return _portfolio_out(db, portfolio)


@router.post("/reset", response_model=schemas.PortfolioOut)
def reset(db: Session = Depends(get_db)):
    portfolio = repo.get_or_create_portfolio(db)
    for p in list(portfolio.positions):
        db.delete(p)
    for t in list(portfolio.transactions):
        db.delete(t)
    portfolio.cash = portfolio.starting_cash
    db.commit()
    db.refresh(portfolio)
    return _portfolio_out(db, portfolio)


@router.get("/watchlist")
def get_watchlist(db: Session = Depends(get_db)):
    portfolio = repo.get_or_create_portfolio(db)
    items = db.execute(select(models.WatchlistItem).where(models.WatchlistItem.portfolio_id == portfolio.id)).scalars().all()
    return [i.ticker for i in items]


@router.post("/watchlist/{ticker}")
def add_watchlist(ticker: str, db: Session = Depends(get_db)):
    ticker = ticker.upper()
    portfolio = repo.get_or_create_portfolio(db)
    existing = db.execute(
        select(models.WatchlistItem).where(models.WatchlistItem.portfolio_id == portfolio.id, models.WatchlistItem.ticker == ticker)
    ).scalar_one_or_none()
    if existing is None:
        db.add(models.WatchlistItem(portfolio_id=portfolio.id, ticker=ticker))
        db.commit()
    return {"ok": True}


@router.delete("/watchlist/{ticker}")
def remove_watchlist(ticker: str, db: Session = Depends(get_db)):
    ticker = ticker.upper()
    portfolio = repo.get_or_create_portfolio(db)
    existing = db.execute(
        select(models.WatchlistItem).where(models.WatchlistItem.portfolio_id == portfolio.id, models.WatchlistItem.ticker == ticker)
    ).scalar_one_or_none()
    if existing is not None:
        db.delete(existing)
        db.commit()
    return {"ok": True}
