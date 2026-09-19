"""
Multivariate Monte Carlo portfolio simulator. Estimates mean/covariance of
equities/bonds/crypto daily log returns from historical data, correlates
simulated paths via Cholesky decomposition. Cash is added deterministically
at a fixed rate rather than simulated (avoids a singular covariance matrix).
Mirrors runMonteCarloSimulation() in the browser demo.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .risk import RISK_FREE_ANNUAL, TRADING_DAYS_YEAR, daily_log_returns


@dataclass
class SimulationResult:
    amount: float
    horizon_months: float
    weights: dict
    median: float
    p10: float
    p25: float
    p75: float
    p90: float
    min: float
    max: float
    prob_loss: float
    prob_gain_10: float
    assumptions: dict


def build_asset_class_returns(instruments_by_ticker: dict) -> dict:
    eq = daily_log_returns(instruments_by_ticker["SPY"]["close"])
    bond = daily_log_returns(instruments_by_ticker["AGG"]["close"])
    btc = daily_log_returns(instruments_by_ticker["BTC"]["close"])
    eth = daily_log_returns(instruments_by_ticker["ETH"]["close"])
    sol = daily_log_returns(instruments_by_ticker["SOL"]["close"])
    n = min(len(btc), len(eth), len(sol))
    crypto = (btc[-n:] + eth[-n:] + sol[-n:]) / 3
    return {"equities": eq, "bonds": bond, "crypto": crypto}


def run_monte_carlo_simulation(
    instruments_by_ticker: dict,
    amount: float,
    weights: dict,
    horizon_months: float,
    n_sims: int = 3000,
    rng: Optional[np.random.Generator] = None,
) -> SimulationResult:
    rng = rng or np.random.default_rng()
    classes = build_asset_class_returns(instruments_by_ticker)
    series = [classes["equities"], classes["bonds"], classes["crypto"]]
    n = min(len(s) for s in series)
    series = [s[-n:] for s in series]
    mu = np.array([np.mean(s) for s in series])
    sigma = np.cov(np.vstack(series))
    # small jitter for numerical PD safety
    sigma = sigma + np.eye(3) * 1e-12
    L = np.linalg.cholesky(sigma)

    H = max(1, round(horizon_months * 21))
    daily_cash = (1 + RISK_FREE_ANNUAL) ** (1 / TRADING_DAYS_YEAR) - 1

    w_sum = weights["equities"] + weights["bonds"] + weights["crypto"] + weights["cash"]
    w = {k: weights[k] / w_sum for k in ("equities", "bonds", "crypto", "cash")}

    # z: (n_sims, H, 3) standard normals -> correlated daily returns via L
    z = rng.standard_normal(size=(n_sims, H, 3))
    correlated = mu + z @ L.T  # (n_sims, H, 3)
    cum_log = correlated.sum(axis=1)  # (n_sims, 3)
    cash_factor_end = (1 + daily_cash) ** H

    ending = amount * (
        w["equities"] * np.exp(cum_log[:, 0])
        + w["bonds"] * np.exp(cum_log[:, 1])
        + w["crypto"] * np.exp(cum_log[:, 2])
        + w["cash"] * cash_factor_end
    )
    ending_sorted = np.sort(ending)

    def pct(p):
        idx = min(max(int(p * len(ending_sorted)), 0), len(ending_sorted) - 1)
        return float(ending_sorted[idx])

    prob_loss = float(np.mean(ending < amount))
    prob_gain_10 = float(np.mean(ending > amount * 1.10))

    def ann_ret(s):
        return float(np.mean(s) * TRADING_DAYS_YEAR)

    def ann_vol(s):
        return float(np.std(s, ddof=1) * np.sqrt(TRADING_DAYS_YEAR))

    return SimulationResult(
        amount=amount, horizon_months=horizon_months, weights=w,
        median=pct(0.5), p10=pct(0.10), p25=pct(0.25), p75=pct(0.75), p90=pct(0.90),
        min=float(ending_sorted[0]), max=float(ending_sorted[-1]),
        prob_loss=prob_loss, prob_gain_10=prob_gain_10,
        assumptions={
            "equities_annual_return": ann_ret(series[0]), "equities_annual_vol": ann_vol(series[0]),
            "bonds_annual_return": ann_ret(series[1]), "bonds_annual_vol": ann_vol(series[1]),
            "crypto_annual_return": ann_ret(series[2]), "crypto_annual_vol": ann_vol(series[2]),
            "cash_annual_return": RISK_FREE_ANNUAL, "n_sims": n_sims, "horizon_trading_days": H,
        },
    )
