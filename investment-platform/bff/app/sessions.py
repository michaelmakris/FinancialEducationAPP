"""Server-side sessions: create, resolve from the cookie, revoke; plus the CSRF
and audit helpers the routes share."""
from __future__ import annotations

import datetime

from fastapi import Depends, HTTPException, Request, Response
from prometheus_client import Counter
from sqlalchemy import select, update
from sqlalchemy.orm import Session as DB

from . import security
from .config import settings
from .db import get_db
from .models import AuthEvent, Customer, Session, utcnow

AUTH_EVENTS = Counter("bff_auth_events_total", "Security events by type", ["event"])
_TOUCH_EVERY = datetime.timedelta(seconds=60)  # don't write last_seen_at on every request


def audit(db: DB, request: Request, event: str, customer_id: str | None = None, email: str = "", detail: str = "") -> None:
    db.add(AuthEvent(customer_id=customer_id, email=email[:254], event=event, ip=security.client_ip(request),
                     user_agent=request.headers.get("user-agent", "")[:300], detail=detail[:2000]))
    AUTH_EVENTS.labels(event).inc()


def create_session(db: DB, customer: Customer, request: Request, response: Response) -> Session:
    raw = security.new_token()
    now = utcnow()
    sess = Session(
        id=security.sha256_hex(raw), customer_id=customer.id, csrf_token=security.new_token(),
        created_at=now, last_seen_at=now, expires_at=now + datetime.timedelta(hours=settings.session_absolute_hours),
        ip=security.client_ip(request), user_agent=request.headers.get("user-agent", "")[:300],
    )
    db.add(sess)
    response.set_cookie(
        settings.cookie_name, raw, max_age=settings.session_absolute_hours * 3600, path="/",
        httponly=True, secure=settings.cookie_secure, samesite="strict",
    )
    return sess


def clear_cookie(response: Response) -> None:
    response.delete_cookie(settings.cookie_name, path="/", httponly=True, secure=settings.cookie_secure, samesite="strict")


def revoke_all(db: DB, customer_id: str, except_id: str | None = None) -> int:
    q = update(Session).where(Session.customer_id == customer_id, Session.revoked_at.is_(None))
    if except_id:
        q = q.where(Session.id != except_id)
    return db.execute(q.values(revoked_at=utcnow())).rowcount or 0


class Current:
    def __init__(self, session: Session, customer: Customer):
        self.session, self.customer = session, customer


def _resolve(request: Request, db: DB) -> Current | None:
    raw = request.cookies.get(settings.cookie_name)
    if not raw or len(raw) > 200:
        return None
    sess = db.get(Session, security.sha256_hex(raw))
    if sess is None or sess.revoked_at is not None:
        return None
    now = utcnow()
    if now >= sess.expires_at or now - sess.last_seen_at > datetime.timedelta(minutes=settings.session_idle_minutes):
        sess.revoked_at = now
        db.commit()
        return None
    customer = db.get(Customer, sess.customer_id)
    if customer is None or customer.status != "active":
        return None
    if now - sess.last_seen_at > _TOUCH_EVERY:
        sess.last_seen_at = now
        db.commit()
    return Current(sess, customer)


def current(request: Request, db: DB = Depends(get_db)) -> Current:
    """Dependency: the logged-in customer, or 401."""
    cur = _resolve(request, db)
    if cur is None:
        raise HTTPException(401, "Not signed in")
    return cur


def current_with_csrf(request: Request, cur: Current = Depends(current)) -> Current:
    """Dependency for state-changing calls: also require the session's CSRF token
    in X-CSRF-Token (a cross-site page can send the cookie but cannot read the token)."""
    if not security.same(request.headers.get("x-csrf-token"), cur.session.csrf_token):
        raise HTTPException(403, "Missing or invalid CSRF token")
    return cur


def active_sessions(db: DB, customer_id: str) -> list[Session]:
    now = utcnow()
    idle = datetime.timedelta(minutes=settings.session_idle_minutes)
    rows = db.execute(select(Session).where(Session.customer_id == customer_id, Session.revoked_at.is_(None),
                                            Session.expires_at > now).order_by(Session.created_at.desc())).scalars()
    return [s for s in rows if now - s.last_seen_at <= idle]
