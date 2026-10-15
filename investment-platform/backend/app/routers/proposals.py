"""
Risk profile and educational proposals for the caller's practice portfolio.

    GET  /v1/profile/questionnaire     questions (market:read)
    GET  /v1/profile                   latest risk profile (portfolio:read)
    POST /v1/profile                   answer the questionnaire (portfolio:write)
    POST /v1/proposals                 generate a proposal (portfolio:write)
    GET  /v1/proposals                 my proposals (portfolio:read)
    GET  /v1/proposals/latest | /{id}  one proposal (portfolio:read, own only)
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from prometheus_client import Counter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..auth import Principal, require
from ..db import get_db
from ..services import llm
from proposals import questionnaire, service

router = APIRouter(prefix="/v1", tags=["proposals"])
GENERATED = Counter("proposals_generated_total", "Educational proposals generated", ["narrative"])


class AnswersIn(BaseModel):
    answers: dict[str, str]


class ProposalIn(BaseModel):
    use_ai: bool = False
    provider: str | None = None  # model for the AI wording; default LLM_PROVIDER


def _narrative_kind(source: str) -> str:
    if source == "ai":
        return "ai"
    if "rejected" in source:
        return "ai_rejected"
    if "unavailable" in source:
        return "ai_unavailable"
    return "template"


@router.get("/llm/providers", dependencies=[Depends(require("market:read"))])
def llm_providers():
    """Models the app can use for the assistant and for AI wording; `default` is LLM_PROVIDER."""
    return llm.available()


@router.get("/profile/questionnaire", dependencies=[Depends(require("market:read"))])
def get_questionnaire():
    return questionnaire.public()


@router.get("/profile")
def get_profile(db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:read"))):
    ra = service.latest_assessment(db, principal.subject)
    if ra is None:
        raise HTTPException(404, "No risk profile yet. Answer the questionnaire first (POST /v1/profile).")
    return {"id": ra.id, "created_at": ra.created_at, "answers": json.loads(ra.answers_json), **json.loads(ra.result_json)}


@router.post("/profile", status_code=201)
def post_profile(body: AnswersIn, db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:write"))):
    try:
        ra = service.save_assessment(db, principal.subject, body.answers)
    except questionnaire.InvalidAnswers as e:
        raise HTTPException(422, str(e))
    return {"id": ra.id, "created_at": ra.created_at, **json.loads(ra.result_json)}


@router.post("/proposals", status_code=201)
def create_proposal(body: ProposalIn | None = None, db: Session = Depends(get_db),
                    principal: Principal = Depends(require("portfolio:write"))):
    provider = body.provider if body else None
    if provider and provider not in {p["id"] for p in llm.available()}:
        raise HTTPException(422, f"Unknown or unconfigured model provider '{provider}'")
    try:
        with llm.use(provider):
            prop = service.generate(db, principal.subject, use_ai=bool(body and body.use_ai))
    except service.NoProfile:
        raise HTTPException(409, "Answer the risk questionnaire first (POST /v1/profile).")
    except RuntimeError as e:  # e.g. risk estimates not computed yet
        raise HTTPException(503, f"Proposals are temporarily unavailable: {e}")
    GENERATED.labels(_narrative_kind(prop.narrative_source)).inc()
    return service.as_dict(prop)


@router.get("/proposals")
def list_proposals(db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:read"))):
    rows = db.execute(select(models.Proposal).where(models.Proposal.customer_id == principal.subject)
                      .order_by(models.Proposal.id.desc()).limit(50)).scalars()
    out = []
    for p in rows:
        d = json.loads(p.proposal_json)
        out.append({"id": p.id, "created_at": p.created_at, "profile": d["profile"], "profile_name": d["profile_name"],
                    "expected_volatility": d["expected_volatility"],
                    "allocation": {a["sleeve"]: a["weight_pct"] for a in d["allocation"]}})
    return out


def _own(db: Session, principal: Principal, proposal_id: int | None) -> models.Proposal:
    q = select(models.Proposal).where(models.Proposal.customer_id == principal.subject)
    q = q.where(models.Proposal.id == proposal_id) if proposal_id is not None else q.order_by(models.Proposal.id.desc()).limit(1)
    prop = db.execute(q).scalar_one_or_none()
    if prop is None:
        raise HTTPException(404, "No such proposal")
    return prop


@router.get("/proposals/latest")
def latest_proposal(db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:read"))):
    return service.as_dict(_own(db, principal, None))


@router.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: int, db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:read"))):
    return service.as_dict(_own(db, principal, proposal_id))
