"""
Cross-sectional factor scoring. Every metric is standardized against the
current universe via percentile rank -- never assigned an arbitrary score.
Mirrors computeFactorScores() in the browser demo (investment-platform-demo.jsx).
"""
from __future__ import annotations

from typing import Optional, Sequence

from . import analytics, risk


def percentile_rank(value: Optional[float], all_values: Sequence[Optional[float]], higher_is_better: bool = True) -> Optional[float]:
    valid = [v for v in all_values if v is not None]
    if value is None or len(valid) < 2:
        return None
    sorted_vals = sorted(valid)
    count_below = sum(1 for v in sorted_vals if v < value)
    pct = (count_below / (len(sorted_vals) - 1)) * 100
    pct = max(0.0, min(100.0, pct))
    return pct if higher_is_better else 100 - pct


def _avg_defined(values):
    defined = [v for v in values if v is not None]
    return sum(defined) / len(defined) if defined else None


def _weighted(rows):
    """rows: list of (label, percentile_or_None, weight_float)"""
    defined = [r for r in rows if r[1] is not None]
    if not defined:
        return None
    total_w = sum(r[2] for r in defined)
    return sum(r[1] * (r[2] / total_w) for r in defined)


def build_universe_metrics(instruments: list[dict], spy_ticker: str = "SPY") -> dict:
    """instruments: [{ticker, name, sector, asset_type, close: [...], fundamentals: [...]}]"""
    by_ticker = {i["ticker"]: i for i in instruments}
    market_close = by_ticker[spy_ticker]["close"] if spy_ticker in by_ticker else None

    out = {}
    for inst in instruments:
        price = inst["close"][-1]
        is_market = inst["ticker"] == spy_ticker
        mkt = risk.market_stats(inst["close"], None if is_market else market_close)
        is_eq = inst["asset_type"] == "equity"
        val = analytics.valuation_ratios(inst["fundamentals"], price) if is_eq else None
        qual = analytics.quality_metrics(inst["fundamentals"]) if is_eq else None
        growth = analytics.growth_metrics(inst["fundamentals"]) if is_eq else None
        bs = analytics.balance_sheet_metrics(inst["fundamentals"]) if is_eq else None
        out[inst["ticker"]] = {
            "ticker": inst["ticker"], "name": inst["name"], "sector": inst["sector"],
            "asset_type": inst["asset_type"], "price": price, "market": mkt,
            "valuation": val, "quality": qual, "growth": growth, "balance_sheet": bs,
            "fundamentals": inst["fundamentals"],
        }
    return out


