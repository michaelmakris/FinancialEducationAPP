import numpy as np
import pytest

from app.services import risk


def make_gbm_close(n=504, start=100.0, drift=0.10, vol=0.20, seed=1):
    rng = np.random.default_rng(seed)
    dt = 1 / 252
    shocks = rng.normal((drift - 0.5 * vol**2) * dt, vol * np.sqrt(dt), n)
    return start * np.exp(np.cumsum(shocks))


def test_daily_log_returns_length():
    close = make_gbm_close(100)
    r = risk.daily_log_returns(close)
    assert len(r) == 99


def test_annualized_vol_matches_input_vol_approximately():
    close = make_gbm_close(n=5000, vol=0.25, seed=42)
    r = risk.daily_log_returns(close)
    assert 0.20 < risk.annualized_vol(r) < 0.30


def test_max_drawdown_is_nonpositive_and_detects_known_drop():
    close = [100, 110, 90, 95, 120]
    dd = risk.max_drawdown(close)
    assert dd <= 0
    assert dd == pytest.approx((90 / 110) - 1, rel=1e-6)


def test_sma_matches_manual_average():
    close = [1, 2, 3, 4, 5]
    assert risk.sma(close, 3) == pytest.approx((3 + 4 + 5) / 3)
    assert risk.sma(close, 10) is None


def test_rsi_is_100_when_all_gains():
    close = [100 + i for i in range(20)]
    assert risk.rsi(close, 14) == 100.0


def test_rsi_bounded_0_100():
    close = make_gbm_close(60, seed=7)
    val = risk.rsi(close.tolist(), 14)
    assert 0 <= val <= 100


def test_historical_var_is_a_left_tail_return():
    rng = np.random.default_rng(0)
    returns = rng.normal(0, 0.01, 1000)
    var95 = risk.historical_var(returns, 0.95)
    # ~5% of returns should be below the 95% VaR cutoff
    frac_below = float(np.mean(returns < var95))
    assert 0.03 < frac_below < 0.07


def test_cvar_is_worse_than_var():
    rng = np.random.default_rng(0)
    returns = rng.normal(0, 0.01, 2000)
    var95 = risk.historical_var(returns, 0.95)
    cvar95 = risk.historical_cvar(returns, 0.95)
    assert cvar95 <= var95


def test_beta_of_series_against_itself_is_one():
    close = make_gbm_close(300, seed=3)
    r = risk.daily_log_returns(close)
    assert risk.beta_vs_market(r, r) == pytest.approx(1.0, rel=1e-6)


def test_sharpe_none_when_zero_vol():
    flat_returns = np.zeros(50)
    assert risk.sharpe_ratio(flat_returns) is None


def test_market_stats_end_to_end_smoke():
    close = make_gbm_close(504, seed=9)
    market = make_gbm_close(504, seed=10)
    stats = risk.market_stats(close, market)
    assert stats.last_close == pytest.approx(close[-1])
    assert stats.sma50 is not None and stats.sma200 is not None
    assert stats.beta is not None
