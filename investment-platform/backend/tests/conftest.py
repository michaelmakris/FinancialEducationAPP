import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Point at a fresh temp DB file *before* anything imports app.config/app.db,
# so the API tests never touch a developer's real investment_platform.db.
_tmp_db = tempfile.NamedTemporaryFile(prefix="test_investment_platform_", suffix=".db", delete=False)
_tmp_db.close()  # Windows can't delete a file that's still open (see teardown below)
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ["MARKET_CACHE_TTL_S"] = "0"  # tests change data between requests
os.environ["METRICS_REFRESH_S"] = "0"

# A throwaway "BFF" signing key, trusted by the API under test (see app/auth.py).
BFF_KEY = Ed25519PrivateKey.generate()
_pub = tempfile.NamedTemporaryFile(prefix="test_bff_pub_", suffix=".pem", delete=False)
_pub.write(BFF_KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
_pub.close()
os.environ["API_AUTH_MODE"] = "required"
os.environ["API_AUDIENCE"] = "investment-api"
os.environ["API_TRUSTED_ISSUERS"] = f"bff={_pub.name}"

CUSTOMER_SCOPES = "market:read portfolio:read portfolio:write chat"
TEST_CUSTOMER = "test-customer-1"

import jwt  # noqa: E402
import pytest  # noqa: E402

from app.db import engine, init_db  # noqa: E402
from scripts.seed_demo_data import seed  # noqa: E402


def make_token(sub: str = TEST_CUSTOMER, scope: str = CUSTOMER_SCOPES, *, key=None, iss: str = "bff",
               aud: str = "investment-api", lifetime: int = 60, iat: int | None = None, alg: str = "EdDSA") -> str:
    """A token shaped like the ones the BFF mints."""
    now = int(time.time()) if iat is None else iat
    claims = {"iss": iss, "aud": aud, "sub": sub, "scope": scope, "iat": now, "exp": now + lifetime, "jti": uuid.uuid4().hex}
    return jwt.encode(claims, key or BFF_KEY, algorithm=alg)


def auth_headers(**kwargs) -> dict:
    return {"Authorization": f"Bearer {make_token(**kwargs)}"}


class _AuthedClient:
    """TestClient wrapper that signs a fresh customer token on every request
    (tokens live 60 s, a long test session must not reuse one)."""

    def __init__(self, client, **token_kwargs):
        self._client, self._kw = client, token_kwargs

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if name not in ("get", "post", "put", "patch", "delete", "request"):
            return attr

        def call(*args, headers=None, **kwargs):
            return attr(*args, headers={**auth_headers(**self._kw), **(headers or {})}, **kwargs)

        return call


@pytest.fixture(scope="session", autouse=True)
def _seeded_db():
    init_db()
    seed()
    yield
    engine.dispose()
    os.unlink(_tmp_db.name)
    os.unlink(_pub.name)


@pytest.fixture(scope="session")
def raw_client():
    """No credentials at all -- for testing that the API refuses anonymous calls."""
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture(scope="session")
def client(raw_client):
    """Calls as TEST_CUSTOMER with the normal customer scopes, like the BFF does."""
    return _AuthedClient(raw_client)


@pytest.fixture(scope="session")
def staff_client(raw_client):
    return _AuthedClient(raw_client, sub="staff-1", scope=CUSTOMER_SCOPES + " ops:read")
