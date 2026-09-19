from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from .config import settings
from .db import init_db
from .routers import compare, financials, instruments, portfolio, scores, simulation


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

app.include_router(instruments.router)
app.include_router(scores.router)
app.include_router(financials.router)
app.include_router(compare.router)
app.include_router(portfolio.router)
app.include_router(simulation.router)


@app.get("/health")
def health():
    return {"status": "ok"}
