"""
21-period volatility forecasts per instrument.

Candidates: EWMA (RiskMetrics, lambda 0.94) and GARCH(1,1); baseline: the last
252 observations' standard deviation ("last year's volatility").
Walk-forward: every 21 observations over the last EVAL_YEARS, each method
forecasts using data up to that date only; the forecast is scored against the
realised variance of the next 21 returns with QLIKE (log f + rv/f, lower is
better, robust to noise in realised variance). The method with the lowest
pooled QLIKE is the champion; if no candidate beats the baseline, the baseline
itself is served (it is still a valid, if naive, risk estimate).

Also: P(fall of more than 10% over the next 21 periods), from the forecast
volatility (normal, zero mean) -- scored with the Brier score against the
asset's own historical frequency, and the better of the two is served.
"""
from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd
from scipy.stats import norm

HORIZON = 21
LOSS_THRESHOLD = math.log(0.90)   # -10% over the horizon
EWMA_LAMBDA = 0.94
EVAL_YEARS = 3
GARCH_WINDOW = 1000               # observations used to fit GARCH (speed; older data adds little)
MIN_EMPIRICAL_OBS = 750           # ~3 years: below this a historical loss frequency is too noisy to serve
BENCHMARKS = {"AT": "GD.AT", "crypto": "BTC-EUR", "europe": "^STOXX50E", "other": "^GSPC"}


def log_returns(prices: pd.Series) -> np.ndarray:
    p = prices[prices > 0]
    return np.diff(np.log(p.to_numpy()))


def periods_per_year(index: pd.DatetimeIndex) -> float:
    """~252 for exchange-traded, ~365 for crypto, measured from the last two years."""
    recent = index[index >= index[-1] - pd.Timedelta(days=730)]
    span_years = max((recent[-1] - recent[0]).days / 365.25, 0.25)
    return len(recent) / span_years


# ---------------------------------------------------------------- one-step methods (daily variance over the horizon)
def hist_var(r: np.ndarray, window: int = 252) -> float:
    w = r[-window:]
    return float(np.var(w, ddof=1)) if len(w) > 20 else float("nan")


def ewma_var(r: np.ndarray, lam: float = EWMA_LAMBDA) -> float:
    if len(r) < 30:
        return float("nan")
    v = float(np.var(r[:30], ddof=1))
    for x in r[30:]:
        v = lam * v + (1 - lam) * x * x
    return v


