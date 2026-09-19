"""
Risk and market-statistics functions. These mirror the JS analytics engine in
the browser demo (investment-platform-demo.jsx) line for line, so the backend
API and the demo agree on definitions -- there is exactly one set of formulas
for this platform, expressed twice (JS for the browser, Python for the API).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np

TRADING_DAYS_YEAR = 252
RISK_FREE_ANNUAL = 0.04


def daily_log_returns(close: Sequence[float]) -> np.ndarray:
    close = np.asarray(close, dtype=float)
    return np.diff(np.log(close))


def annualized_vol(returns: np.ndarray) -> float:
    if len(returns) < 2:
        return float("nan")
    return float(np.std(returns, ddof=1) * math.sqrt(TRADING_DAYS_YEAR))


def annualized_return(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return float("nan")
    return float(np.mean(returns) * TRADING_DAYS_YEAR)


def cumulative_return_over_days(close: Sequence[float], days: int) -> Optional[float]:
    close = np.asarray(close, dtype=float)
    if len(close) <= days:
        return None
    return float(close[-1] / close[-1 - days] - 1)


def max_drawdown(close: Sequence[float]) -> float:
    close = np.asarray(close, dtype=float)
    peak = close[0]
    worst = 0.0
    for p in close:
        if p > peak:
            peak = p
        dd = p / peak - 1
        if dd < worst:
            worst = dd
    return float(worst)


def sma(close: Sequence[float], window: int) -> Optional[float]:
    close = np.asarray(close, dtype=float)
    if len(close) < window:
        return None
    return float(np.mean(close[-window:]))


def ema(values: Sequence[float], span: int) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    k = 2 / (span + 1)
    out = np.empty_like(values)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = values[i] * k + out[i - 1] * (1 - k)
    return out


def macd(close: Sequence[float]) -> dict:
    close = np.asarray(close, dtype=float)
    if len(close) < 35:
        return {"line": None, "signal": None, "hist": None}
    ema_fast = ema(close, 12)
    ema_slow = ema(close, 26)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, 9)
    return {"line": float(macd_line[-1]), "signal": float(signal_line[-1]), "hist": float(macd_line[-1] - signal_line[-1])}


def rsi(close: Sequence[float], window: int = 14) -> Optional[float]:
    close = np.asarray(close, dtype=float)
    if len(close) < window + 1:
        return None
    diffs = np.diff(close[-(window + 1):])
    gains = diffs[diffs >= 0].sum()
    losses = -diffs[diffs < 0].sum()
    avg_gain, avg_loss = gains / window, losses / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - 100 / (1 + rs))


def sharpe_ratio(returns: np.ndarray, rf: float = RISK_FREE_ANNUAL) -> Optional[float]:
    vol = annualized_vol(returns)
    if not vol or math.isnan(vol):
        return None
    return (annualized_return(returns) - rf) / vol


def sortino_ratio(returns: np.ndarray, rf: float = RISK_FREE_ANNUAL) -> Optional[float]:
    downside = returns[returns < 0]
    if len(downside) == 0:
        return None
    dd = float(np.std(downside, ddof=1) * math.sqrt(TRADING_DAYS_YEAR))
    if dd == 0:
        return None
    return (annualized_return(returns) - rf) / dd


def historical_var(returns: np.ndarray, confidence: float = 0.95) -> float:
    sorted_r = np.sort(returns)
    idx = min(max(int((1 - confidence) * len(sorted_r)), 0), len(sorted_r) - 1)
    return float(sorted_r[idx])


def historical_cvar(returns: np.ndarray, confidence: float = 0.95) -> float:
    sorted_r = np.sort(returns)
    cut = min(max(int((1 - confidence) * len(sorted_r)), 1), len(sorted_r))
    return float(np.mean(sorted_r[:cut]))


def beta_vs_market(returns: np.ndarray, market_returns: np.ndarray) -> Optional[float]:
    n = min(len(returns), len(market_returns))
    a, b = returns[-n:], market_returns[-n:]
    var_m = np.var(b, ddof=1)
    if var_m == 0:
        return None
    cov = np.cov(a, b, ddof=1)[0][1]
    return float(cov / var_m)


@dataclass
class MarketStats:
    return_1m: Optional[float]
    return_3m: Optional[float]
    return_6m: Optional[float]
    return_12m: Optional[float]
    volatility: float
    max_drawdown: float
    sharpe: Optional[float]
    sortino: Optional[float]
    var95: float
    cvar95: float
    beta: Optional[float]
    sma50: Optional[float]
    sma200: Optional[float]
    rsi14: Optional[float]
    macd: dict
    last_close: float


def market_stats(close: Sequence[float], market_close: Optional[Sequence[float]] = None) -> MarketStats:
    close = np.asarray(close, dtype=float)
    returns = daily_log_returns(close)
    market_returns = daily_log_returns(np.asarray(market_close, dtype=float)) if market_close is not None else None
    return MarketStats(
        return_1m=cumulative_return_over_days(close, 21),
        return_3m=cumulative_return_over_days(close, 63),
        return_6m=cumulative_return_over_days(close, 126),
        return_12m=cumulative_return_over_days(close, 252),
        volatility=annualized_vol(returns),
        max_drawdown=max_drawdown(close),
        sharpe=sharpe_ratio(returns),
        sortino=sortino_ratio(returns),
        var95=historical_var(returns),
        cvar95=historical_cvar(returns),
        beta=beta_vs_market(returns, market_returns) if market_returns is not None else None,
        sma50=sma(close, 50),
        sma200=sma(close, 200),
        rsi14=rsi(close, 14),
        macd=macd(close),
        last_close=float(close[-1]),
    )
