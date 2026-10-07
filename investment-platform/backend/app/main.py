from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from .config import settings
from .db import init_db
from . import monitoring
from .auth import require
from .routers import chat, compare, financials, instruments, macro, market, portfolio, predictions, scores, simulation


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="AI Investment Intelligence Platform (starter API)",
    description=(
        "Starter backend for the platform described in the original project plan. "
        "Serves the same analytics engine (ratios, factor scores, Monte Carlo simulation) "
        "used by the browser demo and the Python AI-analyst agent."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
monitoring.register_metrics()  # market_* data-freshness gauges on the same /metrics

# Every route needs a token signed by a trusted caller (the BFF) -- see app/auth.py.
# /health and /metrics stay open for container probes and Prometheus (internal network only).
_market = [Depends(require("market:read"))]
app.include_router(instruments.router, dependencies=_market)
app.include_router(scores.router, dependencies=_market)
app.include_router(financials.router, dependencies=_market)
app.include_router(compare.router, dependencies=_market)
app.include_router(simulation.router, dependencies=_market)
app.include_router(portfolio.router)  # per-route portfolio:read / portfolio:write
app.include_router(chat.router)       # chat scope, checked in the route
# real market data (Euronext Athens, crypto, Greek/EU macro) + its health
app.include_router(market.router, dependencies=_market)
app.include_router(macro.router, dependencies=_market)
app.include_router(predictions.router, dependencies=_market)
app.include_router(monitoring.router, dependencies=[Depends(require("ops:read"))])


@app.get("/health")
def health():
    return {"status": "ok"}
