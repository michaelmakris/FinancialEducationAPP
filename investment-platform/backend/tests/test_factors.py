import pytest

from app.services import factors


def test_percentile_rank_higher_is_better():
    pool = [10, 20, 30, 40, 50]
    assert factors.percentile_rank(50, pool, True) == 100
    assert factors.percentile_rank(10, pool, True) == 0
    assert factors.percentile_rank(30, pool, True) == 50


def test_percentile_rank_lower_is_better_inverts():
    pool = [10, 20, 30, 40, 50]
    assert factors.percentile_rank(10, pool, False) == 100
    assert factors.percentile_rank(50, pool, False) == 0


def test_percentile_rank_none_for_missing_value_or_thin_pool():
    assert factors.percentile_rank(None, [1, 2, 3], True) is None
    assert factors.percentile_rank(5, [1], True) is None


def test_weighted_ignores_missing_and_renormalizes():
    rows = [("a", 100, 0.5), ("b", None, 0.3), ("c", 0, 0.2)]
    # only 'a' (w=0.5) and 'c' (w=0.2) are defined -> renormalized weights 5/7, 2/7
    expected = 100 * (0.5 / 0.7) + 0 * (0.2 / 0.7)
    assert factors._weighted(rows) == pytest.approx(expected)


def _synthetic_universe():
    """Three equities + one ETF market proxy, with clearly ordered fundamentals
    so we can assert the resulting rank order is sane."""
    import numpy as np

    def close_series(seed, drift, n=300):
        rng = np.random.default_rng(seed)
        dt = 1 / 252
        shocks = rng.normal((drift - 0.02) * dt, 0.2 * np.sqrt(dt), n)
        return list(100 * np.exp(np.cumsum(shocks)))

    def fundamentals(revenue, growth):
        rows = []
        rev = revenue
        for i, yr in enumerate([2022, 2023, 2024]):
            if i > 0:
                rev *= (1 + growth)
            rows.append(dict(
                fiscal_year=yr, revenue=rev, gross_profit=rev * 0.5, operating_income=rev * 0.2,
                net_income=rev * 0.15, ebitda=rev * 0.25, free_cash_flow=rev * 0.12,
                total_assets=rev * 2, total_equity=rev * 1.0, total_debt=rev * 0.4,
                current_assets=rev * 0.5, current_liabilities=rev * 0.3, interest_expense=rev * 0.02,
                shares_diluted=10.0, eps=(rev * 0.15) / 10.0,
            ))
        return rows

    instruments = [
        {"ticker": "CHEAP_HIGHGROWTH", "name": "A", "sector": "Tech", "asset_type": "equity",
         "close": close_series(1, 0.30), "fundamentals": fundamentals(50, 0.40)},
        {"ticker": "EXPENSIVE_SLOWGROWTH", "name": "B", "sector": "Tech", "asset_type": "equity",
         "close": [c * 20 for c in close_series(2, 0.05)], "fundamentals": fundamentals(50, 0.02)},
        {"ticker": "MID", "name": "C", "sector": "Tech", "asset_type": "equity",
         "close": close_series(3, 0.12), "fundamentals": fundamentals(50, 0.15)},
        {"ticker": "SPY", "name": "Market", "sector": "Broad Market", "asset_type": "etf",
         "close": close_series(4, 0.08), "fundamentals": []},
    ]
    return instruments


def test_universe_metrics_and_scores_end_to_end():
    instruments = _synthetic_universe()
    universe = factors.build_universe_metrics(instruments)
    assert set(universe.keys()) == {"CHEAP_HIGHGROWTH", "EXPENSIVE_SLOWGROWTH", "MID", "SPY"}
    assert universe["SPY"]["valuation"] is None  # ETFs have no fundamentals-based scoring

    scores = factors.compute_factor_scores(universe)
    # CHEAP_HIGHGROWTH has the same starting revenue/margins as the others but the
    # highest growth rate and by far the lowest price -> should rank at or near the
    # top on both value and growth.
    assert scores["CHEAP_HIGHGROWTH"]["category_scores"]["growth"] == 100.0
    assert scores["CHEAP_HIGHGROWTH"]["category_scores"]["value"] > scores["EXPENSIVE_SLOWGROWTH"]["category_scores"]["value"]
    # SPY has no value/quality/growth score (not an equity)
    assert scores["SPY"]["category_scores"]["value"] is None
    # every overall score, where defined, is within [0, 100]
    for s in scores.values():
        if s["overall"] is not None:
            assert 0 <= s["overall"] <= 100
