from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import repo, schemas
from ..db import get_db
from ..services.factors import build_universe_metrics, compute_factor_scores

router = APIRouter(prefix="/scores", tags=["scores"])


@router.get("/{ticker}", response_model=schemas.ScoreOut)
def get_score(ticker: str, db: Session = Depends(get_db)):
    ticker = ticker.upper()
    instruments = repo.load_instruments(db)
    universe = build_universe_metrics(instruments)
    if ticker not in universe:
        raise HTTPException(status_code=404, detail=f"Unknown ticker '{ticker}'")
    scores = compute_factor_scores(universe)
    s = scores[ticker]
    breakdown = {k: [list(row) for row in v] for k, v in s["breakdown"].items()}
    return schemas.ScoreOut(ticker=ticker, overall=s["overall"], category_scores=s["category_scores"], breakdown=breakdown)
