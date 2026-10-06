from __future__ import annotations

import requests

from . import base

SYSTEM_PROMPT = """You are the analysis specialist for an AI investment research platform.

Hard rule: you must never state a price, ratio, score, or comparison from memory or
estimation -- always call a tool to retrieve it first, and only state numbers that
came back from a tool result. If a tool call fails or a ticker doesn't exist, say so
plainly rather than guessing.

All data behind this platform is simulated for demonstration, not real market data --
remind the person of that if they seem to be treating a number as real-world fact.

Keep answers concise, concrete, and grounded in the numbers you retrieved. You do not
give portfolio-level advice, run simulations, or take actions in the app -- those are
handled by separate specialists."""

TOOLS = [
    {
        "name": "get_company_overview",
        "description": "Identity and latest price for a ticker (name, sector, asset type, price).",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]},
    },
    {
        "name": "get_company_score",
        "description": "Full decomposed factor score for a ticker: overall score, the six category "
                        "scores (value, quality, growth, momentum, risk, macro), and every metric/peer "
                        "percentile/weight behind them.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]},
    },
    {
        "name": "get_company_financials",
        "description": "Valuation ratios, quality/margin metrics, growth rates, balance-sheet metrics, "
                        "and market/risk statistics for a ticker.",
        "input_schema": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]},
    },
    {
        "name": "compare_companies",
        "description": "Side-by-side metrics and scores for 2-5 tickers.",
        "input_schema": {
            "type": "object",
            "properties": {"tickers": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 5}},
            "required": ["tickers"],
        },
    },
]


def execute_tool(name: str, tool_input: dict) -> dict:
    try:
        if name == "get_company_overview":
            data = base.get_backend("/instruments")
            ticker = tool_input["ticker"].upper()
            match = next((d for d in data if d["ticker"] == ticker), None)
            if not match:
                raise base.ToolError(f"Unknown ticker '{ticker}'")
            return match
        if name == "get_company_score":
            return base.get_backend(f"/scores/{tool_input['ticker']}")
        if name == "get_company_financials":
            return base.get_backend(f"/financials/{tool_input['ticker']}")
        if name == "compare_companies":
            return base.post_backend("/compare", {"tickers": tool_input["tickers"]})
        return {"error": f"Unknown tool '{name}'"}
    except base.ToolError as e:
        return {"error": str(e)}
    except requests.RequestException as e:
        return {"error": f"Could not reach backend API: {e}"}


def run(message: str, history: list[dict] | None = None) -> str:
    return base.run_agent(SYSTEM_PROMPT, TOOLS, execute_tool, message, history)
