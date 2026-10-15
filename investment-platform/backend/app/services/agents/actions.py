"""The actions specialist. Unlike analysis/advice, its tools don't call the backend API --
navigation and trades are mutations of the browser's own React state (see App.jsx), so
this agent just validates the request and queues a structured action. The router hands
that queue back to the frontend in the /chat response, which is what actually applies it
(via the same goTo/onBuy/onSell handlers the rest of the UI uses)."""
from __future__ import annotations

from . import base

VALID_PAGES = ["home", "feed", "discover", "asset", "compare", "simulator", "portfolio", "learn", "analyst"]

SYSTEM_PROMPT = f"""You are the actions specialist for an AI investment research platform.

You can navigate the app to a different page, or place a simulated buy/sell trade in the
user's virtual portfolio. Valid pages: {', '.join(VALID_PAGES)}.

For the 'compare' page, resolve the tickers the user means (e.g. "Apple vs Google" ->
AAPL.US, GOOGL.US; US shares end in .US, Athens shares in .AT, e.g. ETE.AT; crypto like BTC-EUR) and pass them in `tickers` so the comparison is populated automatically --
you don't need a tool to do this, resolving a well-known company name to its ticker
symbol is not a financial fact that needs grounding, unlike a price/ratio/score.

You do not look up company data or give advice yourself -- if you need a number to
resolve the request (e.g. a ticker's price to judge affordability), say so rather than
guessing. Only call a tool once the request is unambiguous (ticker, quantity, and/or page
are known). Never claim an action completed on your own -- only report what the tool
result says."""

TOOLS = [
    {
        "name": "navigate_to_page",
        "description": f"Navigate the app to a different page. Valid pages: {', '.join(VALID_PAGES)}.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page": {"type": "string", "enum": VALID_PAGES},
                "ticker": {
                    "type": "string",
                    "description": "Optional single ticker to focus -- relevant for the 'asset' page.",
                },
                "tickers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 4,
                    "description": "2-4 tickers to populate the comparison with -- only for the 'compare' page.",
                },
            },
            "required": ["page"],
        },
    },
    {
        "name": "execute_trade",
        "description": "Place a simulated buy or sell order for a ticker in the user's virtual portfolio.",
        "input_schema": {
            "type": "object",
            "properties": {
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "ticker": {"type": "string"},
                "qty": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["side", "ticker", "qty"],
        },
    },
]


def make_execute_tool(collected_actions: list[dict]):
    def execute_tool(name: str, tool_input: dict) -> dict:
        if name == "navigate_to_page":
            page = tool_input.get("page")
            if page not in VALID_PAGES:
                return {"error": f"Unknown page '{page}'"}
            action = {"type": "navigate", "page": page}
            if tool_input.get("ticker"):
                action["ticker"] = str(tool_input["ticker"]).upper()
            tickers = tool_input.get("tickers")
            if tickers:
                if not (2 <= len(tickers) <= 4):
                    return {"error": "tickers must have between 2 and 4 entries"}
                action["tickers"] = [str(t).upper() for t in tickers]
            collected_actions.append(action)
            return {"status": "queued", "action": action}
        if name == "execute_trade":
            side = tool_input.get("side")
            if side not in ("buy", "sell"):
                return {"error": f"Unknown side '{side}'"}
            qty = tool_input.get("qty")
            if not isinstance(qty, (int, float)) or qty <= 0:
                return {"error": "qty must be a positive number"}
            if not tool_input.get("ticker"):
                return {"error": "ticker is required"}
            action = {"type": "trade", "side": side, "ticker": str(tool_input["ticker"]).upper(), "qty": qty}
            collected_actions.append(action)
            return {
                "status": "queued",
                "action": action,
                "note": "Will be executed client-side against the app's live price for this ticker.",
            }
        return {"error": f"Unknown tool '{name}'"}

    return execute_tool


def run(message: str, collected_actions: list[dict], history: list[dict] | None = None) -> str:
    return base.run_agent(SYSTEM_PROMPT, TOOLS, make_execute_tool(collected_actions), message, history)
