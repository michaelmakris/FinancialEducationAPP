"""
/bff/api/<path> -> API /<path>, for signed-in customers only.

The browser never talks to the API and never holds an API credential. For each
call the BFF checks the session (and CSRF token for writes), checks the path
against an allowlist for the customer's role, mints a short-lived token for
that customer and forwards the request. Only the body and content type come
back -- no upstream headers leak through.
"""
from __future__ import annotations

import re
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from prometheus_client import Counter, Histogram

from . import security
from .config import settings
from .sessions import Current, current

router = APIRouter(prefix="/bff/api", tags=["api proxy"])

UPSTREAM = Counter("bff_upstream_requests_total", "Proxied API calls", ["route", "status"])
UPSTREAM_LATENCY = Histogram("bff_upstream_latency_seconds", "API latency seen by the BFF", ["route"],
                             buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120))
DENIED = Counter("bff_proxy_denied_total", "Proxy calls refused before reaching the API", ["reason"])

_CUSTOMER_ROUTES = [
    r"v1/instruments(/[^/]+(/(prices|performance|fundamentals))?)?",
    r"v1/compare", r"v1/crypto/market",
    r"v1/macro/(indicators(/[^/]+(/series)?)?|snapshot)",
    r"instruments", r"scores(/[^/]+)?", r"financials(/[^/]+)?", r"compare", r"simulate",
    r"portfolio(/(buy|sell|reset|watchlist(/[^/]+)?))?",
    r"chat",
]
ROLE_ROUTES = {
    "customer": [re.compile(f"^{p}$") for p in _CUSTOMER_ROUTES],
    "staff": [re.compile(f"^{p}$") for p in _CUSTOMER_ROUTES + [r"v1/data-status"]],
}
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._^\-]+$")
_FORWARD_HEADERS = ("content-type", "accept")


def route_label(path: str) -> str:
    """Low-cardinality metric label: first two segments, ticker-like parts collapsed."""
    parts = path.split("/")
    return "/".join(parts[:2]) if parts[0] == "v1" else parts[0]


def _check_path(path: str, role: str) -> None:
    segments = path.split("/")
    if not path or any(s in ("", ".", "..") or not _SAFE_SEGMENT.match(s) for s in segments):
        DENIED.labels("bad_path").inc()
        raise HTTPException(400, "Invalid path")
    if not any(rx.match(path) for rx in ROLE_ROUTES.get(role, ROLE_ROUTES["customer"])):
        DENIED.labels("not_allowed").inc()
        raise HTTPException(404, "Not found")


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request, cur: Current = Depends(current)):
    if request.method != "GET" and not security.same(request.headers.get("x-csrf-token"), cur.session.csrf_token):
        DENIED.labels("csrf").inc()
        raise HTTPException(403, "Missing or invalid CSRF token")
    if settings.require_mfa and not cur.customer.mfa_enabled:
        DENIED.labels("mfa_enrollment").inc()
        raise HTTPException(403, "mfa_enrollment_required")
    _check_path(path, cur.customer.role)

    lifetime = settings.chat_token_lifetime_s if path == "chat" else settings.token_lifetime_s
    token = security.mint_api_token(cur.customer.id, cur.customer.role, lifetime)
    headers = {h: request.headers[h] for h in _FORWARD_HEADERS if h in request.headers}
    headers.update({"Authorization": f"Bearer {token}", "X-Request-ID": uuid.uuid4().hex})
    body = await request.body() if request.method in ("POST", "PUT", "PATCH", "DELETE") else None

    client: httpx.AsyncClient = request.app.state.http
    label = route_label(path)
    started = time.perf_counter()
    try:
        upstream = await client.request(request.method, f"{settings.api_base_url}/{path}",
                                        params=request.url.query or None, content=body, headers=headers)
    except httpx.HTTPError:
        UPSTREAM.labels(label, "unreachable").inc()
        raise HTTPException(502, "The service is temporarily unavailable")
    finally:
        UPSTREAM_LATENCY.labels(label).observe(time.perf_counter() - started)
    if upstream.status_code in (401, 403):
        # The API refused a token we just minted: a BFF/API key or clock problem, not the customer's fault.
        UPSTREAM.labels(label, "token_rejected").inc()
        return Response(b'{"detail":"The service is temporarily unavailable"}', status_code=502, media_type="application/json")
    UPSTREAM.labels(label, f"{upstream.status_code // 100}xx").inc()
    return Response(upstream.content, status_code=upstream.status_code,
                    media_type=upstream.headers.get("content-type", "application/json"))
