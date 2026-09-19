from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import repo, schemas
from ..db import get_db
from ..services.factors import build_universe_metrics

router = APIRouter(prefix="/financials", tags=["financials"])


@router.get("/{ticker}", response_model=schemas.FinancialsOut)
def get_financials(ticker: str, db: Session = Depends(get_db)):
    ticker = ticker.upper()
    instruments = repo.load_instruments(db)
    universe = build_universe_metrics(instruments)
    if ticker not in universe:
        raise HTTPException(status_code=404, detail=f"Unknown ticker '{ticker}'")
    m = universe[ticker]
    return schemas.FinancialsOut(
        ticker=ticker, valuation=m["valuation"], quality=m["quality"], growth=m["growth"],
        balance_sheet=m["balance_sheet"], market=asdict(m["market"]),
    )
