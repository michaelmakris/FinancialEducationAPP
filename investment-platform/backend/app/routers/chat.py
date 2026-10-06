from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import repo, schemas
from ..auth import Principal, require
from ..config import settings
from ..db import get_db
from ..services.agents import orchestrator

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=schemas.ChatResponse)
def chat(payload: schemas.ChatRequest, db: Session = Depends(get_db), principal: Principal = Depends(require("chat"))):
    history = [{"role": m.role, "content": m.content} for m in payload.history]
    started = time.monotonic()
    try:
        reply, actions, agents_used = orchestrator.run_chat(payload.message, history)
    except Exception as e:
        repo.record_chat_interaction(
            db, customer_id=principal.subject, user_message=payload.message, assistant_reply="", provider=settings.llm_provider,
            agents_used=[], actions_json="[]", status="error", detail=str(e),
            latency_ms=(time.monotonic() - started) * 1000,
        )
        raise HTTPException(status_code=502, detail=f"AI assistant unavailable: {e}")

    repo.record_chat_interaction(
        db, customer_id=principal.subject, user_message=payload.message, assistant_reply=reply, provider=settings.llm_provider,
        agents_used=sorted(set(agents_used)), actions_json=json.dumps(actions), status="ok", detail="",
        latency_ms=(time.monotonic() - started) * 1000,
    )
    return {"reply": reply, "actions": actions}
