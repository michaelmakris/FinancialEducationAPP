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
    llm_provider: str = os.environ.get("LLM_PROVIDER", "anthropic")  # "anthropic" or "selfhosted"
    selfhosted_base_url: str = os.environ.get("SELFHOSTED_LLM_BASE_URL", "http://localhost:8001/v1")
    selfhosted_model: str = os.environ.get("SELFHOSTED_LLM_MODEL", "Qwen/Qwen2.5-32B-Instruct-AWQ")
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
    # Seconds between DB-backed freshness metric refreshes on /metrics (Prometheus scrapes every 15s).
    metrics_refresh_s: int = int(os.environ.get("METRICS_REFRESH_S", "60"))


settings = Settings()
