"""
A command-line AI analyst for the platform. This is the *real* agent (as
opposed to the browser demo's "AI analyst" tab, which only previews how it
works): it uses Claude's tool-use API and can only state a number after
retrieving it from this backend's own API -- the same analytics engine used
by every other part of the platform.

Setup:
    export ANTHROPIC_API_KEY=sk-ant-...
    uvicorn app.main:app --reload &          # backend must be running
    python -m scripts.seed_demo_data          # first run only
    python agent/chat_agent.py

Requires: pip install anthropic requests  (both already in requirements.txt)
"""
from __future__ import annotations

import json
import os
import sys

import requests

try:
    import anthropic
except ImportError:
    print("Missing dependency: pip install anthropic")
    sys.exit(1)

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
MODEL = "claude-sonnet-5"
MAX_TOOL_ROUNDS = 4

SYSTEM_PROMPT = """You are the AI analyst embedded in a demo investment research platform.

Hard rule: you must never state a price, ratio, score, or simulation result
from memory or estimation -- always call a tool to retrieve it first, and
only state numbers that came back from a tool result. If a tool call fails
or a ticker doesn't exist, say so plainly rather than guessing.

All data behind this platform is simulated for demonstration, not real
market data -- remind the person of that if they seem to be treating a
number as real-world fact.

When discussing risk or return outcomes, present them as ranges and
probabilities from the simulator, never as guarantees or recommendations.
Keep answers concise, concrete, and grounded in the numbers you retrieved."""

TOOLS = [
    {
        "name": "get_company_overview",
        "description": "Identity and latest price for a ticker (name, sector, asset type, price).",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_company_score",
        "description": "Full decomposed factor score for a ticker: overall score, the six category "
                        "scores (value, quality, growth, momentum, risk, macro), and every metric/peer "
                        "percentile/weight behind them.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_company_financials",
        "description": "Valuation ratios, quality/margin metrics, growth rates, balance-sheet metrics, "
                        "and market/risk statistics for a ticker.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
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


class ToolError(Exception):
    pass


def _get(path: str) -> dict:
    resp = requests.get(f"{API_BASE_URL}{path}", timeout=15)
    if resp.status_code == 404:
        raise ToolError(resp.json().get("detail", "Not found"))
    resp.raise_for_status()
    return resp.json()


def _post(path: str, payload: dict) -> dict:
    resp = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=30)
    if resp.status_code in (400, 404, 422):
        raise ToolError(resp.json().get("detail", "Request rejected"))
    resp.raise_for_status()
    return resp.json()


def execute_tool(name: str, tool_input: dict) -> dict:
    try:
        if name == "get_company_overview":
            data = _get(f"/instruments")
            ticker = tool_input["ticker"].upper()
            match = next((d for d in data if d["ticker"] == ticker), None)
            if not match:
                raise ToolError(f"Unknown ticker '{ticker}'")
            return match
        if name == "get_company_score":
            return _get(f"/scores/{tool_input['ticker']}")
        if name == "get_company_financials":
            return _get(f"/financials/{tool_input['ticker']}")
        if name == "compare_companies":
            return _post("/compare", {"tickers": tool_input["tickers"]})
        if name == "calculate_portfolio_risk":
            return _get("/portfolio")
        if name == "simulate_portfolio":
            return _post("/simulate", {
                "amount": tool_input["amount"], "equities_pct": tool_input["equities_pct"],
                "bonds_pct": tool_input["bonds_pct"], "crypto_pct": tool_input["crypto_pct"],
                "cash_pct": tool_input["cash_pct"], "horizon_months": tool_input["horizon_months"],
            })
        return {"error": f"Unknown tool '{name}'"}
    except ToolError as e:
        return {"error": str(e)}
    except requests.RequestException as e:
        return {"error": f"Could not reach backend API at {API_BASE_URL}: {e}"}


def run_turn(client: anthropic.Anthropic, history: list[dict]) -> str:
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL, max_tokens=1024, system=SYSTEM_PROMPT, messages=history, tools=TOOLS,
        )
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b.text for b in response.content if b.type == "text"]

        if not tool_uses:
            return "\n".join(text_blocks) if text_blocks else "(no response)"

        history.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tu in tool_uses:
            print(f"  \u2192 {tu.name}({json.dumps(tu.input)})")
            result = execute_tool(tu.name, tu.input)
            tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(result)})
        history.append({"role": "user", "content": tool_results})

    return "(stopped after too many tool-call rounds -- try a narrower question)"


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Set ANTHROPIC_API_KEY before running this script.")
        sys.exit(1)
    try:
        requests.get(f"{API_BASE_URL}/health", timeout=5).raise_for_status()
    except requests.RequestException:
        print(f"Could not reach the backend at {API_BASE_URL}. Start it first:\n"
              f"  uvicorn app.main:app --reload")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    history: list[dict] = []
    print("AI analyst ready. Simulated data -- not investment advice. Ctrl+C to quit.\n")
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        history.append({"role": "user", "content": user_input})
        reply = run_turn(client, history)
        history.append({"role": "assistant", "content": reply})
        print(f"\nanalyst> {reply}\n")


if __name__ == "__main__":
    main()
