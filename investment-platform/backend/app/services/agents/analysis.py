from __future__ import annotations

from urllib.parse import quote

import requests

from . import base

SYSTEM_PROMPT = """You are the analysis specialist for an educational investing app.

Hard rule: you must never state a price, ratio, score, or comparison from memory or
estimation -- always call a tool to retrieve it first, and only state numbers that
came back from a tool result. If a tool call fails or a ticker doesn't exist, say so
plainly rather than guessing.

The app covers real instruments in five markets: athens (Athens-listed shares, tickers
like ETE.AT), europe (euro-area large caps, e.g. SAP.DE, ASML.AS), us (US large caps,
tickers end in .US, e.g. AAPL.US), etf (EUR-listed ETFs, e.g. IWDA.AS) and crypto
(e.g. BTC-EUR). Use search_instruments when you are not sure of a ticker. Prices come
from free, delayed sources and are for learning only -- say so if someone treats them
as live trading quotes. Company financials exist only for some Athens-listed companies.

Keep answers concise, concrete, and grounded in the numbers you retrieved. You do not
give portfolio-level advice, run simulations, or take actions in the app -- those are
handled by separate specialists."""

_TICKER = {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}

TOOLS = [
    {
        "name": "search_instruments",
        "description": "Find instruments by name or ticker, optionally within one market "
                        "(athens, europe, us, etf, crypto). Returns ticker, name, sector, last close, "
                        "1-day / 1-month / 1-year returns.",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string"},
            "market": {"type": "string", "enum": ["athens", "europe", "us", "etf", "crypto"]}}},
    },
    {
        "name": "get_company_overview",
        "description": "Identity, latest daily close, returns over several periods and today's live "
                        "(delayed) price for a ticker.",
        "input_schema": _TICKER,
    },
    {
        "name": "get_company_financials",
        "description": "Reported annual financials (revenue, profit, assets, equity, ...) for an Athens-listed company.",
        "input_schema": _TICKER,
    },
    {
        "name": "get_risk_estimates",
        "description": "Model estimates for a ticker: expected volatility, chance of a loss, quality rank.",
        "input_schema": _TICKER,
    },
    {
        "name": "compare_companies",
        "description": "Side-by-side returns and risk for 2-5 tickers over the last year.",
        "input_schema": {
            "type": "object",
            "properties": {"tickers": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 5}},
            "required": ["tickers"],
        },
    },
]


def execute_tool(name: str, tool_input: dict) -> dict:
    try:
        if name == "search_instruments":
            params = []
            if tool_input.get("query"):
                params.append("q=" + quote(str(tool_input["query"])))
            if tool_input.get("market"):
                params.append("market=" + quote(str(tool_input["market"])))
            rows = base.get_backend("/v1/instruments" + ("?" + "&".join(params) if params else ""))
            keep = ("ticker", "name", "market", "sector", "currency", "last_close", "change_1d", "return_1m", "return_1y")
            return {"count": len(rows), "results": [{k: r.get(k) for k in keep} for r in rows[:15]],
                    "note": "first 15 matches; narrow the query or market for others" if len(rows) > 15 else ""}
        ticker = quote(str(tool_input.get("ticker", "")).upper())
        if name == "get_company_overview":
            detail = base.get_backend(f"/v1/instruments/{ticker}")
            live = base.get_backend(f"/v1/instruments/{ticker}/intraday")
            live.pop("points", None)
            return {"instrument": detail, "today": live}
        if name == "get_company_financials":
            data = base.get_backend(f"/v1/instruments/{ticker}/fundamentals")
            years = data.get("years") or []
            # the two latest fiscal years are enough to talk about; sources are links, not numbers
            data["years"] = [{k: v for k, v in y.items() if k != "sources"} for y in years[:2]]  # newest first
            data["years_available"] = len(years)
            return data
        if name == "get_risk_estimates":
            return base.get_backend(f"/v1/predictions/instruments/{ticker}")
        if name == "compare_companies":
            tickers = ",".join(quote(str(t).upper()) for t in tool_input["tickers"])
            data = base.get_backend(f"/v1/compare?tickers={tickers}")
            # the daily series are for charts (the app's Compare page); the model gets the totals
            return {k: v for k, v in data.items() if k != "points"}
        return {"error": f"Unknown tool '{name}'"}
    except base.ToolError as e:
        return {"error": str(e)}
    except requests.RequestException as e:
        return {"error": f"Could not get that data: {e}"}


def run(message: str, history: list[dict] | None = None) -> str:
    return base.run_agent(SYSTEM_PROMPT, TOOLS, execute_tool, message, history)
