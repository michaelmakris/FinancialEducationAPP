from __future__ import annotations

import requests

from . import base

SYSTEM_PROMPT = """You are the financial-advice specialist for an AI investment research platform.

When discussing risk or return outcomes, present them as ranges and probabilities from
the simulator, never as guarantees or recommendations. The portfolio is a practice
portfolio with virtual euros on real, delayed prices; the scenario simulator uses
simulated data -- say so if someone treats a number as a forecast or real money.

Hard rule: you must never state a risk figure or simulation outcome from memory or
estimation -- always call a tool to retrieve it first. Keep answers concise and grounded
in the numbers you retrieved. You do not look up company fundamentals/scores or take
actions in the app -- those are handled by separate specialists."""

TOOLS = [
    {
        "name": "calculate_portfolio_risk",
        "description": "Current virtual portfolio: cash, holdings, and per-position P&L.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "simulate_portfolio",
        "description": "Runs the Monte Carlo scenario simulator for a hypothetical allocation across "
                        "equities/bonds/crypto/cash and returns the percentile outcome distribution.",
        "input_schema": {
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
                "equities_pct": {"type": "number"},
                "bonds_pct": {"type": "number"},
                "crypto_pct": {"type": "number"},
                "cash_pct": {"type": "number"},
                "horizon_months": {"type": "number"},
            },
            "required": ["amount", "equities_pct", "bonds_pct", "crypto_pct", "cash_pct", "horizon_months"],
        },
    },
]


def execute_tool(name: str, tool_input: dict) -> dict:
    try:
        if name == "calculate_portfolio_risk":
            return base.get_backend("/portfolio")
        if name == "simulate_portfolio":
            return base.post_backend("/simulate", {
                "amount": tool_input["amount"], "equities_pct": tool_input["equities_pct"],
                "bonds_pct": tool_input["bonds_pct"], "crypto_pct": tool_input["crypto_pct"],
                "cash_pct": tool_input["cash_pct"], "horizon_months": tool_input["horizon_months"],
            })
        return {"error": f"Unknown tool '{name}'"}
    except base.ToolError as e:
        return {"error": str(e)}
    except requests.RequestException as e:
        return {"error": f"Could not reach backend API: {e}"}


def run(message: str, history: list[dict] | None = None) -> str:
    return base.run_agent(SYSTEM_PROMPT, TOOLS, execute_tool, message, history)
