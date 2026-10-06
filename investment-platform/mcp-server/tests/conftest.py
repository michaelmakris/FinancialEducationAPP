"""In-process harness: a real MCP client talks Streamable HTTP to the real app;
the app's outbound calls go to a fake BFF (key introspection) and a fake API,
both of which verify the Ed25519 tokens the MCP server signs."""
import asyncio
import contextlib
import os
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp = Path(tempfile.mkdtemp(prefix="mcp_test_"))
MCP_KEY = Ed25519PrivateKey.generate()
(_tmp / "mcp.pem").write_bytes(MCP_KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                     serialization.NoEncryption()))
os.environ.update({
    "MCP_SIGNING_KEY_FILE": str(_tmp / "mcp.pem"),
    "MCP_BFF_URL": "http://bff.internal",
    "MCP_API_BASE_URL": "http://api.internal",
    "MCP_PUBLIC_URL": "http://testserver",
    "MCP_ALLOWED_HOSTS": "testserver,testserver:*",
    "MCP_KEY_CACHE_S": "30",
    "MCP_CALLS_PER_MINUTE": "1000",
})

import httpx  # noqa: E402
import httpx2  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from mcp import Client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

from app import auth  # noqa: E402
from app.main import create_app  # noqa: E402

PUB = MCP_KEY.public_key()
KEYS = {
    "fea_mcp_read_key": {"customer_id": "cust-1", "scopes": ["market:read", "portfolio:read"]},
    "fea_mcp_trade_key": {"customer_id": "cust-2", "scopes": ["market:read", "portfolio:read", "portfolio:write"]},
}
SCOPE_FOR = [("/portfolio/buy", "portfolio:write"), ("/portfolio/sell", "portfolio:write"),
             ("/portfolio/watchlist/", "portfolio:write"), ("/portfolio", "portfolio:read"), ("/v1/", "market:read")]


class Backends:
    def __init__(self):
        self.introspections = 0
        self.api_calls: list[tuple[httpx.Request, dict]] = []
        self.revoked: set[str] = set()
        self.bff_down = False
        self.api_status = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if request.url.host == "bff.internal":
            if self.bff_down:
                raise httpx.ConnectError("down", request=request)
            jwt.decode(token, PUB, algorithms=["EdDSA"], audience="bff-internal", issuer="mcp")  # raises if forged
            self.introspections += 1
            key = __import__("json").loads(request.content)["key"]
            info = KEYS.get(key)
            if not info or key in self.revoked:
                return httpx.Response(200, json={"active": False})
            return httpx.Response(200, json={"active": True, "key_id": key[-8:], "key_prefix": key[:12], **info})
        # the API
        claims = jwt.decode(token, PUB, algorithms=["EdDSA"], audience="investment-api", issuer="mcp")
        self.api_calls.append((request, claims))
        path = request.url.path
        if self.api_status:
            return httpx.Response(self.api_status, json={"detail": "upstream says no"})
        needed = next((s for prefix, s in SCOPE_FOR if path.startswith(prefix)), "market:read")
        if needed not in claims["scope"].split():
            return httpx.Response(403, json={"detail": f"Missing scope(s): {needed}"})
        if path == "/v1/instruments":
            return httpx.Response(200, json=[{"ticker": "ETE.AT", "name": "National Bank of Greece"}])
        if path == "/v1/instruments/XYZ":
            return httpx.Response(404, json={"detail": "Unknown ticker 'XYZ'"})
        if path.endswith("/prices"):
            bars = [{"date": f"2026-01-{(i % 28) + 1:02d}", "close": float(i)} for i in range(1000)]
            return httpx.Response(200, json={"ticker": "BTC-EUR", "currency": "EUR", "interval": request.url.params["interval"], "bars": bars})
        if path == "/v1/compare":
            return httpx.Response(200, json={"tickers": ["A", "B"], "points": [{"date": str(i)} for i in range(366)],
                                             "total_return": {"A": 0.1, "B": 0.2}})
        if path == "/portfolio/buy":
            return httpx.Response(200, json={"cash": 9000, "positions": [{"ticker": "AAPL", "qty": 1}]})
        if path == "/portfolio":
            return httpx.Response(200, json={"cash": 10000, "positions": []})
        return httpx.Response(200, json={"path": path})


@pytest.fixture
def backends():
    return Backends()


@pytest.fixture
def mcp_app(backends):
    auth.limiter._hits.clear()
    return create_app(httpx.AsyncClient(transport=httpx.MockTransport(backends.handler)))


@contextlib.asynccontextmanager
async def running(app):
    """Start the app's lifespan (the MCP session manager can start once per app instance)."""
    async with app.router.lifespan_context(app):
        yield


def raw_http(app, headers: dict | None = None) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://testserver", headers=headers or {})


@contextlib.asynccontextmanager
async def client_for(app, key: str | None):
    """An MCP client session over Streamable HTTP. The app must already be running."""
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with Client(streamable_http_client("http://testserver/mcp", http_client=raw_http(app, headers))) as client:
        yield client


@contextlib.asynccontextmanager
async def connect(app, key: str | None):
    async with running(app), client_for(app, key) as client:
        yield client


def run(coro):
    return asyncio.run(coro)
