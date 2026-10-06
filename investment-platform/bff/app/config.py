from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent          # bff/
load_dotenv(ROOT.parent / ".env")                       # shared investment-platform/.env


def _bool(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    # Credentials live in the BFF's own tables (auth_*), never in the API's database
    # tables. In production point this at a separate database or role.
    database_url: str = os.environ.get("BFF_DATABASE_URL", f"sqlite:///{ROOT / 'bff.db'}")

    # Downstream API and the token the BFF signs for it (see backend/app/auth.py)
    api_base_url: str = os.environ.get("BFF_API_BASE_URL", "http://localhost:8000").rstrip("/")
    api_audience: str = os.environ.get("API_AUDIENCE", "investment-api")
    token_issuer: str = os.environ.get("BFF_TOKEN_ISSUER", "bff")
    signing_key_file: str = os.environ.get("BFF_SIGNING_KEY_FILE", str(ROOT.parent / "secrets" / "bff_ed25519_private.pem"))
    token_lifetime_s: int = int(os.environ.get("BFF_TOKEN_LIFETIME_S", "60"))
    chat_token_lifetime_s: int = int(os.environ.get("BFF_CHAT_TOKEN_LIFETIME_S", "300"))  # assistant runs several tool calls
    upstream_timeout_s: float = float(os.environ.get("BFF_UPSTREAM_TIMEOUT_S", "120"))

    # Browser session
    cookie_secure: bool = _bool("BFF_COOKIE_SECURE", "true")
    session_idle_minutes: int = int(os.environ.get("BFF_SESSION_IDLE_MINUTES", "30"))
    session_absolute_hours: int = int(os.environ.get("BFF_SESSION_ABSOLUTE_HOURS", "12"))
    allowed_origins: list[str] = [o.strip() for o in os.environ.get(
        "BFF_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

    # Brute-force protection
    login_max_failures: int = int(os.environ.get("BFF_LOGIN_MAX_FAILURES", "5"))
    lockout_minutes: int = int(os.environ.get("BFF_LOCKOUT_MINUTES", "15"))
    auth_rate_per_minute: int = int(os.environ.get("BFF_AUTH_RATE_PER_MINUTE", "10"))
    trust_proxy_headers: bool = _bool("BFF_TRUST_PROXY_HEADERS", "false")  # only behind a known reverse proxy
    # Shared rate limits across BFF replicas. Empty = in-process memory (single instance / dev).
    redis_url: str = os.environ.get("BFF_REDIS_URL", "")

    # Email (verification, password reset, security notices)
    public_url: str = os.environ.get("BFF_PUBLIC_URL", "http://localhost:5173").rstrip("/")  # links in emails
    email_backend: str = os.environ.get("BFF_EMAIL_BACKEND", "outbox").lower()  # outbox (dev: .eml files) | smtp
    email_from: str = os.environ.get("BFF_EMAIL_FROM", "Investment Lab <no-reply@localhost>")
    outbox_dir: str = os.environ.get("BFF_OUTBOX_DIR", str(ROOT / "outbox"))
    smtp_host: str = os.environ.get("BFF_SMTP_HOST", "")
    smtp_port: int = int(os.environ.get("BFF_SMTP_PORT", "587"))
    smtp_user: str = os.environ.get("BFF_SMTP_USER", "")
    smtp_password: str = os.environ.get("BFF_SMTP_PASSWORD", "")
    smtp_security: str = os.environ.get("BFF_SMTP_SECURITY", "starttls").lower()  # starttls | ssl | none
    require_email_verification: bool = _bool("BFF_REQUIRE_EMAIL_VERIFICATION", "true")
    verify_token_hours: int = int(os.environ.get("BFF_VERIFY_TOKEN_HOURS", "24"))
    reset_token_minutes: int = int(os.environ.get("BFF_RESET_TOKEN_MINUTES", "30"))

    # Multi-factor authentication (TOTP authenticator apps)
    require_mfa: bool = _bool("BFF_REQUIRE_MFA", "false")  # true for real customers: no API access until enrolled
    mfa_issuer: str = os.environ.get("BFF_MFA_ISSUER", "Investment Lab")
    mfa_challenge_minutes: int = int(os.environ.get("BFF_MFA_CHALLENGE_MINUTES", "5"))
    # Personal access keys for AI assistants (MCP server)
    access_key_max_days: int = int(os.environ.get("BFF_ACCESS_KEY_MAX_DAYS", "90"))
    access_key_max_active: int = int(os.environ.get("BFF_ACCESS_KEY_MAX_ACTIVE", "10"))
    # Internal services allowed to call /bff/internal/* : "mcp=/path/mcp_ed25519_public.pem"
    internal_callers: str = os.environ.get(
        "BFF_INTERNAL_CALLERS", f"mcp={ROOT.parent / 'secrets' / 'mcp_ed25519_public.pem'}")

    # Symmetric key that encrypts TOTP secrets at rest and peppers recovery-code hashes.
    data_key_file: str = os.environ.get("BFF_DATA_KEY_FILE", str(ROOT.parent / "secrets" / "bff_data_key"))

    @property
    def cookie_name(self) -> str:
        # __Host- prefix: browser refuses it unless Secure, Path=/ and no Domain -- can't be set by a subdomain
        return "__Host-fea_session" if self.cookie_secure else "fea_session"


settings = Settings()
