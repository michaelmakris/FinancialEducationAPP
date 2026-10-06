"""
Real market data: Euronext Athens equities, benchmarks and crypto (/v1).
Prices come from pipelines/ (see pipelines/SOURCES.md); returns use adjusted closes.
"""
from __future__ import annotations

import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import market_repo as mr
from .. import market_schemas as s
from ..db import get_db
from ..services import market as calc

router = APIRouter(prefix="/v1", tags=["market data"])

MAX_COMPARE = 10
_RET_KEYS = {"1w": "w1", "1m": "m1", "3m": "m3", "6m": "m6", "ytd": "ytd", "1y": "y1", "3y": "y3", "5y": "y5"}


def _instrument_or_404(db: Session, ticker: str):
    inst = mr.get_instrument(db, ticker)
    if inst is None:
        raise HTTPException(404, f"Unknown ticker '{ticker}'. See GET /v1/instruments for the available ones.")
    return inst


def _check_range(start: Optional[datetime.date], end: Optional[datetime.date]) -> None:
    if start and end and start > end:
        raise HTTPException(422, "start must be on or before end")


def _returns_model(r: dict) -> s.Returns:
    return s.Returns(**{_RET_KEYS[k]: v for k, v in r.items()})


def _overview(db: Session) -> list[dict]:
    """Summary row per real instrument; one query for prices, cached (MARKET_CACHE_TTL_S)."""
    def build():
        insts = mr.list_instruments(db)
        ids = [i.id for i in insts]
        since = datetime.date.today() - datetime.timedelta(days=400)
        series = mr.adj_close_series(db, ids, since=since)
        with_facts = set(mr.latest_fiscal_year_ends(db))
        rows = []
        for i in insts:
            ser = series.get(i.id, [])
            last = ser[-1] if ser else None
            rets = calc.period_returns(ser) if ser else {}
            prev = ser[-2][1] if len(ser) > 1 else None
            rows.append(dict(
                ticker=i.ticker, name=i.name, asset_type=i.asset_type, sector=i.sector, country=i.country,
                exchange=i.exchange, currency=i.currency, data_source=i.data_source,
                last_date=last[0] if last else None, last_close=last[1] if last else None,
                change_1d=(last[1] / prev - 1) if last and prev else None,
                return_1m=rets.get("1m"), return_1y=rets.get("1y"), has_fundamentals=i.id in with_facts,
            ))
        return rows

    return mr.cached(("overview",), build)


@router.get("/instruments", response_model=list[s.InstrumentSummary])
def list_instruments(
    asset_type: Optional[Literal["equity", "index", "etf", "crypto"]] = None,
    country: Optional[str] = Query(None, description="ISO-2, e.g. GR"),
    sector: Optional[str] = None,
    q: Optional[str] = Query(None, description="case-insensitive match on ticker or name"),
    db: Session = Depends(get_db),
):
    rows = _overview(db)
    if asset_type:
        rows = [r for r in rows if r["asset_type"] == asset_type]
    if country:
        rows = [r for r in rows if r["country"].upper() == country.upper()]
    if sector:
        rows = [r for r in rows if r["sector"].lower() == sector.lower()]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["ticker"].lower() or ql in r["name"].lower()]
    return rows


@router.get("/instruments/{ticker}", response_model=s.InstrumentDetail)
def instrument_detail(ticker: str, db: Session = Depends(get_db)):
    inst = _instrument_or_404(db, ticker)
    ser = mr.adj_close_series(db, [inst.id])[inst.id]
    summary = next((r for r in _overview(db) if r["ticker"] == inst.ticker), None) or {}
    crypto = mr.latest_crypto_snapshots(db).get(inst.id) if inst.asset_type == "crypto" else None
    return s.InstrumentDetail(
        **{**summary, "ticker": inst.ticker, "name": inst.name, "asset_type": inst.asset_type, "sector": inst.sector,
           "country": inst.country, "exchange": inst.exchange, "currency": inst.currency, "data_source": inst.data_source},
        lei=inst.lei, vendor_symbol=inst.vendor_symbol, first_date=ser[0][0] if ser else None,
        returns=_returns_model(calc.period_returns(ser)),
        volatility_1y=calc.annualized_volatility(ser), max_drawdown_1y=calc.max_drawdown(ser),
        crypto_market=s.CryptoMarket.model_validate(crypto, from_attributes=True) if crypto else None,
    )


@router.get("/instruments/{ticker}/prices", response_model=s.PriceSeries)
def prices(
    ticker: str,
    start: Optional[datetime.date] = None,
    end: Optional[datetime.date] = None,
    interval: Literal["daily", "weekly", "monthly"] = "daily",
    db: Session = Depends(get_db),
):
    _check_range(start, end)
    inst = _instrument_or_404(db, ticker)
    if start is None and end is None and interval == "daily":
        start = datetime.date.today() - datetime.timedelta(days=365)  # default: last year of dailies
    bars = calc.resample_bars(mr.bars(db, inst.id, start, end), interval)
    return s.PriceSeries(ticker=inst.ticker, currency=inst.currency, interval=interval, bars=bars)