def compute_factor_scores(universe_metrics: dict) -> dict:
    all_m = list(universe_metrics.values())
    equities = [m for m in all_m if m["asset_type"] == "equity"]

    pools = {
        "inv_pe": [m["valuation"]["pe"] if m["valuation"] and m["valuation"]["pe"] and m["valuation"]["pe"] > 0 else None for m in equities],
        "inv_pb": [m["valuation"]["pb"] if m["valuation"] and m["valuation"]["pb"] and m["valuation"]["pb"] > 0 else None for m in equities],
        "inv_ps": [m["valuation"]["ps"] if m["valuation"] and m["valuation"]["ps"] and m["valuation"]["ps"] > 0 else None for m in equities],
        "inv_ev_ebitda": [m["valuation"]["ev_ebitda"] if m["valuation"] and m["valuation"]["ev_ebitda"] and m["valuation"]["ev_ebitda"] > 0 else None for m in equities],
        "fcf_yield": [m["valuation"]["fcf_yield"] if m["valuation"] else None for m in equities],
        "roe": [m["quality"]["roe"] if m["quality"] else None for m in equities],
        "roa": [m["quality"]["roa"] if m["quality"] else None for m in equities],
        "gross_margin": [m["quality"]["gross_margin"] if m["quality"] else None for m in equities],
        "op_margin": [m["quality"]["operating_margin"] if m["quality"] else None for m in equities],
        "fcf_margin": [m["quality"]["fcf_margin"] if m["quality"] else None for m in equities],
        "rev_growth": [m["growth"]["revenue_growth_yoy"] if m["growth"] else None for m in equities],
        "eps_growth": [m["growth"]["eps_growth_yoy"] if m["growth"] else None for m in equities],
        "fcf_growth": [m["growth"]["fcf_growth_yoy"] if m["growth"] else None for m in equities],
        "cagr": [m["growth"]["revenue_cagr"] if m["growth"] else None for m in equities],
        "r1m": [m["market"].return_1m for m in all_m],
        "r3m": [m["market"].return_3m for m in all_m],
        "r6m": [m["market"].return_6m for m in all_m],
        "r12m": [m["market"].return_12m for m in all_m],
        "inv_vol": [m["market"].volatility for m in all_m],
        "inv_dd": [-m["market"].max_drawdown if m["market"].max_drawdown is not None else None for m in all_m],
        "inv_var": [-m["market"].var95 if m["market"].var95 is not None else None for m in all_m],
        "sharpe": [m["market"].sharpe for m in all_m],
        "inv_beta": [abs(m["market"].beta) if m["market"].beta is not None else None for m in all_m],
    }

    scores = {}
    for m in all_m:
        is_eq = m["asset_type"] == "equity"
        breakdown = {"value": [], "quality": [], "growth": [], "momentum": [], "risk": [], "macro": []}

        if is_eq and m["valuation"] and m["quality"] and m["growth"]:
            v, q, g = m["valuation"], m["quality"], m["growth"]
            breakdown["value"] = [
                ("P/E (inverse)", percentile_rank(v["pe"] if v["pe"] and v["pe"] > 0 else None, pools["inv_pe"], False), 0.25),
                ("P/B (inverse)", percentile_rank(v["pb"] if v["pb"] and v["pb"] > 0 else None, pools["inv_pb"], False), 0.20),
                ("P/S (inverse)", percentile_rank(v["ps"] if v["ps"] and v["ps"] > 0 else None, pools["inv_ps"], False), 0.20),
                ("EV/EBITDA (inverse)", percentile_rank(v["ev_ebitda"] if v["ev_ebitda"] and v["ev_ebitda"] > 0 else None, pools["inv_ev_ebitda"], False), 0.20),
                ("FCF yield", percentile_rank(v["fcf_yield"], pools["fcf_yield"], True), 0.15),
            ]
            breakdown["quality"] = [
                ("ROE", percentile_rank(q["roe"], pools["roe"], True), 0.25),
                ("ROA", percentile_rank(q["roa"], pools["roa"], True), 0.20),
                ("Gross margin", percentile_rank(q["gross_margin"], pools["gross_margin"], True), 0.20),
                ("Operating margin", percentile_rank(q["operating_margin"], pools["op_margin"], True), 0.20),
                ("FCF margin", percentile_rank(q["fcf_margin"], pools["fcf_margin"], True), 0.15),
            ]
            breakdown["growth"] = [
                ("Revenue growth YoY", percentile_rank(g["revenue_growth_yoy"], pools["rev_growth"], True), 0.30),
                ("EPS growth YoY", percentile_rank(g["eps_growth_yoy"], pools["eps_growth"], True), 0.25),
                ("FCF growth YoY", percentile_rank(g["fcf_growth_yoy"], pools["fcf_growth"], True), 0.20),
                ("Revenue 3Y CAGR", percentile_rank(g["revenue_cagr"], pools["cagr"], True), 0.25),
            ]

        mkt = m["market"]
        breakdown["momentum"] = [
            ("1M return", percentile_rank(mkt.return_1m, pools["r1m"], True), 0.15),
            ("3M return", percentile_rank(mkt.return_3m, pools["r3m"], True), 0.25),
            ("6M return", percentile_rank(mkt.return_6m, pools["r6m"], True), 0.30),
            ("12M return", percentile_rank(mkt.return_12m, pools["r12m"], True), 0.30),
        ]
        breakdown["risk"] = [
            ("Volatility (inverse)", percentile_rank(mkt.volatility, pools["inv_vol"], False), 0.25),
            ("Max drawdown (inverse)", percentile_rank(-mkt.max_drawdown if mkt.max_drawdown is not None else None, pools["inv_dd"], False), 0.25),
            ("95% VaR (inverse)", percentile_rank(-mkt.var95 if mkt.var95 is not None else None, pools["inv_var"], False), 0.20),
            ("Sharpe ratio", percentile_rank(mkt.sharpe, pools["sharpe"], True), 0.30),
        ]
        breakdown["macro"] = [
            ("Sensitivity to market (|beta|, inverse)",
             percentile_rank(abs(mkt.beta) if mkt.beta is not None else None, pools["inv_beta"], False), 1.0),
        ]

        category_scores = {
            "value": _weighted(breakdown["value"]) if is_eq else None,
            "quality": _weighted(breakdown["quality"]) if is_eq else None,
            "growth": _weighted(breakdown["growth"]) if is_eq else None,
            "momentum": _weighted(breakdown["momentum"]),
            "risk": _weighted(breakdown["risk"]),
            "macro": _weighted(breakdown["macro"]),
        }
        overall = _avg_defined(category_scores.values())
        scores[m["ticker"]] = {"category_scores": category_scores, "overall": overall, "breakdown": breakdown, "asset_type": m["asset_type"]}
    return scores
