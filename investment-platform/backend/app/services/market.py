"""
Calculations for the real-market-data API (/v1). Pure functions over plain
(date, value) series and bar dicts -- no DB access -- so they are unit tested
directly. Returns use adjusted closes (dividends and splits) where available.
"""
from __future__ import annotations

import datetime
import math
from bisect import bisect_right
from typing import Iterable, Optional

Series = list[tuple[datetime.date, float]]

# Calendar-day lookbacks; "value at window start" = last observation on/before the target date.
RETURN_WINDOWS = {"1w": 7, "1m": 30, "3m": 91, "6m": 182, "1y": 365, "3y": 1095, "5y": 1826}


def value_on_or_before(series: Series, target: datetime.date) -> Optional[tuple[datetime.date, float]]:
    i = bisect_right([d for d, _ in series], target)
    return series[i - 1] if i else None


def period_returns(series: Series, as_of: datetime.date | None = None) -> dict[str, Optional[float]]:
    """Simple returns over RETURN_WINDOWS plus year-to-date, as fractions (0.05 = +5%).
    A window is None when the series does not reach back that far."""
    if not series:
        return {k: None for k in [*RETURN_WINDOWS, "ytd"]}
    as_of = as_of or series[-1][0]
    last = value_on_or_before(series, as_of)
    out: dict[str, Optional[float]] = {}
    targets = {k: as_of - datetime.timedelta(days=n) for k, n in RETURN_WINDOWS.items()}
    targets["ytd"] = datetime.date(as_of.year - 1, 12, 31)
    for key, target in targets.items():
        base = value_on_or_before(series, target)
        # require the series to actually cover the window start (not just a later first point)
        out[key] = (last[1] / base[1] - 1) if last and base and base[1] and series[0][0] <= target else None
    return out


def annualized_volatility(series: Series, days: int = 365, as_of: datetime.date | None = None) -> Optional[float]:
    """Std-dev of log returns over the last `days`, annualised by the series' own
    observation frequency (~252/yr for stocks, 365/yr for crypto)."""
    if len(series) < 3:
        return None
    as_of = as_of or series[-1][0]
    window = [v for d, v in series if as_of - datetime.timedelta(days=days) <= d <= as_of and v > 0]
    if len(window) < 20:
        return None
    rets = [math.log(b / a) for a, b in zip(window, window[1:])]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    per_year = len(rets) / (days / 365.25)
    return math.sqrt(var * per_year)


def max_drawdown(series: Series, days: int | None = 365, as_of: datetime.date | None = None) -> Optional[float]:
    """Worst peak-to-trough fall within the window, as a negative fraction."""
    if not series:
        return None
    as_of = as_of or series[-1][0]
    vals = [v for d, v in series if (days is None or d >= as_of - datetime.timedelta(days=days)) and d <= as_of]
    if len(vals) < 2:
        return None
    peak, worst = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1)
    return worst


def resample_bars(bars: list[dict], interval: str) -> list[dict]:
    """daily -> weekly (ISO week) or monthly OHLCV. Each bar dict has date/open/high/low/close/volume/adj_close."""
    if interval == "daily":
        return bars

    def key(d: datetime.date):
        if interval == "weekly":
            y, w, _ = d.isocalendar()
            return (y, w)
        return (d.year, d.month)

    out: list[dict] = []
    for b in bars:
        if out and key(out[-1]["date"]) == key(b["date"]):
            cur = out[-1]
            cur["high"] = _max(cur["high"], b["high"])
            cur["low"] = _min(cur["low"], b["low"])
            cur["close"], cur["adj_close"], cur["date"] = b["close"], b["adj_close"], b["date"]
            cur["volume"] = (cur["volume"] or 0) + (b["volume"] or 0) if (cur["volume"] is not None or b["volume"] is not None) else None
        else:
            out.append(dict(b))
    return out


def _max(a, b):
    return b if a is None else a if b is None else max(a, b)


def _min(a, b):
    return b if a is None else a if b is None else min(a, b)


def rebase_compare(series_by_key: dict[str, Series], start: datetime.date | None = None,
                   end: datetime.date | None = None) -> tuple[datetime.date | None, list[dict]]:
    """Align several series (different calendars: crypto trades 7 days a week, Athens
    5) on the union of their dates, carry each value forward, and rebase all to
    100 at the first date where every series has a value.
    Returns (base_date, [{date, <key>: value, ...}])."""
    clipped = {k: [(d, v) for d, v in s if (start is None or d >= start) and (end is None or d <= end) and v]
               for k, s in series_by_key.items()}
    if any(not s for s in clipped.values()):
        return None, []
    base_date = max(s[0][0] for s in clipped.values())
    dates = sorted({d for s in clipped.values() for d, _ in s if d >= base_date})
    lookups = {k: dict(s) for k, s in clipped.items()}
    last = {k: value_on_or_before(s, base_date)[1] for k, s in clipped.items()}
    base = dict(last)
    rows = []
    for d in dates:
        row: dict = {"date": d}
        for k in clipped:
            if d in lookups[k]:
                last[k] = lookups[k][d]
            row[k] = round(100.0 * last[k] / base[k], 4)
        rows.append(row)
    return base_date, rows


