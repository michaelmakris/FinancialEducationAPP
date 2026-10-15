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
os.environ["QUOTE_CACHE_TTL_S"] = "0"
os.environ["PRACTICE_DEFAULT_COSTS"] = "none"  # trading tests check exact cash; tests/test_costs.py covers costs  # every request sees the fake quotes as the test sets them

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


# ---------------------------------------------------------------- practice trading on "real" instruments
@pytest.fixture
def practice_market(monkeypatch):
    """Three tradable instruments (Athens EUR, US USD, crypto EUR) and fake live quotes, no network.
    Tests change `prices[ticker]` (or `prices["USD"]`, USD per EUR) to move the market."""
    import datetime as dt

    from app.db import SessionLocal
    from app.services import quotes
    from pipelines import market_writer as w

    db = SessionLocal()
    for t, name, market, cur, src, sym in (("TESTA.AT", "Test Athens Co", "athens", "EUR", "yahoo", "TESTA.AT"),
                                           ("TSTUS.US", "Test US Inc", "us", "USD", "yahoo", "TSTUS"),
                                           ("TST-EUR", "Testcoin", "crypto", "EUR", "binance", "TSTEUR")):
        w.ensure_instrument(db, ticker=t, name=name, sector="Test", asset_type="crypto" if market == "crypto" else "equity",
                            exchange="", currency=cur, data_source=src, vendor_symbol=sym, market=market)
    db.commit()
    db.close()
    prices = {"TESTA.AT": 10.0, "TSTUS.US": 100.0, "TST-EUR": 50.0, "USD": 1.25}   # 1 EUR = 1.25 USD
    prev = {"TESTA.AT": 9.0, "TSTUS.US": 100.0, "TST-EUR": 50.0, "USD": 1.25}
    by_symbol = {"TESTA.AT": "TESTA.AT", "TSTUS": "TSTUS.US", "TSTEUR": "TST-EUR", "EURUSD=X": "USD"}

    def fake(key, currency):
        now = dt.datetime.now(dt.timezone.utc)
        day0 = quotes.athens_midnight_utc(now)
        early = day0 + (now - day0) / 4
        return quotes.Intraday(ticker=key, currency=currency, prev_close=prev[key],
                               points=[(early, prev[key]), (now, prices[key])], market_open=True)

    monkeypatch.setattr(quotes, "fetch_yahoo_intraday",
                        lambda ticker, symbol: fake(by_symbol[symbol], "USD" if symbol in ("TSTUS", "EURUSD=X") else "EUR"))
    monkeypatch.setattr(quotes, "fetch_binance_intraday", lambda ticker, pair: fake(by_symbol[pair], "EUR"))
    quotes.clear_cache()
    return prices
