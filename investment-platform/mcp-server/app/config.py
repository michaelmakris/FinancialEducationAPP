from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent          # mcp-server/
load_dotenv(ROOT.parent / ".env")                       # shared investment-platform/.env
SECRETS = ROOT.parent / "secrets"


class Settings:
    # Where this server is reachable by AI clients (advertised as the protected resource).
    public_url: str = os.environ.get("MCP_PUBLIC_URL", "http://localhost:8090").rstrip("/")
    # Who issues the access keys (the BFF / web app). Advertised in the OAuth resource metadata.
    auth_server_url: str = os.environ.get("MCP_AUTH_SERVER_URL", "http://localhost:5173").rstrip("/")

    # Internal calls
    bff_url: str = os.environ.get("MCP_BFF_URL", "http://localhost:8080").rstrip("/")      # key introspection
    api_base_url: str = os.environ.get("MCP_API_BASE_URL", "http://localhost:8000").rstrip("/")
    api_audience: str = os.environ.get("API_AUDIENCE", "investment-api")
    issuer: str = os.environ.get("MCP_TOKEN_ISSUER", "mcp")
    signing_key_file: str = os.environ.get("MCP_SIGNING_KEY_FILE", str(SECRETS / "mcp_ed25519_private.pem"))
    token_lifetime_s: int = int(os.environ.get("MCP_TOKEN_LIFETIME_S", "60"))
    upstream_timeout_s: float = float(os.environ.get("MCP_UPSTREAM_TIMEOUT_S", "30"))

    # Access-key checks are cached briefly: revocation takes effect within this many seconds.
    key_cache_s: int = int(os.environ.get("MCP_KEY_CACHE_S", "30"))
    calls_per_minute: int = int(os.environ.get("MCP_CALLS_PER_MINUTE", "60"))  # per access key

    # DNS-rebinding protection for the HTTP transport.
    allowed_hosts: list[str] = [h.strip() for h in os.environ.get(
        "MCP_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*").split(",") if h.strip()]


settings = Settings()