# ---------------------------------------------------------------------------
# Fundamentals: raw ESEF/IFRS facts -> comparable metrics per fiscal year
# ---------------------------------------------------------------------------
# metric -> IFRS concepts in order of preference (issuers tag differently; banks
# use interest/fee lines instead of Revenue).
FUNDAMENTAL_CONCEPTS: dict[str, list[str]] = {
    "revenue": ["Revenue", "RevenueFromContractsWithCustomers"],
    "gross_profit": ["GrossProfit"],
    "operating_profit": ["ProfitLossFromOperatingActivities"],
    "profit_before_tax": ["ProfitLossBeforeTax"],
    "net_income": ["ProfitLossAttributableToOwnersOfParent", "ProfitLossAttributableToOrdinaryEquityHoldersOfParentEntity", "ProfitLoss"],
    "eps_basic": ["BasicEarningsLossPerShare"],
    "eps_diluted": ["DilutedEarningsLossPerShare"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "equity": ["EquityAttributableToOwnersOfParent", "Equity"],
    "current_assets": ["CurrentAssets"],
    "current_liabilities": ["CurrentLiabilities"],
    "cash": ["CashAndCashEquivalents"],
    "operating_cash_flow": ["CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "dividends_paid": ["DividendsPaidClassifiedAsFinancingActivities"],
    "depreciation_amortisation": ["DepreciationAndAmortisationExpense"],
    "finance_costs": ["FinanceCosts"],
    "weighted_avg_shares": ["WeightedAverageShares"],
    # banks
    "interest_income": ["RevenueFromInterest", "InterestRevenueCalculatedUsingEffectiveInterestMethod"],
    "interest_expense": ["InterestExpense"],
    "net_interest_income": ["InterestRevenueExpense"],
    "net_fee_income": ["FeeAndCommissionIncomeExpense"],
    "loans_to_customers": ["LoansAndAdvancesToCustomers"],
    "customer_deposits": ["DepositsFromCustomers"],
}
_FLOW_METRICS = {"revenue", "gross_profit", "operating_profit", "profit_before_tax", "net_income", "eps_basic",
                 "eps_diluted", "operating_cash_flow", "capex", "dividends_paid", "depreciation_amortisation",
                 "finance_costs", "weighted_avg_shares", "interest_income", "interest_expense",
                 "net_interest_income", "net_fee_income"}
_OUTFLOWS = {"capex", "dividends_paid"}  # sign conventions vary by issuer; report as positive amounts


def _ratio(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def normalize_fundamentals(facts: Iterable[dict]) -> list[dict]:
    """facts: [{concept, period_start, period_end, value, unit}] for one company.
    Returns one dict per fiscal year (newest first) with FUNDAMENTAL_CONCEPTS
    metrics, the concept each came from, and derived ratios."""
    flows: dict[tuple[str, datetime.date], float] = {}
    stocks: dict[tuple[str, datetime.date], float] = {}
    year_ends: set[datetime.date] = set()
    for f in facts:
        if f["period_start"] is None:
            stocks[(f["concept"], f["period_end"])] = f["value"]
        elif 330 <= (f["period_end"] - f["period_start"]).days <= 400:  # annual periods only
            flows[(f["concept"], f["period_end"])] = f["value"]
            year_ends.add(f["period_end"])
    years = []
    for end in sorted(year_ends, reverse=True):
        metrics: dict[str, Optional[float]] = {}
        sources: dict[str, str] = {}
        for metric, concepts in FUNDAMENTAL_CONCEPTS.items():
            table = flows if metric in _FLOW_METRICS else stocks
            for c in concepts:
                if (c, end) in table:
                    v = table[(c, end)]
                    metrics[metric] = abs(v) if metric in _OUTFLOWS else v
                    sources[metric] = c
                    break
            else:
                metrics[metric] = None
        years.append({"fiscal_year_end": end, "metrics": metrics, "sources": sources})

    for i, y in enumerate(years):
        m = y["metrics"]
        prev = years[i + 1]["metrics"] if i + 1 < len(years) else {}
        avg_equity = ((m["equity"] + prev["equity"]) / 2) if m["equity"] is not None and prev.get("equity") is not None else m["equity"]
        fcf = m["operating_cash_flow"] - m["capex"] if m["operating_cash_flow"] is not None and m["capex"] is not None else None
        y["ratios"] = {
            "roe": _ratio(m["net_income"], avg_equity),
            "roa": _ratio(m["net_income"], m["total_assets"]),
            "net_margin": _ratio(m["net_income"], m["revenue"]),
            "operating_margin": _ratio(m["operating_profit"], m["revenue"]),
            "gross_margin": _ratio(m["gross_profit"], m["revenue"]),
            "equity_ratio": _ratio(m["equity"], m["total_assets"]),
            "current_ratio": _ratio(m["current_assets"], m["current_liabilities"]),
            "free_cash_flow": fcf,
            "payout_ratio": _ratio(m["dividends_paid"], m["net_income"]) if (m["net_income"] or 0) > 0 else None,
            "loan_to_deposit": _ratio(m["loans_to_customers"], m["customer_deposits"]),
            "revenue_growth": _ratio(m["revenue"], prev.get("revenue")) - 1 if _ratio(m["revenue"], prev.get("revenue")) is not None else None,
            "net_income_growth": (_ratio(m["net_income"], prev.get("net_income")) - 1)
            if _ratio(m["net_income"], prev.get("net_income")) is not None and (prev.get("net_income") or 0) > 0 else None,
        }
    return years


def market_ratios(latest_year: dict | None, price: float | None) -> dict[str, Optional[float]]:
    """Price-based ratios from the latest fiscal year. Market cap uses the year's
    weighted-average share count, so treat it as an approximation."""
    if not latest_year or not price:
        return {"pe": None, "pb": None, "market_cap_approx": None, "dividend_yield": None}
    m = latest_year["metrics"]
    eps = m.get("eps_basic")
    shares = m.get("weighted_avg_shares")
    mcap = price * shares if shares else None
    return {
        "pe": price / eps if eps and eps > 0 else None,
        "pb": _ratio(mcap, m.get("equity")) if mcap else None,
        "market_cap_approx": mcap,
        "dividend_yield": _ratio(m.get("dividends_paid"), mcap) if mcap else None,
    }
