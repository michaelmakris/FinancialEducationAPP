"""Macro context for the proposal: plain facts from today's indicator snapshots."""
from __future__ import annotations

DIRECTION_WORD = {"rising": "rising", "falling": "falling", "stable": "stable"}


def _snap(snaps: dict, key: str):
    s = snaps.get(key)
    return s if s is not None and s.payload_eligible else None


def facts(snaps: dict) -> list[dict]:
    """snaps: {indicator_id: IndicatorSnapshot}. Only payload-eligible (fresh) values are used."""
    out = []
    infl, dep = _snap(snaps, "hicp_yoy"), _snap(snaps, "deposit_rate")
    if infl and dep:
        real = dep.value - infl.value
        out.append({"topic": "cash", "indicators": ["hicp_yoy", "deposit_rate"], "values": {"inflation": infl.value, "deposit_rate": dep.value, "real_rate": real},
                    "text": f"Greek inflation is {infl.value:.1f}% while new term deposits pay about {dep.value:.2f}%, "
                            f"so cash {'loses' if real < 0 else 'gains'} about {abs(real):.1f}% a year in purchasing power."})
    dfr = _snap(snaps, "ecb_dfr")
    if dfr:
        out.append({"topic": "rates", "indicators": ["ecb_dfr"], "values": {"ecb_deposit_rate": dfr.value},
                    "text": f"The ECB deposit rate is {dfr.value:.2f}% and has been {DIRECTION_WORD[dfr.direction_90d]} over the last 90 days."})
    ggb, spread = _snap(snaps, "ggb_10y"), _snap(snaps, "spread_10y")
    if ggb and spread:
        out.append({"topic": "bonds", "indicators": ["ggb_10y", "spread_10y"], "values": {"greek_10y": ggb.value, "spread_bps": spread.value},
                    "text": f"Greek 10-year government bonds yield {ggb.value:.2f}%, {spread.value:.0f} basis points above Germany "
                            f"(spread {DIRECTION_WORD[spread.direction_90d]})."})
    unemp = _snap(snaps, "unemp")
    if unemp:
        out.append({"topic": "economy", "indicators": ["unemp"], "values": {"unemployment": unemp.value},
                    "text": f"Greek unemployment is {unemp.value:.1f}% ({DIRECTION_WORD[unemp.direction_90d]})."})
    fg = _snap(snaps, "crypto_fear_greed")
    if fg:
        mood = "fear" if fg.value < 45 else "greed" if fg.value > 55 else "neutral"
        out.append({"topic": "crypto", "indicators": ["crypto_fear_greed"], "values": {"fear_greed": fg.value},
                    "text": f"Crypto sentiment (Fear & Greed index) is {fg.value:.0f}/100: {mood}."})
    return out
