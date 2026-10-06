"""
Backend-for-frontend: the only service the browser talks to.

    browser --(session cookie + CSRF header)--> BFF /bff/auth/*   login, register, sessions
                                                    /bff/api/*    --(signed 60 s token)--> API

Run:  uvicorn app.main:app --port 8080     (from bff/, after `python -m scripts.generate_keys`)
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from . import access_keys, auth_routes, proxy, security
from .config import settings
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    security._signing_key()  # fail at startup, not on the first customer request, if a key is missing
    security._data_key()
    if not hasattr(app.state, "http"):
        app.state.http = httpx.AsyncClient(timeout=settings.upstream_timeout_s)
    yield
    await app.state.http.aclose()


_docs = os.environ.get("BFF_DOCS", "false").lower() == "true"
app = FastAPI(title="Financial Education BFF", lifespan=lifespan,
              docs_url="/bff/docs" if _docs else None, redoc_url=None, openapi_url="/bff/openapi.json" if _docs else None)

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def origin_and_headers(request: Request, call_next):
    # Defence in depth on top of SameSite=Strict + CSRF tokens: a browser always sends
    # Origin on cross-site writes, so refuse any write whose Origin is not ours.
    origin = request.headers.get("origin")
    if request.method in _UNSAFE and origin and origin not in settings.allowed_origins:
        return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/bff/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(auth_routes.router)
app.include_router(access_keys.router)
app.include_router(proxy.router)
Instrumentator(excluded_handlers=["/metrics", "/bff/health"]).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


@app.get("/bff/health")
def health():
    return {"status": "ok"}
