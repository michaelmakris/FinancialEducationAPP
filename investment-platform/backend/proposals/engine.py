"""
Allocation engine: pure functions over MarketInputs (gathered by service.py).

1. Strategic allocation for the profile (STRATEGIC, documented, sums to 100).
2. Crypto only when the questionnaire allows it; otherwise its weight goes to global equity.
3. Stressed markets (measured, not forecast): 5 points from equities to cash for profiles <= 5.
4. Volatility cap: expected volatility from the validated volatility model + measured
   correlations must stay inside the profile's band; if not, every risky sleeve is scaled
   down and the difference moves to cash (cash is ~riskless, so the scale is band / vol).
5. Stress tests and example instruments.
Every adjustment is recorded with its reason.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

SLEEVES = ["cash", "bonds", "global_equity", "greek_equity", "crypto"]
RISKY = ["bonds", "global_equity", "greek_equity", "crypto"]
SLEEVE_NAMES = {"cash": "Cash & deposits", "bonds": "Bonds", "global_equity": "Global shares",
                "greek_equity": "Greek shares", "crypto": "Crypto"}

STRATEGIC = {  # percent
    1: {"cash": 40, "bonds": 50, "global_equity": 10, "greek_equity": 0, "crypto": 0},
    2: {"cash": 25, "bonds": 50, "global_equity": 20, "greek_equity": 5, "crypto": 0},
    3: {"cash": 15, "bonds": 45, "global_equity": 30, "greek_equity": 10, "crypto": 0},
    4: {"cash": 10, "bonds": 35, "global_equity": 40, "greek_equity": 15, "crypto": 0},
    5: {"cash": 5, "bonds": 25, "global_equity": 47, "greek_equity": 20, "crypto": 3},
    6: {"cash": 5, "bonds": 15, "global_equity": 52, "greek_equity": 23, "crypto": 5},
    7: {"cash": 3, "bonds": 7, "global_equity": 57, "greek_equity": 25, "crypto": 8},
}
VOL_BAND = {1: 0.04, 2: 0.07, 3: 0.10, 4: 0.13, 5: 0.16, 6: 0.20, 7: 0.25}  # max expected annual volatility
STRESS_SHIFT = 5  # points from equities to cash when markets are measured as stressed

# Scenario shocks per sleeve (fractions). Hypothetical, round numbers -- not forecasts.
SCENARIOS = {
    "equity_crash": {"name": "Global equity crash", "shocks": {"cash": 0, "bonds": 0.03, "global_equity": -0.30, "greek_equity": -0.35, "crypto": -0.50}},
    "crypto_winter": {"name": "Crypto winter", "shocks": {"cash": 0, "bonds": 0, "global_equity": -0.05, "greek_equity": -0.05, "crypto": -0.70}},
    "rate_shock": {"name": "Interest-rate shock", "shocks": {"cash": 0, "bonds": -0.08, "global_equity": -0.10, "greek_equity": -0.12, "crypto": -0.20}},
}


@dataclass
class MarketInputs:
    sleeve_vol: dict[str, float]                         # annualised, from the volatility model / bond proxy
    correlations: dict[tuple[str, str], float]           # pairs of RISKY sleeves; missing -> 0
    conditions_label: str | None = None                  # calm | normal | stressed (measured)
    replay: dict | None = None                           # {"name", "period", "returns": {sleeve: r}}
    ideas: dict[str, list[dict]] = field(default_factory=dict)
    sources: dict = field(default_factory=dict)          # which proxy/model/version produced each number


def portfolio_vol(weights: dict[str, float], m: MarketInputs) -> float:
    """sqrt(w' Σ w) over risky sleeves; weights are fractions."""
    var = 0.0
    for a in RISKY:
        for b in RISKY:
            wa, wb = weights.get(a, 0.0), weights.get(b, 0.0)
            if not wa or not wb:
                continue
            va, vb = m.sleeve_vol.get(a, 0.0), m.sleeve_vol.get(b, 0.0)
            rho = 1.0 if a == b else m.correlations.get((a, b), m.correlations.get((b, a), 0.0))
            var += wa * wb * va * vb * rho
    return math.sqrt(max(var, 0.0))


def _round_to_100(weights: dict[str, float]) -> dict[str, float]:
    """Percent weights to one decimal that add up to exactly 100."""
    w = {k: round(v, 1) for k, v in weights.items()}
    drift = round(100 - sum(w.values()), 1)
    if drift:
        k = max(w, key=w.get)
        w[k] = round(w[k] + drift, 1)
    return w


def allocate(profile: int, crypto_allowed: bool, m: MarketInputs) -> dict:
    steps = []
    w = dict(STRATEGIC[profile])
    steps.append({"step": "strategic", "detail": f"starting mix for profile {profile}", "weights": dict(w)})

    if w["crypto"] and not crypto_allowed:
        w["global_equity"] += w["crypto"]
        steps.append({"step": "no_crypto", "detail": "crypto left out: it needs prior experience with volatile assets "
                      "(questionnaire) and an adventurous profile", "moved": w["crypto"]})
        w["crypto"] = 0

    if m.conditions_label == "stressed" and profile <= 5:
        eq = w["global_equity"] + w["greek_equity"]
        if eq > 0:
            shift = min(STRESS_SHIFT, eq)
            for k in ("global_equity", "greek_equity"):
                w[k] -= shift * w[k] / eq
            w["cash"] += shift
            steps.append({"step": "stressed_markets", "detail": f"Athens market measured as stressed: {shift} points "
                          "from shares to cash while volatility is high", "moved": shift})

    frac = {k: v / 100 for k, v in w.items()}
    vol = portfolio_vol(frac, m)
    band = VOL_BAND[profile]
    if vol > band:
        scale = band / vol
        moved = sum(frac[k] for k in RISKY) * (1 - scale)
        for k in RISKY:
            frac[k] *= scale
        frac["cash"] += moved
        steps.append({"step": "volatility_cap", "detail": f"expected volatility {vol:.1%} is above the {band:.0%} limit "
                      f"for this profile, so every risky part is scaled to {scale:.0%} and {moved * 100:.1f} points move to cash",
                      "moved": round(moved * 100, 1)})
        vol = portfolio_vol(frac, m)

    weights = _round_to_100({k: frac[k] * 100 for k in SLEEVES})
    return {"weights": weights, "expected_volatility": vol, "volatility_band": band, "steps": steps}


def stress(weights_pct: dict[str, float], m: MarketInputs) -> list[dict]:
    out = []
    scenarios = dict(SCENARIOS)
    if m.replay:
        scenarios["replay"] = {"name": m.replay["name"], "shocks": m.replay["returns"], "period": m.replay.get("period"),
                               "historical": True}
    for key, sc in scenarios.items():
        impact = sum(weights_pct.get(s, 0) / 100 * sc["shocks"].get(s, 0.0) for s in SLEEVES)
        out.append({"scenario": key, "name": sc["name"], "portfolio_return": impact,
                    "on_10000_eur": round(10000 * impact), "shocks": sc["shocks"],
                    "historical": sc.get("historical", False), "period": sc.get("period")})
    return out


def build(assessment: dict, m: MarketInputs) -> dict:
    alloc = allocate(assessment["profile"], assessment["crypto_allowed"], m)
    w = alloc["weights"]
    sleeves = []
    for s in SLEEVES:
        sleeves.append({"sleeve": s, "name": SLEEVE_NAMES[s], "weight_pct": w[s],
                        "expected_volatility": m.sleeve_vol.get(s) if s != "cash" else 0.0,
                        "ideas": m.ideas.get(s, []) if w[s] > 0 else []})
    stresses = stress(w, m)
    worst = min(stresses, key=lambda x: x["portfolio_return"])
    return {"profile": assessment["profile"], "profile_name": assessment["profile_name"], "allocation": sleeves,
            "expected_volatility": alloc["expected_volatility"], "volatility_band": alloc["volatility_band"],
            "adjustments": alloc["steps"], "stress_tests": stresses, "worst_scenario": worst["name"],
            "worst_scenario_return": worst["portfolio_return"], "market_conditions": m.conditions_label,
            "sources": m.sources}
