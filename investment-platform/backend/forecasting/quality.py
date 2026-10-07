"""
Quality score 0-100 per company, relative to its peer group, from the latest
annual report (ESEF/IFRS). A transparent ranking -- not a forecast and not a
recommendation. Banks are scored against banks with bank metrics; everyone
else against all non-bank companies (too few companies per sector in Athens
for sector-by-sector ranks).

Each component is the company's percentile rank in its peer group (0 = worst,
1 = best); the score is the mean of the available components x 100, and is
reported only when at least MIN_COMPONENTS are available.
"""
from __future__ import annotations

import pandas as pd

MIN_COMPONENTS = 3
# component -> higher is better?  (all ratios from app.services.market.normalize_fundamentals, + fcf_margin)
BANK_COMPONENTS = {"roe": True, "roa": True, "equity_ratio": True, "net_income_growth": True, "payout_ratio": True}
CORPORATE_COMPONENTS = {"roe": True, "operating_margin": True, "net_margin": True, "equity_ratio": True,
                        "current_ratio": True, "revenue_growth": True, "fcf_margin": True}


def _row(f: dict) -> dict:
    r, m = dict(f["ratios"]), f["metrics"]
    fcf = r.get("free_cash_flow")
    r["fcf_margin"] = fcf / m["revenue"] if fcf is not None and m.get("revenue") else None
    return r


def score(fundamentals: dict[str, dict]) -> list[dict]:
    rows = []
    for group, comps, members in (
        ("banks", BANK_COMPONENTS, {t: f for t, f in fundamentals.items() if f["sector"] == "Banks"}),
        ("non-banks", CORPORATE_COMPONENTS, {t: f for t, f in fundamentals.items() if f["sector"] != "Banks"}),
    ):
        if len(members) < 3:
            continue
        df = pd.DataFrame({t: _row(f) for t, f in members.items()}).T
        ranks = pd.DataFrame(index=df.index)
        for c, higher in comps.items():
            if c in df and df[c].notna().sum() >= 3:
                col = pd.to_numeric(df[c], errors="coerce")
                ranks[c] = col.rank(pct=True, ascending=higher)
        for t in df.index:
            comp = {c: float(ranks.loc[t, c]) for c in ranks.columns if pd.notna(ranks.loc[t, c])}
            if len(comp) < MIN_COMPONENTS:
                continue
            rows.append({"subject": t, "target": "quality_score", "horizon_days": 0,
                         "value": 100 * sum(comp.values()) / len(comp),
                         "details": {"peer_group": group, "peers": len(df), "fiscal_year_end": members[t]["fiscal_year_end"],
                                     "component_percentiles": comp,
                                     "inputs": {c: (None if pd.isna(df.loc[t, c]) else float(df.loc[t, c])) for c in comp}}})
    return rows
