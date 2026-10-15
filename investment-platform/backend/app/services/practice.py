"""
The customer's practice portfolio on real prices.

Every customer starts with STARTING_CASH virtual euros. A buy takes the latest
price (services/quotes.py, converted to EUR) times the quantity, plus the transaction
costs of the customer's broker profile (services/costs.py), out of cash; a
sell puts the proceeds minus costs back and records the realised gain or loss against the
average cost. "Today" is the Athens calendar day: the intraday curve replays
today's trades over today's 5-minute prices, so a position bought at 11:00
only counts from 11:00. Reset empties the portfolio back to the starting cash.

Trading is allowed when an exchange is closed (at the last price): this is a
learning tool, not an order book.
"""
from __future__ import annotations

import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import market_repo as mr
from .. import models as M
from ..config import settings
from . import costs, quotes

STARTING_CASH = 10_000.0
TRADABLE_MARKETS = {"athens", "europe", "us", "etf", "crypto"}
EPS = 1e-9


def tradable_instrument(db: Session, ticker: str) -> M.Instrument:
    inst = mr.get_instrument(db, ticker)
    if inst is None or inst.market not in TRADABLE_MARKETS:
        raise HTTPException(404, f"'{ticker}' is not tradable. See GET /v1/instruments?market=athens|europe|us|etf|crypto")
    return inst


def quote_eur(db: Session, inst: M.Instrument) -> dict:
    q = quotes.intraday(db, inst)
    if q.last is None:
        raise HTTPException(503, f"No price available for {inst.ticker} right now")
    fx = quotes.fx_intraday(db, q.currency or inst.currency)
    rate = fx.last or 1.0
    return {"price_local": q.last, "currency": q.currency or inst.currency, "fx_rate": rate,
            "price_eur": q.last * rate, "prev_close_eur": (q.prev_close * (fx.prev_close or rate)) if q.prev_close else None,
            "as_of": q.as_of, "market_open": q.market_open, "live": q.live}


def _position(db: Session, portfolio: M.Portfolio, ticker: str) -> M.Position | None:
    return db.execute(select(M.Position).where(M.Position.portfolio_id == portfolio.id, M.Position.ticker == ticker)).scalar_one_or_none()


def cost_profile(portfolio: M.Portfolio) -> str:
    p = portfolio.cost_profile or settings.practice_default_costs
    return p if p in costs.PROFILES else "typical"


def set_cost_profile(db: Session, portfolio: M.Portfolio, profile: str) -> None:
    if profile not in costs.PROFILES:
        raise HTTPException(422, f"Unknown cost profile '{profile}'. Use one of: {', '.join(costs.PROFILES)}")
    portfolio.cost_profile = profile
    db.commit()


def trade_costs(db: Session, portfolio: M.Portfolio, ticker: str, qty: float) -> dict:
    """What a trade of `qty` would cost now: with the customer's profile, and the low/typical/high range."""
    inst = tradable_instrument(db, ticker)
    q = quote_eur(db, inst)
    amount = qty * q["price_eur"]
    profile = cost_profile(portfolio)
    return {"ticker": inst.ticker, "market": inst.market, "amount": amount, "profile": profile,
            "costs": costs.estimate(inst.market, amount, profile), "range": costs.ranges(inst.market, amount)}


def buy(db: Session, portfolio: M.Portfolio, ticker: str, qty: float) -> M.Transaction:
    inst = tradable_instrument(db, ticker)
    q = quote_eur(db, inst)
    amount = qty * q["price_eur"]
    fees = costs.estimate(inst.market, amount, cost_profile(portfolio))["total"]
    cost = amount + fees
    if cost > portfolio.cash + EPS:
        raise HTTPException(400, f"Not enough virtual cash: this costs EUR {cost:,.2f} including EUR {fees:,.2f} of costs, "
                                 f"you have EUR {portfolio.cash:,.2f}")
    pos = _position(db, portfolio, inst.ticker)
    if pos is None:
        pos = M.Position(portfolio_id=portfolio.id, ticker=inst.ticker, qty=0.0, cost_basis=0.0)
        db.add(pos)
    pos.qty += qty
    pos.cost_basis += cost          # costs are part of what the position cost you
    portfolio.cash -= cost
    tx = M.Transaction(portfolio_id=portfolio.id, ticker=inst.ticker, side="buy", qty=qty, price=q["price_eur"],
                       price_local=q["price_local"], currency=q["currency"], fx_rate=q["fx_rate"], fees=fees)
    db.add(tx)
    db.commit()
    return tx


