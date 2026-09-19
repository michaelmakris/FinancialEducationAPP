from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import repo, schemas
from ..db import get_db
from ..services.factors import build_universe_metrics, compute_factor_scores

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=list[schemas.InstrumentOut])
def list_instruments(db: Session = Depends(get_db)):
    instruments = repo.load_instruments(db)
    universe = build_universe_metrics(instruments)
    scores = compute_factor_scores(universe)
    return [
        schemas.InstrumentOut(
            ticker=m["ticker"], name=m["name"], sector=m["sector"], asset_type=m["asset_type"],
            price=m["price"], overall_score=scores[m["ticker"]]["overall"],
            return_1m=m["market"].return_1m, return_12m=m["market"].return_12m,
            volatility=m["market"].volatility,
        )
        for m in universe.values()
    ]
