from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import repo, schemas
from ..db import get_db
from ..services.factors import build_universe_metrics, compute_factor_scores

router = APIRouter(prefix="/compare", tags=["compare"])


@router.post("")
def compare(payload: schemas.CompareRequest, db: Session = Depends(get_db)):
    tickers = [t.upper() for t in payload.tickers]
    instruments = repo.load_instruments(db)
    universe = build_universe_metrics(instruments)
    missing = [t for t in tickers if t not in universe]
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown ticker(s): {', '.join(missing)}")
    scores = compute_factor_scores(universe)
    out = {}
    for t in tickers:
        m = universe[t]
        out[t] = {
            "overall_score": scores[t]["overall"], "price": m["price"], "sector": m["sector"],
            "valuation": m["valuation"], "quality": m["quality"], "growth": m["growth"],
            "balance_sheet": m["balance_sheet"], "market": asdict(m["market"]),
        }
    return out
