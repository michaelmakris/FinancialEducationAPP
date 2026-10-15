"""
One client for the OpenAI-style chat-completions providers:

    LLM_PROVIDER=selfhosted   vLLM / any OpenAI-compatible server (SELFHOSTED_LLM_BASE_URL, SELFHOSTED_LLM_MODEL)
    LLM_PROVIDER=azure        Azure OpenAI in Azure AI Foundry (AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT)

(LLM_PROVIDER=anthropic is handled by the Anthropic SDK in agents/base.py.)

Azure authentication, in order:
  * AZURE_OPENAI_API_KEY if set (api-key header), else
  * Microsoft Entra ID via azure-identity's DefaultAzureCredential -- on a developer PC that is
    your `az login`; in a container a managed identity or AZURE_CLIENT_ID/SECRET/TENANT_ID.
    The identity needs the "Cognitive Services OpenAI User" role on the resource. No key is stored.
"""
from __future__ import annotations

import contextlib
import contextvars
import threading
import time

import requests

from ..config import settings

_SCOPE = "https://cognitiveservices.azure.com/.default"
_choice: contextvars.ContextVar[str | None] = contextvars.ContextVar("llm_provider", default=None)
# Tokens used by the model calls of the current request (see count_usage); None = not counting.
_usage: contextvars.ContextVar[dict | None] = contextvars.ContextVar("llm_usage", default=None)


@contextlib.contextmanager
def count_usage():
    """Collects the tokens every model call inside the block uses: {"prompt", "completion", "total"}."""
    totals = {"prompt": 0, "completion": 0, "total": 0}
    token = _usage.set(totals)
    try:
        yield totals
    finally:
        _usage.reset(token)


def add_usage(prompt: int = 0, completion: int = 0) -> None:
    totals = _usage.get()
    if totals is not None:
        totals["prompt"] += int(prompt or 0)
        totals["completion"] += int(completion or 0)
        totals["total"] = totals["prompt"] + totals["completion"]


def available() -> list[dict]:
    """Providers that are configured, for the app's model picker. LLM_PROVIDER is the default."""
    out = []
    if settings.azure_openai_endpoint and settings.azure_openai_deployment:
        out.append({"id": "azure", "label": f"Azure OpenAI ({settings.azure_openai_deployment})",
                    "model": settings.azure_openai_deployment, "note": "Azure AI Foundry"})
    if settings.selfhosted_base_url:
        out.append({"id": "selfhosted", "label": f"University cluster ({settings.selfhosted_model.split('/')[-1]})",
                    "model": settings.selfhosted_model, "note": "self-hosted vLLM; needs the VPN and SSH tunnel"})
    if settings.anthropic_api_key:
        out.append({"id": "anthropic", "label": "Anthropic Claude", "model": "claude-sonnet-5", "note": "Anthropic API"})
    for p in out:
        p["default"] = p["id"] == settings.llm_provider
    return out


def current() -> str:
    return _choice.get() or settings.llm_provider


@contextlib.contextmanager
def use(provider: str | None):
    """Use `provider` for LLM calls made inside this block (this request only)."""
    if provider and provider not in {p["id"] for p in available()}:
        raise ValueError(f"LLM provider '{provider}' is not configured")
    token = _choice.set(provider or None)
    try:
        yield
    finally:
        _choice.reset(token)


_token_lock = threading.Lock()
_token: tuple[str, float] | None = None  # (token, expires_on)
_credential = None


def _azure_headers() -> dict[str, str]:
    if settings.azure_openai_api_key:
        return {"api-key": settings.azure_openai_api_key}
    global _token, _credential
    with _token_lock:
        if _token is None or _token[1] - time.time() < 300:  # refresh 5 minutes before expiry
            if _credential is None:
                from azure.identity import DefaultAzureCredential
                _credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
            t = _credential.get_token(_SCOPE)
            _token = (t.token, float(t.expires_on))
        return {"Authorization": f"Bearer {_token[0]}"}


def chat(messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 1024,
         temperature: float | None = None, timeout: float = 90) -> dict:
    """One chat-completions call; returns choices[0].message (content and/or tool_calls)."""
    if current() == "azure":
        if not (settings.azure_openai_endpoint and settings.azure_openai_deployment):
            raise RuntimeError("Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT for LLM_PROVIDER=azure")
        url = f"{settings.azure_openai_endpoint.rstrip('/')}/openai/v1/chat/completions"
        # GPT-5-family deployments: reasoning tokens count against max_completion_tokens (so it gets
        # 3x the visible answer's budget), and temperature is fixed by the service, so it is never sent.
        body: dict = {"model": settings.azure_openai_deployment, "messages": messages,
                      "max_completion_tokens": max_tokens * 3}
        if settings.azure_openai_reasoning_effort:
            body["reasoning_effort"] = settings.azure_openai_reasoning_effort
        headers = _azure_headers()
    else:
        url = f"{settings.selfhosted_base_url.rstrip('/')}/chat/completions"
        body = {"model": settings.selfhosted_model, "messages": messages, "max_tokens": max_tokens}
        if temperature is not None:
            body["temperature"] = temperature
        headers = {}
    if tools:
        body["tools"] = tools
    resp = requests.post(url, json=body, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage") or {}
    add_usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
    return data["choices"][0]["message"]
