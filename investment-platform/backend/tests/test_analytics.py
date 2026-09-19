import pytest

from app.services import analytics


def make_fundamentals():
    return [
        dict(fiscal_year=2022, revenue=100.0, gross_profit=50.0, operating_income=20.0, net_income=15.0,
             ebitda=25.0, free_cash_flow=12.0, total_assets=200.0, total_equity=100.0, total_debt=50.0,
             current_assets=60.0, current_liabilities=40.0, interest_expense=2.0, shares_diluted=10.0, eps=1.5),
        dict(fiscal_year=2023, revenue=120.0, gross_profit=60.0, operating_income=25.0, net_income=18.0,
             ebitda=30.0, free_cash_flow=15.0, total_assets=220.0, total_equity=115.0, total_debt=52.0,
             current_assets=65.0, current_liabilities=42.0, interest_expense=2.1, shares_diluted=10.0, eps=1.8),
    ]


def test_growth_metrics_yoy():
    g = analytics.growth_metrics(make_fundamentals())
    assert g["revenue_growth_yoy"] == pytest.approx(0.20)
    assert g["eps_growth_yoy"] == pytest.approx(1.8 / 1.5 - 1)
    assert g["revenue_cagr"] == pytest.approx(0.20)  # single-year gap -> CAGR == YoY growth


def test_growth_metrics_none_with_insufficient_history():
    assert analytics.growth_metrics([make_fundamentals()[0]]) is None
    assert analytics.growth_metrics([]) is None


def test_valuation_ratios_basic_math():
    f = make_fundamentals()
    price = 50.0
    v = analytics.valuation_ratios(f, price)
    market_cap = price * 10.0
    assert v["market_cap"] == pytest.approx(market_cap)
    assert v["pe"] == pytest.approx(market_cap / 18.0)
    assert v["pb"] == pytest.approx(market_cap / 115.0)
    assert v["fcf_yield"] == pytest.approx(15.0 / market_cap)


def test_valuation_ratios_none_when_no_fundamentals():
    assert analytics.valuation_ratios([], 50.0) is None


def test_quality_metrics_margins():
    q = analytics.quality_metrics(make_fundamentals())
    assert q["gross_margin"] == pytest.approx(60.0 / 120.0)
    assert q["operating_margin"] == pytest.approx(25.0 / 120.0)
    assert q["roe"] == pytest.approx(18.0 / 115.0)


def test_balance_sheet_metrics():
    bs = analytics.balance_sheet_metrics(make_fundamentals())
    assert bs["debt_equity"] == pytest.approx(52.0 / 115.0)
    assert bs["current_ratio"] == pytest.approx(65.0 / 42.0)
    assert bs["interest_coverage"] == pytest.approx(25.0 / 2.1)


def test_handles_zero_denominators_gracefully():
    f = make_fundamentals()
    f[-1]["total_equity"] = 0
    f[-1]["current_liabilities"] = 0
    bs = analytics.balance_sheet_metrics(f)
    assert bs["debt_equity"] is None
    assert bs["current_ratio"] is None
