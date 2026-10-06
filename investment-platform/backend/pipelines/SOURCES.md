# Market data sources

What the real-data pipelines (`pipelines/jobs.py`) load, from where, and what you
need to sort out before customers see it. Everything below was verified live on
2026-10-05; the full backfill took ~6 minutes into SQLite.

```
python -m pipelines.run all --full     # first load (backfill)
python -m pipelines.run all            # daily incremental (also scheduled, see JOBS in jobs.py)
```

## Wired in

| Job | Source | What | History | Key | Cadence (Athens time) |
|---|---|---|---|---|---|
| `equities` | Yahoo Finance chart API | 35 Euronext Athens stocks (`.AT`), Athens General index `GD.AT`, EURO STOXX 50, S&P 500, MSCI World ETF: daily OHLCV + adjusted close | 2015 → (shorter for recent listings) | none | Mon–Fri 18:30 |
| `crypto` | Binance public klines | 12 coins, daily OHLCV in **EUR** (`BTC-EUR` …) | 2020 → (EUR pairs start 2020–21) | none | every 6 h |
| `crypto` | CoinGecko `/coins/markets` | market cap, 24h volume, circulating supply, rank (EUR) | daily snapshot from first run | optional demo key | every 6 h |
| `fundamentals` | filings.xbrl.org (XBRL International) | ESEF annual reports → consolidated IFRS facts (revenue, profit, assets, equity, EPS, …) for 29 Athens issuers | FY2021 → FY2024 | none | Sun 06:00 |
| `indicators` | Eurostat | Greece + EU-27: HICP, unemployment (total, youth), real GDP q/q, household saving rate, government debt/GDP, consumer confidence | 1985–2000 → | none | daily 07:15 |
| `indicators` | ECB Data Portal | deposit facility rate, €STR, 3m Euribor, GR & DE 10y yields (→ derived GR-DE spread), Greek mortgage and term-deposit rates, EUR/USD | 2010 → | none | daily 07:15 |
| `indicators` | FRED | US fed funds, US 10y, VIX, Brent | 2010 → | `FRED_API_KEY` | daily 07:15 |
| `indicators` | alternative.me | Crypto Fear & Greed index | 2018 → | none | daily 07:15 |
| `indicators` | DefiLlama | total DeFi TVL (USD) | 2017 → | none | daily 07:15 |
| `snapshots` | (computed) | per indicator: latest value, 90-day direction, 1y-ago value, EU-27 comparator, staleness, payload eligibility (the Databricks notebook logic, no descriptor text) | one row/day | — | daily 07:45 |

Edit `pipelines/catalog.py` to add a stock, coin or indicator.

## Before this is customer-facing: licensing

| Source | Status |
|---|---|
| Eurostat | Free reuse incl. commercial, with source acknowledgement. ✅ |
| ECB Data Portal | Free reuse with source citation. ✅ |
| filings.xbrl.org / ESEF | Issuers' public regulatory filings; the index is a free XBRL International service. ✅ (cite the issuer's report) |
| FRED | Free, but some series carry third-party copyright (e.g. **VIX is © Cboe**). Check each series' notes before redistributing. ⚠️ |
| alternative.me, DefiLlama | Free; attribution expected. ✅/⚠️ |
| CoinGecko (free Demo plan) | Attribution required; commercial display needs a paid plan, so check the current terms. ⚠️ |
| Binance market data | Public endpoints; review Binance's terms on redistribution / display. ⚠️ |
| **Yahoo Finance** | **Unofficial, not licensed for commercial use.** OK for development and internal research only. Before customers see Athens prices, swap `sources/yahoo.py` for a licensed feed: Euronext market-data licence (Athens is now part of Euronext), or a vendor such as EODHD / Twelve Data / LSEG. ❌ for production |

## Data quality notes

- **Zero-volume placeholder bars** (Yahoo fills suspended sessions with stale or wrong prices) are dropped when the price jumps >50% from the last traded close: `yahoo.drop_phantom_bars`. Each run logs what it dropped (e.g. ETE.AT 2015-11-30..12-02, during the recapitalisation).
- **Use `adj_close` for returns**, not `close`. A dividend or split inside the incremental window triggers a full re-fetch of that stock, because every earlier adjusted close changes.
- **CrediaBank (ex-Attica Bank)** has genuine extreme history (massive dilutions in 2021 and 2024). Exclude it from return statistics or cap its returns.
- **Re-listed tickers have short history on Yahoo:** ALPHA.AT from 2025-07 (Alpha Bank merger), MTLN.AT from 2025-08 (Metlen PLC replaced MYTIL), BOCHGR.AT from 2024-09. Older history would need stitching from the predecessor symbol.
- **ESEF coverage gaps:** Eurobank and Ellaktor have FY2023 as their latest filing on filings.xbrl.org; OPAP/Allwyn, ADMIE, CrediaBank, Aktor, Intracom and Kri-Kri have no LEI match, so they get prices only. Concepts differ by industry (banks report `InterestIncome…`, not `Revenue`), so normalise per sector in the API layer, not in the loader.
- **Revisions:** ECB and FRED re-read ~400 days each run and Eurostat the full series; changed values overwrite in place (`fetched_at` updates). DefiLlama revises TVL history often.
- **Real market instruments are kept out of the demo analytics** (`Instrument.data_source != "simulated"`), because those endpoints assume one aligned simulated date grid. Real-data endpoints come next.

## Free sources checked but not wired (yet)

| Source | Verdict |
|---|---|
| World Bank API | Works, no key; annual only (GDP, population, …). Good for long-run context. |
| OECD SDMX | Works but needs exact dataflow keys (e.g. composite leading indicators for Greece). |
| IMF DataMapper | Blocked from this network (HTTP 403). |
| Bank of Greece, ELSTAT | No public API; Excel downloads only. Eurostat and the ECB already republish most of their headline series. |
| Kraken public OHLC | Works, no key; a good fallback for Binance (720 bars per call). |
| CoinPaprika | Works, no key; an alternative to CoinGecko for market cap. |
| EODHD | Free tier 20 calls/day; paid plans cover Athens (`.AT`) properly. A candidate licensed replacement for Yahoo. |
| Stooq | Now behind a JavaScript challenge, so not usable from a script. |
