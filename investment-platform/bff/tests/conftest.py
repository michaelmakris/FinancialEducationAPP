import os
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_tmp = Path(tempfile.mkdtemp(prefix="bff_test_"))
KEY = Ed25519PrivateKey.generate()
(_tmp / "priv.pem").write_bytes(KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                  serialization.NoEncryption()))
PUBLIC_KEY = KEY.public_key()
from cryptography.fernet import Fernet  # noqa: E402
(_tmp / "data_key").write_bytes(Fernet.generate_key())
MCP_KEY = Ed25519PrivateKey.generate()  # stands in for the MCP server's signing key
(_tmp / "mcp_pub.pem").write_bytes(MCP_KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
os.environ.update({
    "BFF_INTERNAL_CALLERS": f"mcp={_tmp / 'mcp_pub.pem'}",
    "BFF_DATA_KEY_FILE": str(_tmp / "data_key"),
    "BFF_REQUIRE_EMAIL_VERIFICATION": "true",
    "BFF_REQUIRE_MFA": "false",
    "BFF_PUBLIC_URL": "https://app.example",
    "BFF_DATABASE_URL": f"sqlite:///{_tmp / 'bff_test.db'}",
    "BFF_SIGNING_KEY_FILE": str(_tmp / "priv.pem"),
    "BFF_COOKIE_SECURE": "true",               # test the real cookie config over https://testserver
    "BFF_API_BASE_URL": "http://api.internal",
    "BFF_ALLOWED_ORIGINS": "https://testserver",
    "BFF_AUTH_RATE_PER_MINUTE": "1000",
})

import re  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app import mailer, security  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AccessKey, AuthEvent, AuthToken, Customer, RecoveryCode, Session  # noqa: E402

PASSWORD = "correct horse battery staple"


class FakeAPI:
    """Stands in for the API: records what the BFF sent, answers with a canned response."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.status = 200
        self.body = {"ok": True}
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        self.calls.append(request)
        return httpx.Response(self.status, json=self.body, headers={"x-internal-secret": "must-not-leak"})


@pytest.fixture
def api():
    return FakeAPI()


@pytest.fixture(autouse=True)
def mail():
    box = mailer.MemorySender()
    mailer.set_sender(box)
    return box


@pytest.fixture
def client(api):
    init_db()
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(api.handler))
    with TestClient(app, base_url="https://testserver") as c:
        yield c
    db = SessionLocal()
    for model in (AuthEvent, Session, AuthToken, RecoveryCode, AccessKey, Customer):
        db.execute(delete(model))
    db.commit()
    db.close()
    security.limiter.clear()


def register(c, email="maria@example.com", password=PASSWORD, full_name="Maria Papadopoulou"):
    return c.post("/bff/auth/register", json={"email": email, "password": password, "full_name": full_name})


def link_token(message, action: str) -> str:
    """Pull the token out of the link in an email we sent."""
    m = re.search(rf"action={action}&token=([A-Za-z0-9_\-]+)", message.get_content())
    assert m, message.get_content()
    return m.group(1)


def last_mail_to(mail, email):
    return [m for m in mail.sent if m["To"] == email][-1]


def signup(c, email="maria@example.com", password=PASSWORD, full_name="Maria Papadopoulou") -> dict:
    """Register, click the verification link from the email, sign in. Returns the login payload."""
    box = mailer.sender()
    assert register(c, email, password, full_name).status_code == 202
    token = link_token(last_mail_to(box, email), "verify-email")
    assert c.post("/bff/auth/verify-email", json={"token": token}).status_code == 200
    r = login(c, email, password)
    assert r.status_code == 200, r.text
    return r.json()


def login(c, email="maria@example.com", password=PASSWORD):
    return c.post("/bff/auth/login", json={"email": email, "password": password})


def csrf(c) -> dict:
    return {"X-CSRF-Token": c.get("/bff/auth/me").json()["csrf_token"]}
