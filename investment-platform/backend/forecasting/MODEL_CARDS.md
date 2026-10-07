# Model cards (v1)

Every model is retrained and re-validated daily by the `forecasts` job (19:30 Athens, after the price load).
Each run is a new row in `model_versions`, with out-of-sample metrics, the baseline's metrics, parameters
and a status. **Only `approved` versions serve predictions** (`model_predictions` → `/v1/predictions`,
MCP `get_risk_estimates` / `get_market_conditions` / `get_quality_ranking`). Live numbers:
`GET /v1/predictions/models`.

Validation is walk-forward throughout: at each test date a model sees only data available on that date. For
macro data that means data already *published*, not just already measured.

Results below are from the first run on real data (2026-10-06; prices since 2015, crypto since 2020).

---

## volatility: 21-day risk per instrument · **approved**

| | |
|---|---|
| Output | Annualised volatility over the next 21 trading days; P(the price ends > 10% lower after 21 days); 1-year beta and correlation vs benchmark (GD.AT for Athens, BTC-EUR for crypto, S&P 500 otherwise) |
| Candidates | EWMA (λ = 0.94), GARCH(1,1) on the last 1,000 daily returns |
| Baseline | Last 252 observations' volatility |
| Validation | Every 21 observations over the last 3 years, 47 instruments, 1,708 forecasts; QLIKE loss vs realised variance |
| Result | GARCH QLIKE −6.590 vs baseline −6.560 (**0.5% better**); EWMA was worse than the baseline. For P(fall > 10%), the asset's own historical frequency (Brier 0.0764) narrowly beat the model-implied probability (0.0767), so the historical frequency is served, but only for instruments with ≥ 3 years of history; shorter histories (recent listings) get the model-implied probability, because their own loss frequency is too noisy. |
| Approval rule | Champion = lowest QLIKE. If no candidate beats the baseline, the baseline itself is served: a naive risk estimate is still a valid risk estimate. |
| Limitations | Small edge over the baseline. Normal-tail assumption for the model-implied probability. Assets with extreme corporate-action history (CrediaBank) get inflated historical loss frequencies. GARCH can fail to fit an individual asset; that asset falls back to the baseline (`details.method`). |

## conditions: current Athens market state · **approved (measurement)**

Not a forecast. It reports where the Athens General index's 3-month realised volatility sits in its own history (percentile), the drawdown from the 6-month high, and a label: *stressed* if ≥ 80th percentile or > 15% below the high, *calm* if ≤ 33rd percentile, otherwise *normal*.

## regime: P(stressed Athens market next month) · **rejected**

| | |
|---|---|
| Target | GD.AT falls > 7% from a peak within the next 21 trading days (base rate 20%) |
| Features | GD.AT 1-month return, 3-month volatility and 6-month drawdown; VIX; GR-DE 10y spread (level and 3-month change); 6-month Euribor change; Greek HICP. All point-in-time, using publication lags. |
| Model | Standardised features → L2 logistic regression (C = 0.5), refit monthly on an expanding window |
| Baseline | Training-window base rate |
| Result | 84 test months (2019-09 → 2026-08): **AUC 0.39, Brier skill −0.15**, i.e. worse than the base rate. Relationships learned in the 2015-2019 Greek crisis years did not hold afterwards. |
| Approval rule | Brier skill > 0 and AUC > 0.55 over ≥ 36 test months |
| Next steps | Shorter, rolling training windows; regime-switching models; Euro-area-wide stress targets with more history. |

## quality: annual-report quality score · **approved (scoring)**

A transparent percentile ranking, not a prediction and not a recommendation. Banks are compared with banks on ROE, ROA, equity/assets, profit growth and payout. Other companies are compared with all non-banks on ROE, operating and net margin, equity/assets, current ratio, revenue growth and FCF margin. Score = mean percentile × 100, published when ≥ 3 components are available. 29 companies scored. The data is from FY2024 or earlier, because the FY2025 ESEF filings aren't on filings.xbrl.org yet.

## direction: P(positive 21-day return) · **rejected**

| | |
|---|---|
| Features | Momentum 1m / 3m / 12m-skip-1m, 3-month volatility, distance from 52-week high, Athens index 1-month return |
| Model | Pooled L2 logistic regression (C = 0.1), refit monthly |
| Baselines | (a) training base rate; (b) "3-month momentum > 0 ⇒ up" |
| Result | 51 months, 1,721 samples: model AUC **0.50**, accuracy 57.3% vs 59.9% for "always up". Brier 0.2453 vs 0.2443. No skill. |
| Approval rule | Brier better than both baselines and accuracy ≥ 1 point above the better baseline, over ≥ 24 test months |
| Note | Expected for liquid assets at this horizon. The model is kept so any future improvement is tested the same honest way. |

---

## Governance (before customer use)

- **Independent validation:** the bank's model-risk function should review these cards, the code and the walk-forward method. Approval is automatic today; a human sign-off step for `approved` → served can be added to the registry.
- **Explainability:** the regime and direction models store coefficients; regime predictions include per-feature contributions.
- **Monitoring:** alerts `RiskModelNotServed`, `ModelPredictionsStale` and `ModelNotRetrained`, the pipeline-overdue alert for the `forecasts` job, and the *Models* row on the Market Data & API dashboard.
- **Not advice:** every `/v1/predictions` response carries a disclaimer. The step-5 proposal must treat these numbers as inputs to an explanation, not as a recommendation.
