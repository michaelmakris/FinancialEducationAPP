"""
Investment Lab MCP server (Streamable HTTP).

    POST/GET /mcp     MCP endpoint, Authorization: Bearer fea_mcp_... (customer access key)
    GET /health       liveness
    GET /metrics      Prometheus

Run:  uvicorn app.main:app --port 8090      (from mcp-server/, after `python -m scripts.generate_keys --name mcp` in bff/)
"""
from __future__ import annotations

import httpx
from mcp.server.transport_security import TransportSecuritySettings
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth import AccessKeyVerifier, signing_key
from .config import settings
from .tools import build_server


def create_app(http: httpx.AsyncClient | None = None) -> Starlette:
    """`http` is used for both the BFF key check and the API calls (tests pass a mock transport)."""
    signing_key()  # fail at startup if the key is missing, not on the first customer call
    http = http or httpx.AsyncClient(timeout=settings.upstream_timeout_s)
    mcp = build_server(http, AccessKeyVerifier(http))

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    @mcp.custom_route("/metrics", methods=["GET"], include_in_schema=False)
    async def metrics(request: Request) -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,   # each request is authenticated on its own; any replica can serve it
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                                     allowed_hosts=settings.allowed_hosts),
    )
    app.state.mcp = mcp
    return app


app = create_app()