def garch_var(r: np.ndarray, horizon: int = HORIZON) -> tuple[float, dict]:
    """Mean daily variance over the next `horizon` steps from a GARCH(1,1) fit (returns scaled x100 for stability)."""
    from arch import arch_model

    x = r[-GARCH_WINDOW:] * 100.0
    if len(x) < 250:
        return float("nan"), {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = arch_model(x, mean="Zero", vol="GARCH", p=1, q=1, dist="normal", rescale=False).fit(disp="off", show_warning=False)
    var_path = res.forecast(horizon=horizon, reindex=False).variance.to_numpy()[-1]
    params = {k: float(v) for k, v in res.params.items()}
    if params.get("alpha[1]", 0) + params.get("beta[1]", 0) >= 0.999 or not np.all(np.isfinite(var_path)):
        return float("nan"), params  # non-stationary fit: don't trust it
    return float(np.mean(var_path)) / 1e4, params


METHODS = {"historical_252": lambda r: hist_var(r), "ewma_0.94": lambda r: ewma_var(r), "garch_1_1": lambda r: garch_var(r)[0]}
BASELINE = "historical_252"


def qlike(forecast_var: float, realised_var: float) -> float:
    return math.log(forecast_var) + realised_var / forecast_var


def p_loss(daily_var: float, horizon: int = HORIZON, threshold: float = LOSS_THRESHOLD) -> float:
    return float(norm.cdf(threshold / math.sqrt(daily_var * horizon)))


# ---------------------------------------------------------------- walk-forward evaluation
def evaluate(panel: dict[str, pd.Series], eval_years: int = EVAL_YEARS, methods: dict | None = None) -> dict:
    """Pooled out-of-sample QLIKE per method and Brier scores for P(loss > 10%)."""
    methods = methods or METHODS
    losses: dict[str, list[float]] = {m: [] for m in methods}
    brier = {m: [] for m in methods}
    brier_empirical, n_events, n = [], 0, 0
    per_asset = {}
    for ticker, prices in panel.items():
        r = log_returns(prices)
        dates = prices.index[1:]
        start = dates[-1] - pd.Timedelta(days=365 * eval_years)
        origins = [i for i in range(300, len(r) - HORIZON, HORIZON) if dates[i] >= start]
        asset_losses = {m: [] for m in methods}
        for i in origins:
            past, future = r[: i + 1], r[i + 1: i + 1 + HORIZON]
            rv = float(np.mean(future ** 2))
            if rv <= 0:
                continue
            forecasts = {m: f(past) for m, f in methods.items()}
            if any(not (f > 0 and math.isfinite(f)) for f in forecasts.values()):
                continue  # compare methods only on origins where all produced a forecast
            for m, f in forecasts.items():
                q = qlike(f, rv)
                losses[m].append(q)
                asset_losses[m].append(q)
            # P(loss > 10%): from each method's forecast vs the asset's own past frequency
            event = float(np.sum(future) < LOSS_THRESHOLD)
            past_h = np.convolve(past, np.ones(HORIZON), "valid")
            empirical = float(np.mean(past_h < LOSS_THRESHOLD)) if len(past_h) else 0.0
            for m, f in forecasts.items():
                brier[m].append((p_loss(f) - event) ** 2)
            brier_empirical.append((empirical - event) ** 2)
            n_events += int(event)
            n += 1
        if asset_losses[BASELINE]:
            per_asset[ticker] = {m: float(np.mean(v)) for m, v in asset_losses.items()}
    mean_loss = {m: float(np.mean(v)) if v else float("nan") for m, v in losses.items()}
    return {
        "qlike": mean_loss, "n_forecasts": len(losses[BASELINE]), "n_assets": len(per_asset),
        "brier_p_loss": {m: float(np.mean(v)) if v else float("nan") for m, v in brier.items()},
        "brier_p_loss_empirical": float(np.mean(brier_empirical)) if brier_empirical else float("nan"),
        "loss_event_rate": n_events / n if n else float("nan"),
        "per_asset_qlike": per_asset,
    }


def choose(ev: dict) -> tuple[str, bool, str, str]:
    """(champion method, approved, reason, p_loss method)."""
    q = ev["qlike"]
    candidates = {m: v for m, v in q.items() if m != BASELINE and math.isfinite(v)}
    best = min(candidates, key=candidates.get) if candidates else BASELINE
    base = q[BASELINE]
    champion = best if candidates and candidates[best] < base else BASELINE
    p_method = "model" if ev["brier_p_loss"][champion] <= ev["brier_p_loss_empirical"] else "empirical"
    if champion != BASELINE:
        gain = (base - candidates[best]) / abs(base) if base else 0.0
        return champion, True, f"{best} beats last-year volatility out of sample (QLIKE {candidates[best]:.4f} vs {base:.4f}, {gain:.1%} better)", p_method
    return BASELINE, True, "no candidate beat last-year volatility out of sample; serving the baseline", p_method


# ---------------------------------------------------------------- serving
def benchmark_for(ticker: str, asset_type: str) -> str:
    if asset_type == "crypto":
        return BENCHMARKS["crypto"]
    if ticker.endswith(".AT"):
        return BENCHMARKS["AT"]
    if ticker.endswith(".US") or ticker.startswith("^") or "." not in ticker:
        return BENCHMARKS["other"]
    return BENCHMARKS["europe"]  # euro-area stocks and the EUR-listed ETFs


def beta(asset: pd.Series, bench: pd.Series, days: int = 365) -> tuple[float | None, float | None]:
    """Beta and correlation of daily log returns over the last `days`, on common dates."""
    df = pd.concat([asset, bench], axis=1, join="inner").dropna()
    df = df[df.index >= df.index[-1] - pd.Timedelta(days=days)] if len(df) else df
    if len(df) < 60:
        return None, None
    rets = np.log(df).diff().dropna().to_numpy()
    a, b = rets[:, 0], rets[:, 1]
    var_b = float(np.var(b, ddof=1))
    if var_b == 0:
        return None, None
    return float(np.cov(a, b, ddof=1)[0, 1] / var_b), float(np.corrcoef(a, b)[0, 1])


def predict(panel: dict[str, pd.Series], asset_types: dict[str, str], method: str, p_method: str) -> list[dict]:
    rows = []
    for ticker, prices in panel.items():
        r = log_returns(prices)
        daily_var = METHODS[method](r)
        if not (daily_var > 0 and math.isfinite(daily_var)):
            daily_var, used = hist_var(r), BASELINE  # GARCH can fail for a single asset: fall back
        else:
            used = method
        ppy = periods_per_year(prices.index)
        used_p = p_method if len(r) >= MIN_EMPIRICAL_OBS else "model"  # short histories: frequency is unreliable
        if used_p == "model":
            p = p_loss(daily_var)
        else:
            hist_h = np.convolve(r, np.ones(HORIZON), "valid")
            p = float(np.mean(hist_h < LOSS_THRESHOLD))
        bench = benchmark_for(ticker, asset_types.get(ticker, "equity"))
        b, corr = beta(prices, panel[bench]) if bench in panel and bench != ticker else (None, None)
        details = {"method": used, "daily_vol": math.sqrt(daily_var), "periods_per_year": ppy,
                   "last_year_vol_annualized": math.sqrt(hist_var(r) * ppy), "benchmark": bench if b is not None else None,
                   "beta_1y": b, "correlation_1y": corr, "as_of_price_date": prices.index[-1].date()}
        rows.append({"subject": ticker, "target": "vol_21d_annualized", "horizon_days": HORIZON,
                     "value": math.sqrt(daily_var * ppy), "details": details})
        rows.append({"subject": ticker, "target": "p_loss_10pct_21d", "horizon_days": HORIZON, "value": p,
                     "details": {"method": used_p, "threshold": -0.10, "history_observations": len(r)}})
    return rows
