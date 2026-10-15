from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# .env lives at the investment-platform/ root, one level above backend/.
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


def _default_trusted_issuers() -> str:
    secrets_dir = Path(__file__).resolve().parents[2] / "secrets"
    return ",".join(f"{name}={secrets_dir / f'{name}_ed25519_public.pem'}" for name in ("bff", "mcp")
                    if (secrets_dir / f"{name}_ed25519_public.pem").exists())


class Settings:
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./investment_platform.db")
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    llm_provider: str = os.environ.get("LLM_PROVIDER", "anthropic")  # "anthropic" | "selfhosted" | "azure"
    # Limits on what the AI chat sends and spends (services/agents/base.py, routers/chat.py)
    llm_max_output_tokens: int = int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "600"))          # per model call
    llm_max_tool_result_chars: int = int(os.environ.get("LLM_MAX_TOOL_RESULT_CHARS", "3000"))  # ~750 tokens per tool result
    llm_max_tool_rounds: int = int(os.environ.get("LLM_MAX_TOOL_ROUNDS", "3"))
    llm_max_history_messages: int = int(os.environ.get("LLM_MAX_HISTORY_MESSAGES", "8"))       # earlier turns sent along
    llm_max_history_chars: int = int(os.environ.get("LLM_MAX_HISTORY_CHARS", "800"))           # per earlier message
    llm_max_message_chars: int = int(os.environ.get("LLM_MAX_MESSAGE_CHARS", "1500"))          # the new question
    llm_daily_token_budget: int = int(os.environ.get("LLM_DAILY_TOKEN_BUDGET", "60000"))       # per customer per day, 0 = off
    selfhosted_base_url: str = os.environ.get("SELFHOSTED_LLM_BASE_URL", "http://localhost:8001/v1")
    selfhosted_model: str = os.environ.get("SELFHOSTED_LLM_MODEL", "Qwen/Qwen2.5-32B-Instruct-AWQ")
    # LLM_PROVIDER=azure: Azure OpenAI deployment in Azure AI Foundry (see app/services/llm.py)
    azure_openai_endpoint: str = os.environ.get("AZURE_OPENAI_ENDPOINT", "")       # https://<resource>.openai.azure.com
    azure_openai_deployment: str = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")   # deployment name, e.g. gpt-5.2
    azure_openai_api_key: str = os.environ.get("AZURE_OPENAI_API_KEY", "")         # empty -> Entra ID (az login / managed identity)
    azure_openai_reasoning_effort: str = os.environ.get("AZURE_OPENAI_REASONING_EFFORT", "low")
    fred_api_key: str | None = os.environ.get("FRED_API_KEY")
    coingecko_api_key: str | None = os.environ.get("COINGECKO_API_KEY")
    alpha_vantage_api_key: str | None = os.environ.get("ALPHA_VANTAGE_API_KEY")
    sec_user_agent: str = os.environ.get("SEC_USER_AGENT", "InvestmentPlatformDemo you@example.com")
    api_base_url: str = os.environ.get("API_BASE_URL", "http://localhost:8000")
    cors_origins: list[str] = os.environ.get("CORS_ORIGINS", "*").split(",")
    # Caller auth (see app/auth.py). "required" in every shared environment; "disabled" only for solo local dev.
    api_auth_mode: str = os.environ.get("API_AUTH_MODE", "required").lower()
    api_audience: str = os.environ.get("API_AUDIENCE", "investment-api")
    # issuer=public-key-path pairs, comma-separated, e.g. "bff=../secrets/bff_ed25519_public.pem"
    # Default: whichever caller public keys exist in investment-platform/secrets/ (bff/scripts/generate_keys.py):
    # the BFF (browser customers) and the MCP server (AI assistants with a customer's access key).
    api_trusted_issuers: str = os.environ.get("API_TRUSTED_ISSUERS", "") or _default_trusted_issuers()
    # Seconds to cache whole-universe market reads (/v1/instruments, data-status metrics). 0 disables.
    market_cache_ttl_s: int = int(os.environ.get("MARKET_CACHE_TTL_S", "300"))
    quote_cache_ttl_s: int = int(os.environ.get("QUOTE_CACHE_TTL_S", "60"))  # live intraday prices (services/quotes.py)
    practice_default_costs: str = os.environ.get("PRACTICE_DEFAULT_COSTS", "typical")  # none | low | typical | high
    # Seconds between DB-backed freshness metric refreshes on /metrics (Prometheus scrapes every 15s).
    metrics_refresh_s: int = int(os.environ.get("METRICS_REFRESH_S", "60"))


settings = Settings()