def sell(db: Session, portfolio: M.Portfolio, ticker: str, qty: float) -> M.Transaction:
    inst = mr.get_instrument(db, ticker)
    pos = _position(db, portfolio, inst.ticker if inst else ticker.upper())
    if pos is None or qty > pos.qty + EPS:
        raise HTTPException(400, "You do not hold that many units to sell")
    if inst is None:
        raise HTTPException(404, f"Unknown ticker '{ticker}'")
    q = quote_eur(db, inst)
    qty = min(qty, pos.qty)
    avg = pos.cost_basis / pos.qty if pos.qty else 0.0
    amount = qty * q["price_eur"]
    fees = costs.estimate(inst.market, amount, cost_profile(portfolio))["total"]
    proceeds = amount - fees
    realized = proceeds - avg * qty   # after the costs of buying (in avg) and of selling
    pos.qty -= qty
    pos.cost_basis -= avg * qty
    if pos.qty <= EPS:
        db.delete(pos)
    portfolio.cash += proceeds
    tx = M.Transaction(portfolio_id=portfolio.id, ticker=inst.ticker, side="sell", qty=qty, price=q["price_eur"],
                       price_local=q["price_local"], currency=q["currency"], fx_rate=q["fx_rate"], realized_pnl=realized,
                       fees=fees)
    db.add(tx)
    db.commit()
    return tx


def reset(db: Session, portfolio: M.Portfolio) -> None:
    for p in list(portfolio.positions):
        db.delete(p)
    for t in list(portfolio.transactions):
        db.delete(t)
    portfolio.cash = portfolio.starting_cash = STARTING_CASH
    db.commit()


def _today_start() -> datetime.datetime:
    return quotes.athens_midnight_utc()


def _naive_utc(t: datetime.datetime) -> datetime.datetime:
    return t.astimezone(datetime.timezone.utc).replace(tzinfo=None) if t.tzinfo else t


def _aware(t: datetime.datetime) -> datetime.datetime:
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def todays_transactions(db: Session, portfolio: M.Portfolio) -> list[M.Transaction]:
    start = _naive_utc(_today_start())
    return sorted((t for t in portfolio.transactions if _naive_utc(t.executed_at) >= start), key=lambda t: t.executed_at)


def summary(db: Session, portfolio: M.Portfolio) -> dict:
    """Cash, positions at live prices, total, today's change (same replay as the intraday curve), realised gains."""
    db.refresh(portfolio)
    positions, holdings = [], 0.0
    insts = mr.get_instruments(db, [p.ticker for p in portfolio.positions])
    for p in sorted(portfolio.positions, key=lambda p: p.ticker):
        if p.qty <= EPS:
            continue
        inst = insts.get(p.ticker.upper())
        q = quote_eur(db, inst) if inst else None
        price = q["price_eur"] if q else None
        value = p.qty * price if price is not None else 0.0
        holdings += value
        positions.append(dict(
            ticker=p.ticker, name=inst.name if inst else p.ticker, market=inst.market if inst else "",
            currency=q["currency"] if q else "", qty=p.qty, avg_cost=p.cost_basis / p.qty, price=price or 0.0,
            price_local=q["price_local"] if q else None, value=value,
            unrealized_pnl=value - p.cost_basis, unrealized_pnl_pct=(value / p.cost_basis - 1) if p.cost_basis > 0 else 0.0,
            # the instrument's own move in its latest session
            day_change_pct=(q["price_eur"] / q["prev_close_eur"] - 1) if q and q["prev_close_eur"] else None,
            market_open=q["market_open"] if q else False, live=q["live"] if q else False,
            as_of=q["as_of"] if q else None,
        ))
    total = portfolio.cash + holdings
    start_value = intraday(db, portfolio)["start_value"]
    day_change = total - start_value
    return dict(
        cash=portfolio.cash, starting_cash=portfolio.starting_cash, holdings_value=holdings, total_value=total,
        total_pnl=total - portfolio.starting_cash,
        total_pnl_pct=(total / portfolio.starting_cash - 1) if portfolio.starting_cash > 0 else 0.0,
        realized_pnl=sum(t.realized_pnl or 0.0 for t in portfolio.transactions if t.side == "sell"),
        fees_paid=sum(t.fees or 0.0 for t in portfolio.transactions), cost_profile=cost_profile(portfolio),
        day_change=day_change, day_change_pct=(day_change / start_value) if start_value > 0 else 0.0,
        positions=positions,
    )


