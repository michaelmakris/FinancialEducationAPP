"""
How the customer's practice portfolio compares with the proposal.

The practice portfolio trades real instruments (Athens, European and US shares, ETFs,
crypto), so holdings are mapped to the proposal's sleeves: Athens shares -> Greek
shares, other shares and equity ETFs -> global shares, bond ETFs -> bonds, crypto ->
crypto. Its volatility is measured from the holdings' daily returns on the dates they
all traded.
"""
from __future__ import annotations

import math

import numpy as np

from .engine import SLEEVE_NAMES

CONCENTRATION_LIMIT = 0.25   # one holding above 25% of the portfolio
DEVIATION_FLAG = 10.0        # points away from the proposal per sleeve


def sleeve_of(asset_type: str, sector: str, market: str = "") -> str:
    if asset_type == "crypto":
        return "crypto"
    if "bond" in (sector or "").lower():
        return "bonds"
    if market == "athens":
        return "greek_equity"
    return "global_equity"


def analyse(portfolio: dict, instruments: dict[str, dict], target_pct: dict[str, float]) -> dict:
    """portfolio: PortfolioOut-shaped dict; instruments: {ticker: {asset_type, sector, market, close: [...]}}
    with every `close` list on the same dates."""
    total = portfolio["total_value"]
    if total <= 0:
        return {"empty": True}
    by_sleeve = {s: 0.0 for s in target_pct}
    by_sleeve["cash"] = portfolio["cash"]
    holdings = []
    for p in portfolio["positions"]:
        meta = instruments.get(p["ticker"], {"asset_type": "equity", "sector": ""})
        s = sleeve_of(meta["asset_type"], meta.get("sector", ""), meta.get("market", ""))
        by_sleeve[s] = by_sleeve.get(s, 0.0) + p["value"]
        holdings.append({"ticker": p["ticker"], "sleeve": s, "weight": p["value"] / total, "value": p["value"]})
    weights_pct = {s: round(100 * v / total, 1) for s, v in by_sleeve.items()}

    # volatility from the holdings' own daily returns (cash = 0)
    vol = 0.0
    if holdings:
        series = [instruments[h["ticker"]]["close"][-253:] for h in holdings if h["ticker"] in instruments]
        n = min(len(s) for s in series) if series else 0
        if n > 30:
            rets = np.array([np.diff(np.log(np.array(s[-n:], dtype=float))) for s in series])
            cov = np.atleast_2d(np.cov(rets)) * 252
            w = np.array([h["weight"] for h in holdings if h["ticker"] in instruments])
            vol = float(math.sqrt(max(w @ cov @ w, 0.0)))

    flags = []
    top = sorted(holdings, key=lambda h: -h["weight"])
    if top and top[0]["weight"] > CONCENTRATION_LIMIT:
        flags.append({"code": "concentration", "text": f"{top[0]['ticker']} is {top[0]['weight']:.0%} of your practice "
                      f"portfolio; one holding above {CONCENTRATION_LIMIT:.0%} makes results depend heavily on it"})
    for s, tgt in target_pct.items():
        diff = weights_pct.get(s, 0.0) - tgt
        if abs(diff) >= DEVIATION_FLAG:
            flags.append({"code": f"{s}_{'over' if diff > 0 else 'under'}",
                          "text": f"{SLEEVE_NAMES[s]}: {weights_pct.get(s, 0.0):.0f}% of it vs {tgt:.0f}% in the proposal"})
    if weights_pct.get("crypto", 0) > 0 and target_pct.get("crypto", 0) == 0:
        flags.append({"code": "crypto_outside_profile", "text": "you hold crypto although the proposal for your profile has none"})
    return {"empty": False, "total_value": total, "weights_pct": weights_pct, "positions": len(holdings),
            "largest_holding": {"ticker": top[0]["ticker"], "weight": top[0]["weight"]} if top else None,
            "top3_weight": sum(h["weight"] for h in top[:3]), "measured_volatility": vol,
            "deviation_pct": {s: round(weights_pct.get(s, 0.0) - t, 1) for s, t in target_pct.items()},
            "flags": flags}