@router.get("/instruments/{ticker}/performance", response_model=s.Performance)
def performance(ticker: str, db: Session = Depends(get_db)):
    inst = _instrument_or_404(db, ticker)
    ser = mr.adj_close_series(db, [inst.id])[inst.id]
    return s.Performance(
        ticker=inst.ticker, as_of=ser[-1][0] if ser else None, returns=_returns_model(calc.period_returns(ser)),
        volatility_1y=calc.annualized_volatility(ser), max_drawdown_1y=calc.max_drawdown(ser),
        max_drawdown_all=calc.max_drawdown(ser, days=None),
    )


@router.get("/compare", response_model=s.CompareResponse)
def compare(
    tickers: str = Query(..., description=f"comma-separated, 2-{MAX_COMPARE}, e.g. BTC-EUR,ETH-EUR,GD.AT"),
    start: Optional[datetime.date] = Query(None, description="default: 1 year before end"),
    end: Optional[datetime.date] = None,
    db: Session = Depends(get_db),
):
    wanted = list(dict.fromkeys(t.strip() for t in tickers.split(",") if t.strip()))
    if not 2 <= len(wanted) <= MAX_COMPARE:
        raise HTTPException(422, f"Give between 2 and {MAX_COMPARE} distinct tickers")
    end = end or datetime.date.today()
    start = start or end - datetime.timedelta(days=365)
    _check_range(start, end)
    found = mr.get_instruments(db, wanted)
    missing = [t for t in wanted if t.upper() not in found]
    if missing:
        raise HTTPException(404, f"Unknown ticker(s): {', '.join(missing)}")
    insts = [found[t.upper()] for t in wanted]
    # one bar before `start` so each series has a value to carry into the first day
    series = mr.adj_close_series(db, [i.id for i in insts], since=start - datetime.timedelta(days=10))
    by_ticker = {}
    for i in insts:
        ser = [(d, v) for d, v in series[i.id] if d <= end]
        pre = calc.value_on_or_before(ser, start)
        by_ticker[i.ticker] = ([(start, pre[1])] if pre and pre[0] < start else []) + [(d, v) for d, v in ser if d >= start]
    empty = [t for t, ser in by_ticker.items() if not ser]
    if empty:
        raise HTTPException(404, f"No prices in {start}..{end} for: {', '.join(empty)}")
    base_date, points = calc.rebase_compare(by_ticker)
    last = points[-1] if points else {}
    currencies = {i.ticker: i.currency for i in insts}
    note = "Rebased to 100 at base_date using adjusted closes; non-trading days carry the last close forward."
    if len(set(currencies.values())) > 1:
        note += " Returns are in each instrument's own currency (no FX conversion)."
    return s.CompareResponse(
        tickers=[i.ticker for i in insts], currencies=currencies, base_date=base_date, note=note,
        total_return={t: (last[t] / 100 - 1) if t in last else None for t in by_ticker}, points=points,
    )


@router.get("/instruments/{ticker}/fundamentals", response_model=s.Fundamentals)
def fundamentals(ticker: str, db: Session = Depends(get_db)):
    inst = _instrument_or_404(db, ticker)
    if inst.asset_type != "equity":
        raise HTTPException(422, f"{inst.ticker} is a {inst.asset_type}; fundamentals exist for equities only")
    years = calc.normalize_fundamentals(mr.reported_facts(db, inst.id))
    last = mr.latest_bars(db, [inst.id]).get(inst.id)
    return s.Fundamentals(
        ticker=inst.ticker, currency=inst.currency,
        source="ESEF annual reports via filings.xbrl.org (consolidated IFRS)" if years else
               "no ESEF filings loaded for this issuer",
        years=years, market_ratios=calc.market_ratios(years[0] if years else None, last.close if last else None),
        price_date=last.date if last else None,
    )


@router.get("/crypto/market", response_model=s.CryptoOverview)
def crypto_market(db: Session = Depends(get_db)):
    coins = [r for r in _overview(db) if r["asset_type"] == "crypto"]
    snaps = mr.latest_crypto_snapshots(db)
    insts = {i.id: i.ticker for i in mr.list_instruments(db) if i.asset_type == "crypto"}
    markets = {insts[iid]: s.CryptoMarket.model_validate(snap, from_attributes=True)
               for iid, snap in snaps.items() if iid in insts}
    as_of = mr.latest_snapshot_date(db)
    ind = mr.snapshots_on(db, as_of) if as_of else {}

    def snap(i):
        return s.IndicatorSnapshotOut.model_validate(ind[i], from_attributes=True) if i in ind else None

    coins.sort(key=lambda r: (markets.get(r["ticker"]).market_cap_rank or 10**6) if r["ticker"] in markets else 10**6)
    return s.CryptoOverview(as_of=as_of, fear_greed=snap("crypto_fear_greed"), defi_tvl=snap("defi_tvl"),
                            coins=coins, markets=markets)
