"""
Model outputs (/v1/predictions) from forecasting/. Only approved model versions
are served; anything else is reported as not served, with the reason, so callers
(the app, the MCP server, the proposal engine) never show an unvalidated number.
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import market_repo as mr
from ..db import get_db
from forecasting import registry

router = APIRouter(prefix="/v1/predictions", tags=["predictions"])

DISCLAIMER = ("Model estimates for education. They describe risk and past behaviour; they are not "
              "forecasts you should trade on and not investment advice. See /v1/predictions/models for how each "
              "model was validated.")
_SUMMARY_DROP = {"per_asset_qlike"}


def _model_summary(mv) -> Optional[dict]:
    d = registry.as_dict(mv)
    if d is None:
        return None
    d["params"] = {k: v for k, v in d["params"].items() if k not in _SUMMARY_DROP}
    return d


def _pred(p) -> dict:
    return {"value": p.value, "as_of": p.as_of_date, "horizon_days": p.horizon_days, "details": json.loads(p.details_json)}


def _not_served(mv) -> dict:
    if mv is None:
        return {"status": "not_available", "reason": "model has not been trained yet"}
    return {"status": "not_served", "reason": mv.status_reason, "model_version": mv.version}


@router.get("/models")
def models(db: Session = Depends(get_db)):
    """Latest version of every model with its out-of-sample metrics and baseline."""
    return {"models": [_model_summary(mv) for mv in sorted(registry.latest_versions(db).values(), key=lambda m: m.model_name)],
            "disclaimer": DISCLAIMER}


@router.get("/instruments/{ticker}")
def instrument(ticker: str, db: Session = Depends(get_db)):
    inst = mr.get_instrument(db, ticker)
    if inst is None:
        raise HTTPException(404, f"Unknown ticker '{ticker}'. See GET /v1/instruments.")
    versions = registry.latest_versions(db)
    out: dict = {"ticker": inst.ticker, "disclaimer": DISCLAIMER, "models": {}}

    risk = {p.target: p for p in registry.latest_predictions(db, "volatility", inst.ticker)}
    vol_mv = versions.get("volatility")
    if risk:
        out["risk"] = {t: _pred(risk[t]) if t in risk else None for t in ("vol_21d_annualized", "p_loss_10pct_21d")}
    elif vol_mv is None or vol_mv.status != "approved":
        out["risk"] = _not_served(vol_mv)
    else:
        out["risk"] = {"status": "not_available", "reason": "not enough price history for this instrument"}

    q = registry.latest_predictions(db, "quality", inst.ticker)
    out["quality"] = _pred(q[0]) if q else (
        {"status": "not_available", "reason": "no annual-report data for this issuer"} if inst.asset_type == "equity"
        else {"status": "not_applicable", "reason": f"quality scores cover equities, not {inst.asset_type}"})

    d = registry.latest_predictions(db, "direction", inst.ticker)
    out["direction"] = _pred(d[0]) if d else _not_served(versions.get("direction"))

    for name in ("volatility", "quality", "direction"):
        mv = versions.get(name)
        out["models"][name] = {"version": mv.version, "status": mv.status, "trained_at": mv.trained_at} if mv else None
    return out


@router.get("/market")
def market(db: Session = Depends(get_db)):
    mv = registry.latest_versions(db).get("regime")
    rows = registry.latest_predictions(db, "regime", "market:GR")
    cond = registry.latest_predictions(db, "conditions", "market:GR")
    return {"regime": _pred(rows[0]) if rows else _not_served(mv),
            "model": {"version": mv.version, "status": mv.status, "trained_at": mv.trained_at} if mv else None,
            "current_conditions": _pred(cond[0]) if cond else {"status": "not_available", "reason": "Athens index history not loaded"},
            "disclaimer": DISCLAIMER}


@router.get("/quality")
def quality_ranking(peer_group: Optional[str] = None, db: Session = Depends(get_db)):
    rows = registry.latest_predictions(db, "quality")
    out = []
    for p in rows:
        det = json.loads(p.details_json)
        if peer_group and det.get("peer_group") != peer_group:
            continue
        out.append({"ticker": p.subject, "score": p.value, "peer_group": det.get("peer_group"),
                    "fiscal_year_end": det.get("fiscal_year_end"), "components": det.get("component_percentiles")})
    return {"as_of": rows[0].as_of_date if rows else None, "ranking": sorted(out, key=lambda r: -r["score"]),
            "disclaimer": DISCLAIMER}