def intraday(db: Session, portfolio: M.Portfolio) -> dict:
    """Portfolio value through today: cash + units held at each moment x price at that moment (EUR)."""
    db.refresh(portfolio)
    day0 = _today_start()
    today = todays_transactions(db, portfolio)
    # holdings and cash at the start of the day = now, with today's trades undone
    qty0 = {p.ticker: p.qty for p in portfolio.positions if p.qty > EPS}
    cash0 = portfolio.cash
    for t in today:
        sign = 1 if t.side == "buy" else -1
        qty0[t.ticker] = qty0.get(t.ticker, 0.0) - sign * t.qty
        cash0 -= _cash_flow(t)
    tickers = sorted(k for k in set(qty0) | {t.ticker for t in today})
    insts = mr.get_instruments(db, tickers)
    series, fxs = {}, {}
    for tk in tickers:
        inst = insts.get(tk.upper())
        if inst is None:
            continue
        q = quotes.intraday(db, inst)
        cur = q.currency or inst.currency
        if cur not in fxs:
            fxs[cur] = quotes.fx_intraday(db, cur)
        series[tk] = (q, cur)
    stamps = {day0}
    for q, _ in series.values():
        stamps.update(t for t, _ in q.points if t >= day0)
    stamps.update(_aware(t.executed_at) for t in today)
    stamps.add(datetime.datetime.now(datetime.timezone.utc))
    points = []
    for ts in sorted(stamps):
        cash, qty = cash0, dict(qty0)
        for t in today:
            if _aware(t.executed_at) <= ts:
                sign = 1 if t.side == "buy" else -1
                qty[t.ticker] = qty.get(t.ticker, 0.0) + sign * t.qty
                cash += _cash_flow(t)
        value = cash
        for tk, n in qty.items():
            if n <= EPS or tk not in series:
                continue
            q, cur = series[tk]
            fx = fxs[cur]
            px = quotes.price_at(q.points, ts, q.prev_close)
            rate = quotes.price_at(fx.points, ts, fx.prev_close) or 1.0
            if px is not None:
                value += n * px * rate
        points.append({"t": ts, "value": round(value, 2), "cash": round(cash, 2)})
    start_value = points[0]["value"] if points else portfolio.cash
    return {"date": day0.astimezone(quotes.ATHENS).date(), "start_value": start_value,
            "points": points, "trades": [_tx_out(t) for t in today]}


def _cash_flow(t: M.Transaction) -> float:
    """Cash in (+) or out (-) of one trade, costs included."""
    gross = t.qty * t.price
    return -(gross + (t.fees or 0.0)) if t.side == "buy" else gross - (t.fees or 0.0)


def _tx_out(t: M.Transaction) -> dict:
    return dict(id=t.id, ticker=t.ticker, side=t.side, qty=t.qty, price=t.price, price_local=t.price_local,
                currency=t.currency, fx_rate=t.fx_rate, amount=t.qty * t.price, fees=t.fees or 0.0,
                realized_pnl=t.realized_pnl, executed_at=_aware(t.executed_at))


def transactions(db: Session, portfolio: M.Portfolio, limit: int = 100) -> list[dict]:
    rows = sorted(portfolio.transactions, key=lambda t: t.executed_at, reverse=True)[:limit]
    return [_tx_out(t) for t in rows]
