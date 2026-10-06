# Real-data API (`/v1`) and its monitoring

Serves the real market data loaded by `pipelines/` (sources: `pipelines/SOURCES.md`).
The original demo endpoints (`/instruments`, `/compare`, `/scores`, …) still run on
the simulated dataset and are unchanged. Interactive docs: http://localhost:8000/docs.

## Endpoints

| Endpoint | What |
|---|---|
| `GET /v1/instruments?asset_type=&country=&sector=&q=` | All real instruments: last close, 1-day change, 1m/1y return, whether fundamentals exist. Cached for `MARKET_CACHE_TTL_S` (default 300 s). |
| `GET /v1/instruments/{ticker}` | Detail: LEI, history start, returns (1w…5y, YTD), 1y volatility and max drawdown, CoinGecko market data for crypto. Tickers are case-insensitive: `ETE.AT`, `BTC-EUR`, `^GSPC`. |
| `GET /v1/instruments/{ticker}/prices?start=&end=&interval=daily\|weekly\|monthly` | OHLCV + adjusted close. Default is the last year of daily bars. |
| `GET /v1/instruments/{ticker}/performance` | Returns, volatility, 1y and all-time max drawdown. |
| `GET /v1/compare?tickers=BTC-EUR,ETH-EUR,GD.AT&start=&end=` | 2–10 instruments rebased to 100 on a shared date axis (crypto trades 7 days/week, Athens 5: gaps carry the last close forward). Default is the last year. No FX conversion: the response says so when currencies differ. |
| `GET /v1/instruments/{ticker}/fundamentals` | Per fiscal year: comparable metrics mapped from the ESEF/IFRS facts (with the source concept for each), ratios (ROE, margins, FCF, payout, loan-to-deposit for banks, growth), plus P/E (and P/B / market cap where a share count is reported). |
| `GET /v1/crypto/market` | Coins by market-cap rank, CoinGecko snapshot, Fear & Greed, DeFi TVL. |
| `GET /v1/macro/indicators?category=&geo=` | Indicator catalog with today's snapshot (value, 90-day direction, 1y-ago, EU-27 comparator, staleness, eligibility). |
| `GET /v1/macro/indicators/{id}` · `/series?start=&end=` | One indicator; native-frequency history (default 5 years). |
| `GET /v1/macro/snapshot?as_of=&eligible_only=` | All snapshots for a day (default latest). `eligible_only=true` = fresh enough to quote. |
| `GET /v1/data-status` | Freshness of every series and health of every market job. `overall`: `ok` / `degraded` / `critical`. |

Errors: unknown ticker or indicator → 404; invalid input (range, interval, ticker count) → 422.

## Monitoring

```
backend /metrics ──► Prometheus (alerts.yml) ──► Grafana "Market Data & API"
backend DB ─────────────────────────────────────► Grafana tables (Neon datasource)
```

- **API:** request rate, latency histogram and status codes per `/v1` endpoint (prometheus-fastapi-instrumentator).
- **Data:** `app/monitoring.py` reads the DB at most every `METRICS_REFRESH_S` (60 s) and exposes:
  `market_data_age_days`, `market_data_stale`, `market_data_stale_items`, `market_pipeline_hours_since_success`,
  `market_pipeline_overdue`, `market_pipeline_last_status`, `market_pipeline_last_rows`, `market_data_overall`,
  `market_monitoring_scrape_ok`. The JSON form of the same check is `GET /v1/data-status`.
- **Thresholds** (in `app/monitoring.py`):
  - stale: crypto after 1 day; equities/indices after 4 days; annual reports ~16 months after fiscal year end; indicators past their own staleness cap (`pipelines/catalog.py`)
  - job overdue: crypto after 7 h; indicators/snapshots after 26 h; equities after 76 h; fundamentals after 8 days
- **Alerts** (`infra/prometheus/alerts.yml`): backend down, `/v1` 5xx above 5%, p95 latency above 2 s, prices stale, indicator not quotable, annual reports outdated, job overdue, job failed. They show in Prometheus `/alerts` and in the dashboard's *Firing alerts* table. Add an Alertmanager to send them to email or Teams.
- **Dashboard** `infra/grafana/dashboards/market_data_health.json` (auto-provisioned): health/stale/overdue tiles, `/v1` traffic and latency per endpoint, firing alerts, last run per job, run durations, newest bar per instrument, indicator snapshot table, latest annual report per issuer.
