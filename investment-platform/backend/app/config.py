from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# .env lives at the investment-platform/ root, one level above backend/.
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


class Settings:
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./investment_platform.db")
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    fred_api_key: str | None = os.environ.get("FRED_API_KEY")
    coingecko_api_key: str | None = os.environ.get("COINGECKO_API_KEY")
    alpha_vantage_api_key: str | None = os.environ.get("ALPHA_VANTAGE_API_KEY")
    sec_user_agent: str = os.environ.get("SEC_USER_AGENT", "InvestmentPlatformDemo you@example.com")
    api_base_url: str = os.environ.get("API_BASE_URL", "http://localhost:8000")
    cors_origins: list[str] = os.environ.get("CORS_ORIGINS", "*").split(",")


settings = Settings()
