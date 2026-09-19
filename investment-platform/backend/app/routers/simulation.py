from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import repo, schemas
from ..db import get_db
from ..services.simulate import run_monte_carlo_simulation

router = APIRouter(prefix="/simulate", tags=["simulation"])


@router.post("", response_model=schemas.SimulationResponse)
def simulate(payload: schemas.SimulationRequest, db: Session = Depends(get_db)):
    instruments = repo.load_instruments(db)
    by_ticker = {i["ticker"]: i for i in instruments}
    result = run_monte_carlo_simulation(
        by_ticker, amount=payload.amount,
        weights={"equities": payload.equities_pct, "bonds": payload.bonds_pct,
                 "crypto": payload.crypto_pct, "cash": payload.cash_pct},
        horizon_months=payload.horizon_months,
    )
    return schemas.SimulationResponse(
        amount=result.amount, horizon_months=result.horizon_months, weights=result.weights,
        median=result.median, p10=result.p10, p25=result.p25, p75=result.p75, p90=result.p90,
        prob_loss=result.prob_loss, prob_gain_10=result.prob_gain_10, assumptions=result.assumptions,
    )
