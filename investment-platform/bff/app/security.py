"""
Password hashing, input rules, random tokens, API token signing and rate limits.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
import unicodedata
import uuid
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from fastapi import Request

from .config import settings

# ---------------------------------------------------------------- passwords
# argon2-cffi defaults: Argon2id, 64 MiB memory, 3 iterations, 4 lanes (RFC 9106 "second choice").
_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))  # compared against when the email is unknown

PASSWORD_MIN, PASSWORD_MAX = 12, 128
_COMMON = {
    "password1234", "123456789012", "qwertyuiop12", "passwordpassword", "letmein12345", "iloveyou1234",
    "administrator", "welcome12345", "changeme1234", "111111111111", "000000000000", "abcdefghijkl",
}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Constant work whether or not the account exists (pass stored_hash=None)."""
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def password_problems(password: str, email: str = "", full_name: str = "") -> list[str]:
    """NIST 800-63B style: length over composition rules, reject the obvious."""
    problems = []
    if len(password) < PASSWORD_MIN:
        problems.append(f"at least {PASSWORD_MIN} characters")
    if len(password) > PASSWORD_MAX:
        problems.append(f"at most {PASSWORD_MAX} characters")
    low = password.lower()
    if low in _COMMON or len(set(low)) < 4:
        problems.append("not a common or repetitive password")
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in low:
        problems.append("must not contain your email name")
    if full_name and any(len(part) >= 4 and part.lower() in low for part in full_name.split()):
        problems.append("must not contain your name")
    return problems


# ---------------------------------------------------------------- inputs
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def normalize_email(email: str) -> str:
    return unicodedata.normalize("NFKC", email).strip().lower()


def valid_email(email: str) -> bool:
    return len(email) <= 254 and bool(_EMAIL.match(email))


# ---------------------------------------------------------------- tokens
def new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def same(a: str | None, b: str | None) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a, b)


def client_ip(request: Request) -> str:
    if settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


# ---------------------------------------------------------------- tokens for the API
ROLE_SCOPES = {
    "customer": "market:read portfolio:read portfolio:write chat",
    "staff": "market:read portfolio:read portfolio:write chat ops:read",
}


@lru_cache(maxsize=1)
def _signing_key():
    path = Path(settings.signing_key_file)
    if not path.exists():
        raise RuntimeError(f"BFF signing key not found at {path}. Run: python -m scripts.generate_keys")
    return load_pem_private_key(path.read_bytes(), password=None)


def mint_api_token(customer_id: str, role: str, lifetime_s: int) -> str:
    now = int(time.time())
    claims = {
        "iss": settings.token_issuer, "aud": settings.api_audience, "sub": customer_id,
        "scope": ROLE_SCOPES.get(role, ROLE_SCOPES["customer"]),
        "iat": now, "exp": now + lifetime_s, "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, _signing_key(), algorithm="EdDSA")


# ---------------------------------------------------------------- data at rest
@lru_cache(maxsize=1)
def _data_key() -> bytes:
    """32-byte urlsafe-base64 Fernet key from BFF_DATA_KEY_FILE (created by scripts.generate_keys)."""
    path = Path(settings.data_key_file)
    if not path.exists():
        raise RuntimeError(f"BFF data key not found at {path}. Run: python -m scripts.generate_keys")
    return path.read_bytes().strip()


def encrypt(plaintext: str) -> str:
    return Fernet(_data_key()).encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return Fernet(_data_key()).decrypt(token.encode()).decode()


def keyed_hash(value: str) -> str:
    """HMAC-SHA256 with the data key: an offline DB copy alone cannot brute-force recovery codes."""
    return hmac.new(_data_key(), value.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- rate limiting
class MemoryRateLimiter:
    """Sliding-window counter per key, in process memory: one BFF instance / dev."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, q: deque, window_s: float, now: float) -> None:
        while q and now - q[0] > window_s:
            q.popleft()

    def hit(self, key: str, limit: int, window_s: float) -> bool:
        """Record one attempt; False (and not recorded) if `limit` is already reached within `window_s`."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            self._trim(q, window_s, now)
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def count(self, key: str, window_s: float) -> int:
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return 0
            self._trim(q, window_s, now)
            return len(q)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


class RedisRateLimiter:
    """Same contract, shared by every BFF replica: one sorted set per key, scored by time."""

    PREFIX = "bff:rl:"

    def __init__(self, client) -> None:
        self.r = client

    def hit(self, key: str, limit: int, window_s: float) -> bool:
        k, now = self.PREFIX + key, time.time()
        member = f"{now:.6f}:{secrets.token_hex(4)}"
        pipe = self.r.pipeline()  # MULTI/EXEC: trim, add, count atomically
        pipe.zremrangebyscore(k, 0, now - window_s)
        pipe.zadd(k, {member: now})
        pipe.zcard(k)
        pipe.expire(k, int(window_s) + 1)
        _, _, n, _ = pipe.execute()
        if n > limit:
            self.r.zrem(k, member)  # over the limit: this attempt does not count
            return False
        return True

    def count(self, key: str, window_s: float) -> int:
        k = self.PREFIX + key
        self.r.zremrangebyscore(k, 0, time.time() - window_s)
        return int(self.r.zcard(k))

    def reset(self, key: str) -> None:
        self.r.delete(self.PREFIX + key)

    def clear(self) -> None:
        for k in self.r.scan_iter(self.PREFIX + "*"):
            self.r.delete(k)


def _make_limiter():
    if settings.redis_url:
        import redis
        return RedisRateLimiter(redis.Redis.from_url(settings.redis_url, socket_timeout=2))
    return MemoryRateLimiter()


limiter = _make_limiter()
