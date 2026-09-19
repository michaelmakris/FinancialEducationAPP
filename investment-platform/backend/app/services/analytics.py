"""
Ratio calculations from fundamentals rows. A "fundamentals row" is a dict with
the fields produced by scripts/generate_dataset.py / the SEC ingestion
pipeline's normalized output: revenue, gross_profit, operating_income,
net_income, ebitda, free_cash_flow, total_assets, total_equity, total_debt,
current_assets, current_liabilities, interest_expense, shares_diluted, eps.
"""
from __future__ import annotations

from typing import Optional, Sequence


def latest_fundamentals(fundamentals: Sequence[dict]) -> Optional[dict]:
    return fundamentals[-1] if fundamentals else None


def growth_metrics(fundamentals: Sequence[dict]) -> Optional[dict]:
    if not fundamentals or len(fundamentals) < 2:
        return None
    last, prev, first = fundamentals[-1], fundamentals[-2], fundamentals[0]
    years = len(fundamentals) - 1

    def cagr(end_v, start_v, n):
        if start_v and end_v and start_v > 0 and end_v > 0:
            return (end_v / start_v) ** (1 / n) - 1
        return None

    return {
        "revenue_growth_yoy": (last["revenue"] / prev["revenue"] - 1) if prev["revenue"] > 0 else None,
        "eps_growth_yoy": (last["eps"] / prev["eps"] - 1) if prev["eps"] > 0 else None,
        "fcf_growth_yoy": (last["free_cash_flow"] / prev["free_cash_flow"] - 1) if prev["free_cash_flow"] > 0 else None,
        "revenue_cagr": cagr(last["revenue"], first["revenue"], years),
    }


def valuation_ratios(fundamentals: Sequence[dict], price: float) -> Optional[dict]:
    f = latest_fundamentals(fundamentals)
    if not f:
        return None
    market_cap = price * f["shares_diluted"]
    enterprise_value = market_cap + f["total_debt"] - f["current_assets"] * 0.4
    return {
        "market_cap": market_cap,
        "pe": market_cap / f["net_income"] if f["net_income"] > 0 else None,
        "pb": market_cap / f["total_equity"] if f["total_equity"] > 0 else None,
        "ps": market_cap / f["revenue"] if f["revenue"] > 0 else None,
        "ev_ebitda": enterprise_value / f["ebitda"] if f["ebitda"] > 0 else None,
        "fcf_yield": f["free_cash_flow"] / market_cap if market_cap > 0 else None,
    }


def quality_metrics(fundamentals: Sequence[dict]) -> Optional[dict]:
    f = latest_fundamentals(fundamentals)
    if not f:
        return None
    return {
        "roe": f["net_income"] / f["total_equity"] if f["total_equity"] > 0 else None,
        "roa": f["net_income"] / f["total_assets"] if f["total_assets"] > 0 else None,
        "gross_margin": f["gross_profit"] / f["revenue"] if f["revenue"] > 0 else None,
        "operating_margin": f["operating_income"] / f["revenue"] if f["revenue"] > 0 else None,
        "fcf_margin": f["free_cash_flow"] / f["revenue"] if f["revenue"] > 0 else None,
    }


def balance_sheet_metrics(fundamentals: Sequence[dict]) -> Optional[dict]:
    f = latest_fundamentals(fundamentals)
    if not f:
        return None
    return {
        "debt_equity": f["total_debt"] / f["total_equity"] if f["total_equity"] > 0 else None,
        "net_debt_to_ebitda": (f["total_debt"] - f["current_assets"] * 0.3) / f["ebitda"] if f["ebitda"] > 0 else None,
        "interest_coverage": f["operating_income"] / f["interest_expense"] if f["interest_expense"] > 0 else None,
        "current_ratio": f["current_assets"] / f["current_liabilities"] if f["current_liabilities"] > 0 else None,
    }
