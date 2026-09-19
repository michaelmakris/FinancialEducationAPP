import numpy as np
import pytest

from app.services.simulate import run_monte_carlo_simulation


def make_instruments():
    def close_series(seed, drift, vol, n=504, start=100.0):
        rng = np.random.default_rng(seed)
        dt = 1 / 252
        shocks = rng.normal((drift - 0.5 * vol**2) * dt, vol * np.sqrt(dt), n)
        return list(start * np.exp(np.cumsum(shocks)))

    return {
        "SPY": {"ticker": "SPY", "close": close_series(1, 0.10, 0.16)},
        "AGG": {"ticker": "AGG", "close": close_series(2, 0.035, 0.05)},
        "BTC": {"ticker": "BTC", "close": close_series(3, 0.30, 0.55)},
        "ETH": {"ticker": "ETH", "close": close_series(4, 0.28, 0.60)},
        "SOL": {"ticker": "SOL", "close": close_series(5, 0.35, 0.75)},
    }


def test_percentiles_are_ordered():
    r = run_monte_carlo_simulation(
        make_instruments(), amount=10000,
        weights={"equities": 60, "bonds": 25, "crypto": 10, "cash": 5},
        horizon_months=12, n_sims=1500, rng=np.random.default_rng(0),
    )
    assert r.p10 <= r.p25 <= r.median <= r.p75 <= r.p90
    assert r.min <= r.p10 and r.p90 <= r.max


def test_probabilities_within_bounds():
    r = run_monte_carlo_simulation(
        make_instruments(), amount=10000,
        weights={"equities": 60, "bonds": 25, "crypto": 10, "cash": 5},
        horizon_months=6, n_sims=1000, rng=np.random.default_rng(1),
    )
    assert 0 <= r.prob_loss <= 1
    assert 0 <= r.prob_gain_10 <= 1


def test_cash_only_is_deterministic_and_matches_risk_free_rate():
    r = run_monte_carlo_simulation(
        make_instruments(), amount=10000,
        weights={"equities": 0, "bonds": 0, "crypto": 0, "cash": 100},
        horizon_months=12, n_sims=200, rng=np.random.default_rng(2),
    )
    expected = 10000 * 1.04
    assert r.median == pytest.approx(expected, rel=0.01)
    assert r.p10 == pytest.approx(r.p90, rel=1e-9)  # zero variance


def test_weights_are_normalized_when_not_summing_to_100():
    r = run_monte_carlo_simulation(
        make_instruments(), amount=10000,
        weights={"equities": 30, "bonds": 30, "crypto": 0, "cash": 0},  # sums to 60
        horizon_months=1, n_sims=200, rng=np.random.default_rng(3),
    )
    assert r.weights["equities"] == pytest.approx(0.5)
    assert r.weights["bonds"] == pytest.approx(0.5)


def test_higher_crypto_weight_increases_dispersion():
    low = run_monte_carlo_simulation(
        make_instruments(), amount=10000, weights={"equities": 90, "bonds": 10, "crypto": 0, "cash": 0},
        horizon_months=12, n_sims=2000, rng=np.random.default_rng(4),
    )
    high = run_monte_carlo_simulation(
        make_instruments(), amount=10000, weights={"equities": 0, "bonds": 0, "crypto": 100, "cash": 0},
        horizon_months=12, n_sims=2000, rng=np.random.default_rng(5),
    )
    assert (high.p90 - high.p10) > (low.p90 - low.p10)


def test_longer_horizon_widens_absolute_dispersion():
    short = run_monte_carlo_simulation(
        make_instruments(), amount=10000, weights={"equities": 100, "bonds": 0, "crypto": 0, "cash": 0},
        horizon_months=1, n_sims=1500, rng=np.random.default_rng(6),
    )
    long = run_monte_carlo_simulation(
        make_instruments(), amount=10000, weights={"equities": 100, "bonds": 0, "crypto": 0, "cash": 0},
        horizon_months=24, n_sims=1500, rng=np.random.default_rng(7),
    )
    assert (long.p90 - long.p10) > (short.p90 - short.p10)
