from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import repo, schemas
from ..auth import Principal, require
from ..config import settings
from ..db import get_db
from ..services import coach_answers, llm
from ..services.agents import orchestrator

router = APIRouter(prefix="/chat", tags=["chat"])

BUDGET_MESSAGE = {
    "en": "You've used today's AI chat allowance. The lessons in the pop-ups still work, and the chat is back tomorrow.",
    "el": "Έφτασες το σημερινό όριο της συνομιλίας με την AI. Τα μαθήματα στα αναδυόμενα μηνύματα λειτουργούν κανονικά και η συνομιλία επιστρέφει αύριο.",
}


@router.post("", response_model=schemas.ChatResponse)
def chat(payload: schemas.ChatRequest, db: Session = Depends(get_db), principal: Principal = Depends(require("chat"))):
    history = [{"role": m.role, "content": m.content} for m in payload.history]
    started = time.monotonic()
    if len(payload.message) > settings.llm_max_message_chars:
        raise HTTPException(422, f"Please keep questions under {settings.llm_max_message_chars} characters")
    # common questions get a fixed-wording answer with real numbers: instant, no tokens, no budget used
    fixed = coach_answers.answer(db, principal.subject, payload.message, payload.lang)
    if fixed is not None:
        repo.record_chat_interaction(
            db, customer_id=principal.subject, user_message=payload.message, assistant_reply=fixed["reply"],
            provider="rules", agents_used=[f"rules:{fixed['intent']}"], actions_json=json.dumps(fixed["actions"]),
            status="ok", detail="", latency_ms=(time.monotonic() - started) * 1000, tokens_used=0,
        )
        return {"reply": fixed["reply"], "actions": fixed["actions"], "source": "rules", "lesson": fixed["lesson"]}
    if payload.provider and payload.provider not in {p["id"] for p in llm.available()}:
        raise HTTPException(422, f"Unknown or unconfigured model provider '{payload.provider}'")
    budget = settings.llm_daily_token_budget
    if budget > 0 and repo.tokens_used_today(db, principal.subject) >= budget:
        raise HTTPException(429, BUDGET_MESSAGE.get(payload.lang, BUDGET_MESSAGE["en"]))
    provider = payload.provider or settings.llm_provider
    with llm.count_usage() as usage:
        try:
            with llm.use(provider):
                reply, actions, agents_used = orchestrator.run_chat(payload.message, history, lang=payload.lang)
        except Exception as e:
            repo.record_chat_interaction(
                db, customer_id=principal.subject, user_message=payload.message, assistant_reply="", provider=provider,
                agents_used=[], actions_json="[]", status="error", detail=str(e),
                latency_ms=(time.monotonic() - started) * 1000, tokens_used=usage["total"],
            )
            raise HTTPException(status_code=502, detail=f"AI assistant unavailable: {e}")

    repo.record_chat_interaction(
        db, customer_id=principal.subject, user_message=payload.message, assistant_reply=reply, provider=provider,
        agents_used=sorted(set(agents_used)), actions_json=json.dumps(actions), status="ok", detail="",
        latency_ms=(time.monotonic() - started) * 1000, tokens_used=usage["total"],
    )
    return {"reply": reply, "actions": actions, "source": "ai"}
