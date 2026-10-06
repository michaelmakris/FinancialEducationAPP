"""Shared provider-dispatch machinery for the analysis/advice/actions agents.

Each agent defines its own SYSTEM_PROMPT, TOOLS (Anthropic-style {name, description,
input_schema}), and execute_tool(name, input) -> dict, then calls run_agent(...) here
to actually talk to whichever LLM provider is configured (ANTHROPIC or a self-hosted
OpenAI-compatible endpoint, e.g. vLLM). This is the only place that needs to know both
providers' wire formats.
"""
from __future__ import annotations

import json
from typing import Callable

import requests

from ... import auth
from ...config import settings

MAX_TOOL_ROUNDS = 4


class ToolError(Exception):
    pass


def get_backend(path: str) -> dict:
    resp = requests.get(f"{settings.api_base_url}{path}", headers=auth.outbound_headers(), timeout=15)
    if resp.status_code == 404:
        raise ToolError(resp.json().get("detail", "Not found"))
    resp.raise_for_status()
    return resp.json()


def post_backend(path: str, payload: dict) -> dict:
    resp = requests.post(f"{settings.api_base_url}{path}", json=payload, headers=auth.outbound_headers(), timeout=30)
    if resp.status_code in (400, 404, 422):
        raise ToolError(resp.json().get("detail", "Request rejected"))
    resp.raise_for_status()
    return resp.json()


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]},
        }
        for t in tools
    ]


def run_agent(
    system_prompt: str,
    tools: list[dict],
    execute_tool: Callable[[str, dict], dict],
    message: str,
    history: list[dict] | None = None,
) -> str:
    """Runs one user turn to completion, including any tool-call rounds. execute_tool
    must never raise -- it should catch its own errors and return {"error": ...}."""
    history = history or []
    if settings.llm_provider == "anthropic":
        return _run_anthropic(system_prompt, tools, execute_tool, message, history)
    return _run_selfhosted(system_prompt, tools, execute_tool, message, history)


def _run_anthropic(system_prompt, tools, execute_tool, message, history) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    msgs = list(history) + [{"role": "user", "content": message}]
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model="claude-sonnet-5", max_tokens=1024, system=system_prompt, messages=msgs, tools=tools,
        )
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b.text for b in response.content if b.type == "text"]
        if not tool_uses:
            return "\n".join(text_blocks) if text_blocks else "(no response)"
        msgs.append({"role": "assistant", "content": response.content})
        tool_results = []
        for tu in tool_uses:
            result = execute_tool(tu.name, tu.input)
            tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(result)})
        msgs.append({"role": "user", "content": tool_results})
    return "(stopped after too many tool-call rounds -- try a narrower question)"


def _run_selfhosted(system_prompt, tools, execute_tool, message, history) -> str:
    base_url = settings.selfhosted_base_url.rstrip("/")
    msgs = [{"role": "system", "content": system_prompt}] + list(history) + [{"role": "user", "content": message}]
    openai_tools = _to_openai_tools(tools)
    for _ in range(MAX_TOOL_ROUNDS):
        resp = requests.post(
            f"{base_url}/chat/completions",
            json={"model": settings.selfhosted_model, "messages": msgs, "tools": openai_tools, "max_tokens": 1024},
            timeout=90,
        )
        resp.raise_for_status()
        choice_message = resp.json()["choices"][0]["message"]
        tool_calls = choice_message.get("tool_calls") or []
        if not tool_calls:
            return choice_message.get("content") or "(no response)"
        msgs.append(choice_message)
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = execute_tool(name, args)
            msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result)})
    return "(stopped after too many tool-call rounds -- try a narrower question)"
