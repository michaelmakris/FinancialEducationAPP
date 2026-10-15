"""Tsimp, the mosquito coach: nudges and lessons (services/coach.py, coach_content.py)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import Principal, require
from ..db import get_db
from ..services import coach, coach_content

router = APIRouter(prefix="/v1/coach", tags=["coach"])
Lang = Literal["el", "en"]


class PreTradeIn(BaseModel):
    side: Literal["buy", "sell"]
    ticker: str
    qty: float = Field(gt=0)
    lang: Lang = "en"


@router.post("/pre-trade")
def pre_trade(body: PreTradeIn, db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:read"))):
    """What Tsimp would say before this trade (nothing is traded). Empty list = nothing to say."""
    return coach.pre_trade(db, principal.subject, body.side, body.ticker, body.qty, body.lang)


@router.get("/events")
def events(lang: Lang = "en", db: Session = Depends(get_db), principal: Principal = Depends(require("portfolio:read"))):
    """Nudges about the portfolio as it is now (ids are stable per day: show each once)."""
    return coach.events(db, principal.subject, lang)


@router.get("/learn/{page}", dependencies=[Depends(require("market:read"))])
def learn(page: str, lang: Lang = "en"):
    note = coach.page_note(page, lang)
    if note is None:
        raise HTTPException(404, "No note for this page")
    return note


@router.get("/tip", dependencies=[Depends(require("market:read"))])
def tip(lang: Lang = "en"):
    return coach.daily_tip(lang)


@router.get("/lessons/{lesson_id}", dependencies=[Depends(require("market:read"))])
def lesson(lesson_id: str, lang: Lang = Query("en")):
    out = coach_content.lesson(lesson_id, lang)
    if out is None:
        raise HTTPException(404, "Unknown lesson")
    return out
