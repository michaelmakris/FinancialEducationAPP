"""
Transaction costs for the practice portfolio -- ILLUSTRATIVE ranges for retail investors
in Greece/the EU, so customers see that every trade costs something and that small or
frequent trades cost the most. Real costs depend on the broker; taxes (on gains, dividends
or share sales) are NOT included.

Per market and broker profile:
  commission_pct, commission_min   the broker's fee: a % of the trade, at least a minimum (EUR)
  exchange_pct                     exchange / clearing / settlement fees passed on
  spread_pct                       half the bid/ask spread: buying above, selling below the mid price
  fx_pct                           currency conversion for non-EUR shares (US)

Edit the numbers here; everything else (trades, estimates, the app) reads them.
"""
from __future__ import annotations

PROFILES = {
    "none": {"en": "No costs (ideal world)", "el": "Χωρίς κόστη (ιδανικός κόσμος)"},
    "low": {"en": "Low-cost online broker", "el": "Φθηνός online χρηματιστής"},
    "typical": {"en": "Typical bank broker", "el": "Τυπικός τραπεζικός χρηματιστής"},
    "high": {"en": "Expensive broker", "el": "Ακριβός χρηματιστής"},
}
RANGE = ("low", "typical", "high")

# market -> profile -> (commission_pct, commission_min_eur, exchange_pct, spread_pct, fx_pct)
TABLE = {
    "athens": {"low": (0.10, 3, 0.03, 0.10, 0.0), "typical": (0.25, 8, 0.03, 0.20, 0.0), "high": (0.50, 15, 0.03, 0.40, 0.0)},
    "europe": {"low": (0.05, 2, 0.01, 0.03, 0.0), "typical": (0.15, 7, 0.01, 0.05, 0.0), "high": (0.35, 20, 0.01, 0.15, 0.0)},
    "us": {"low": (0.05, 1, 0.00, 0.02, 0.10), "typical": (0.15, 7, 0.00, 0.05, 0.25), "high": (0.35, 20, 0.00, 0.10, 1.00)},
    "etf": {"low": (0.05, 2, 0.01, 0.05, 0.0), "typical": (0.15, 7, 0.01, 0.10, 0.0), "high": (0.35, 20, 0.01, 0.25, 0.0)},
    "crypto": {"low": (0.10, 0, 0.00, 0.05, 0.0), "typical": (0.50, 0, 0.00, 0.15, 0.0), "high": (1.50, 0, 0.00, 0.50, 0.0)},
}


def estimate(market: str, amount_eur: float, profile: str) -> dict:
    """Costs of one trade of `amount_eur` (EUR), by component; 'total' is what leaves the customer."""
    zero = {"commission": 0.0, "exchange": 0.0, "spread": 0.0, "fx": 0.0, "total": 0.0, "pct": 0.0}
    if profile == "none" or market not in TABLE or amount_eur <= 0:
        return dict(zero)
    c_pct, c_min, ex_pct, sp_pct, fx_pct = TABLE[market][profile]
    out = {
        "commission": max(amount_eur * c_pct / 100, c_min),
        "exchange": amount_eur * ex_pct / 100,
        "spread": amount_eur * sp_pct / 100,
        "fx": amount_eur * fx_pct / 100,
    }
    out = {k: round(v, 2) for k, v in out.items()}
    out["total"] = round(sum(out.values()), 2)
    out["pct"] = out["total"] / amount_eur
    return out


def ranges(market: str, amount_eur: float) -> dict:
    """The same trade under the low / typical / high profiles."""
    return {p: estimate(market, amount_eur, p) for p in RANGE}
