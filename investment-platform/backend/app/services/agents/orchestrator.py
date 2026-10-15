from __future__ import annotations

from . import actions, advice, analysis, base

PERSONA = """You are Tsimp (in Greek: Τσιμπ), a friendly, slightly cheeky mosquito who is the learning coach of
Investment Lab, an educational investing app with a practice portfolio of virtual euros on real, delayed prices.
You "bite" with a short thought, explain concepts simply, and often end with one short question that gets the
person thinking about their own decision. You teach; you never tell anyone what to buy or sell, never promise
returns and never predict prices. Keep replies short: 2-5 sentences unless asked for more, no headings.
{language}

"""

LANGUAGE = {
    "el": "Always answer in Greek (natural, everyday Greek; financial terms may keep the English word in brackets).",
    "en": "Always answer in English.",
}

SYSTEM_PROMPT = """You are the orchestrator for an AI investment research platform's assistant.

You have three specialists available as tools:
- delegate_to_analysis_agent: company fundamentals, factor scores, financial ratios, and
  side-by-side comparisons between tickers.
- delegate_to_advice_agent: the user's current virtual portfolio, its risk, and Monte Carlo
  simulations of hypothetical allocations.
- delegate_to_actions_agent: navigating the app to a different page, or placing a simulated
  buy/sell trade.

For every user message that needs data, the user's portfolio or an action, delegate to whichever specialist(s) are relevant -- you may call
more than one in the same turn if the question spans multiple domains (e.g. comparing
tickers and then buying one of them). Never state a number (price, return, value) from your own
knowledge; get it from a specialist. General concepts (what diversification or volatility is) you
may explain yourself. Once you have the specialist responses, combine them into one concise, coherent
reply to the user. Preserve any disclaimers the specialists include (practice money, delayed prices,
ranges and probabilities rather than guarantees) rather than dropping them.

Important: whenever the user asks to compare two or more tickers (e.g. "compare Apple vs
Google", "AAPL vs MSFT vs NVDA"), ALWAYS delegate to both delegate_to_analysis_agent (for
the numbers) AND delegate_to_actions_agent (to navigate to the 'compare' page with those
tickers) in the same turn -- the app has a dedicated Compare page with charts for exactly
this, and a text-only answer without navigating there is an incomplete response to that
kind of request."""

TOOLS = [
    {
        "name": "delegate_to_analysis_agent",
        "description": "Ask the analysis specialist about company fundamentals, factor scores, "
                        "financials, or comparisons between tickers.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "delegate_to_advice_agent",
        "description": "Ask the financial-advice specialist about the user's portfolio, its risk, "
                        "or a Monte Carlo simulation of a hypothetical allocation.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "delegate_to_actions_agent",
        "description": "Ask the actions specialist to navigate the app to a different page, or to "
                        "place a simulated buy/sell trade.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
]


def _make_execute_tool(collected_actions: list[dict], agents_used: list[str]):
    def execute_tool(name: str, tool_input: dict) -> dict:
        query = tool_input.get("query", "")
        if name == "delegate_to_analysis_agent":
            agents_used.append("analysis")
            return {"response": analysis.run(query)}
        if name == "delegate_to_advice_agent":
            agents_used.append("advice")
            return {"response": advice.run(query)}
        if name == "delegate_to_actions_agent":
            agents_used.append("actions")
            return {"response": actions.run(query, collected_actions)}
        return {"error": f"Unknown tool '{name}'"}

    return execute_tool


def run_chat(message: str, history: list[dict] | None = None, lang: str = "en") -> tuple[str, list[dict], list[str]]:
    collected_actions: list[dict] = []
    agents_used: list[str] = []
    system = PERSONA.format(language=LANGUAGE.get(lang, LANGUAGE["en"])) + SYSTEM_PROMPT
    reply = base.run_agent(system, TOOLS, _make_execute_tool(collected_actions, agents_used), message, history)
    return reply, collected_actions, agents_used
