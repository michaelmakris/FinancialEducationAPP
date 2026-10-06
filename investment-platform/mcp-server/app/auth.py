"""
Who is calling, and as whom we call the API.

1. An AI client sends `Authorization: Bearer fea_mcp_...` (a personal access key the
   customer created in the web app, Security -> AI assistant access).
2. AccessKeyVerifier asks the BFF whether the key is valid (POST /bff/internal/introspect,
   authenticated with a 60 s JWT signed by this server's Ed25519 key). Results are
   cached for MCP_KEY_CACHE_S, so a revoked key stops working within that time.
3. For each API call the server mints a 60 s token as issuer "mcp" for that customer,
   with exactly the key's scopes (never more than the customer's own; the BFF
   already intersected them with the customer's role).
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path

import httpx
import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from mcp.server.auth.provider import AccessToken
from prometheus_client import Counter

from .config import settings

log = logging.getLogger("mcp.auth")
AUTH = Counter("mcp_auth_total", "Access-key checks", ["result"])  # valid | invalid | cached | error


@lru_cache(maxsize=1)
def signing_key():
    path = Path(settings.signing_key_file)
    if not path.exists():
        raise RuntimeError(f"MCP signing key not found at {path}. Run in bff/: python -m scripts.generate_keys --name mcp")
    return load_pem_private_key(path.read_bytes(), password=None)


def mint(audience: str, subject: str | None = None, scope: str | None = None, lifetime_s: int | None = None) -> str:
    now = int(time.time())
    claims = {"iss": settings.issuer, "aud": audience, "iat": now, "exp": now + (lifetime_s or settings.token_lifetime_s),
              "jti": uuid.uuid4().hex}
    if subject:
        claims["sub"] = subject
    if scope is not None:
        claims["scope"] = scope
    return jwt.encode(claims, signing_key(), algorithm="EdDSA")


class AccessKeyVerifier:
    """mcp TokenVerifier: resolves `fea_mcp_...` keys through the BFF."""

    def __init__(self, http: httpx.AsyncClient | None = None) -> None:
        self.http = http or httpx.AsyncClient(timeout=10)
        self._cache: dict[str, tuple[float, AccessToken | None]] = {}

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token.startswith("fea_mcp_") or len(token) > 200:
            AUTH.labels("invalid").inc()
            return None
        key = hashlib.sha256(token.encode()).hexdigest()
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            AUTH.labels("cached").inc()
            return hit[1]
        try:
            r = await self.http.post(f"{settings.bff_url}/bff/internal/introspect", json={"key": token},
                                     headers={"Authorization": f"Bearer {mint('bff-internal')}"})
            r.raise_for_status()
            info = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("introspection failed: %s", e)
            AUTH.labels("error").inc()
            return None  # fail closed, and don't cache the outage
        if not info.get("active"):
            AUTH.labels("invalid").inc()
            self._cache[key] = (now + 5, None)
            return None
        access = AccessToken(
            token=token, client_id=f"access-key:{info['key_id']}", scopes=list(info["scopes"]),
            expires_at=info.get("expires_at"), subject=info["customer_id"],
            resource=settings.public_url, claims={"key_prefix": info.get("key_prefix")},
        )
        self._cache[key] = (now + settings.key_cache_s, access)
        AUTH.labels("valid").inc()
        return access


class PerKeyLimiter:
    """Calls per minute per access key (in memory; one MCP server instance)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float = 60) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


limiter = PerKeyLimiter()
