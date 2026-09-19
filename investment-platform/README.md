# AI Investment Intelligence Platform -- backend starter

This is a starter implementation of the backend described in the original
project plan: a FastAPI service with the same analytics engine (ratios, risk
statistics, cross-sectional factor scoring, Monte Carlo portfolio simulation)
that powers the browser demo, plus data-ingestion pipeline skeletons and a
real Python AI-analyst agent.

**Read this before you rely on anything here:** the original plan describes
a multi-month, multi-engineer build (data pipelines against four external
vendors, a full production database, a deployed API, a frontend, an AI
agent). This package is a working, tested *starting point* for that --
not the finished platform. See "What's simplified vs. the full plan" below
for exactly where the gaps are.

## Relationship to the browser demo

`investment-platform-demo.jsx` (one directory up, and mirrored into
`frontend/src/App.jsx` so it can actually be run -- see `frontend/` below) is
a self-contained interactive prototype that runs entirely in the browser on
simulated data generated in JavaScript. This backend is a second, independent
implementation of the *same* formulas in Python (see
`backend/app/services/`), backed by a real database, so you have a working
example of both "instant browser demo" and "real API you can build on."
They use separately-generated random data, so exact numbers won't match
between the two -- the formulas and behavior do.

## Running the frontend demo

The demo component has no build tooling of its own, so `frontend/` is a
minimal Vite + React scaffold that hosts it:

```bash
cd frontend
npm install
npm run dev
```

Then open the URL Vite prints (typically http://localhost:5173). The app
persists your watchlist and virtual portfolio to `localStorage` so they
survive a page reload, standing in for the `window.storage` API the
component was originally authored against.

## Repository layout

```
investment-platform/
├── backend/
│   ├── app/
│   │   ├── main.py           FastAPI app
│   │   ├── models.py         SQLAlchemy ORM models
│   │   ├── schemas.py        Pydantic request/response schemas
│   │   ├── db.py, config.py, repo.py
│   │   ├── services/         analytics.py, risk.py, factors.py, simulate.py
│   │   └── routers/          instruments, scores, financials, compare, portfolio, simulation
│   ├── agent/
│   │   └── chat_agent.py     real AI-analyst CLI (Claude tool-use against this API)
│   ├── pipelines/            sec_ingest.py, prices_ingest.py, crypto_ingest.py, macro_ingest.py
│   ├── scripts/
│   │   ├── generate_dataset.py   the same simulated-data generator as the demo
│   │   └── seed_demo_data.py     loads it into the database
│   ├── alembic/               schema migrations
│   ├── tests/                 39 pytest tests -- all passing (see "What's been tested")
│   ├── requirements.txt
│   └── Dockerfile
├── infra/
│   └── docker-compose.yml    Postgres + backend
├── frontend/
│   └── src/App.jsx           the browser demo, hosted in a minimal Vite scaffold
└── .env.example
```

## Quickest possible start (SQLite, no Docker, no API keys)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m scripts.seed_demo_data
uvicorn app.main:app --reload
```

Then open http://localhost:8000/docs for interactive API docs, or try:

```bash
curl http://localhost:8000/instruments
curl http://localhost:8000/scores/NVDA
curl -X POST http://localhost:8000/simulate -H "Content-Type: application/json" \
  -d '{"amount":10000,"equities_pct":60,"bonds_pct":25,"crypto_pct":10,"cash_pct":5,"horizon_months":12}'
```

## Running with Postgres (Docker Compose)

```bash
cd infra
docker compose up --build
```

This starts Postgres, runs the Alembic migration, seeds the demo dataset,
and starts the API on port 8000 -- same endpoints as above.

## Running the tests

```bash
cd backend && source .venv/bin/activate
pytest -q
```

39 tests covering the risk/statistics formulas, fundamentals ratios, factor
scoring (including a synthetic universe with known rank ordering), the Monte
Carlo engine (percentile ordering, cash-only converges to the risk-free rate,
crypto-heavy allocations show wider dispersion than equity-heavy ones), and
every API endpoint against a seeded temp database.

## Running the AI analyst agent

This is a real tool-calling agent (not the browser demo's static preview
tab) -- it can only state a number after retrieving it from the API above.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn app.main:app --reload &     # if not already running
python agent/chat_agent.py
```

```
you> Why does NVDA score high on growth but weak on value?
  -> get_company_score({"ticker": "NVDA"})
analyst> ...
```

## Data ingestion pipelines

`pipelines/*.py` are structured, correct clients for the real APIs
(SEC EDGAR, a price vendor, CoinGecko, FRED/ECB) -- endpoint shapes were
verified against each provider's current documentation. **They have not
been run against the live internet**: this sandbox's network egress does
not reach any of those domains. Before you rely on them:

- Run each one against a couple of real tickers/series and inspect the output.
- `sec_ingest.py`'s `ebitda` and `free_cash_flow` are placeholder
  approximations from operating income / net income -- SEC's XBRL tagging
  isn't uniform enough across filers to pull these cleanly without
  per-company tag fallbacks; replace with real D&A / operating-cash-flow /
  capex tags before using this for anything real.
- `prices_ingest.py` ships one vendor (Alpha Vantage) behind a small
  `PriceVendor` interface -- swap in whichever vendor fits your budget and
  coverage needs.
- All four pipelines' *parsing* logic (not their live HTTP calls) is
  unit-testable the same way `tests/test_risk.py` tests the analytics --
  that's a good next addition.

## What's simplified vs. the full plan

- **Single-user portfolio, no auth.** `Portfolio` is a singleton row (id=1).
  Add a `user_id` + real auth before this is multi-tenant.
- **Simplified price schema.** One `close` price per instrument per day, not
  full OHLCV. Add `open`/`high`/`low`/`volume` columns if you need them.
- **No caching or task queue.** Every request recomputes ratios/scores/risk
  stats from raw price and fundamentals rows on the fly -- correct and
  simple, but it will not scale to a large universe or heavy traffic as-is.
  Redis + a background worker (Celery/RQ/Prefect) for ingestion and score
  caching is the natural next phase, matching the original plan's own
  roadmap.
- **No filings Q&A / RAG.** The original plan's document-search feature
  needs a vector store and a chunking/embedding pipeline over real filings
  text -- out of scope here.
- **Approximate EBITDA/FCF in the SEC pipeline** -- see above.
- **10 equities + 2 ETFs + 3 crypto assets** in the demo dataset. The schema
  and pipelines aren't limited to this list; it's just what's seeded.

## Design notes worth knowing

- Every ratio/score/risk formula exists in exactly two places: this backend
  (`app/services/`, Python) and the browser demo (JS) -- both were written
  from the same spec so they agree, and both are unit-tested independently.
- Factor scores are always **cross-sectional percentiles within the current
  universe**, never an absolute/arbitrary number, and every score carries
  its exact metric breakdown and weights (`GET /scores/{ticker}`) -- so the
  AI agent (and a human) can always see exactly what a score is made of.
