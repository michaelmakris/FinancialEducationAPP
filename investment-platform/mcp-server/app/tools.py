"""
MCP tools over the Investment Lab API, acting as the customer who owns the
access key. Read tools need `market:read` / `portfolio:read`; the two write tools
(virtual trades, watchlist) need a key created with "trade" access.
"""
from __future__ import annotations

import datetime
import functools
import time
from typing import Any, Literal

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from prometheus_client import Counter, Histogram

from .auth import AccessKeyVerifier, limiter, mint
from .config import settings

TOOL_CALLS = Counter("mcp_tool_calls_total", "Tool calls", ["tool", "outcome"])  # ok | denied | error | limited
TOOL_LATENCY = Histogram("mcp_tool_latency_seconds", "Tool latency", ["tool"],
                         buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30))

INSTRUCTIONS = """\
Investment Lab: an educational investing app. These tools read real market data (Euronext Athens
stocks, the Athens General index, global benchmarks, 12 major crypto assets in EUR), annual-report
fundamentals of Greek listed companies (ESEF/IFRS), and Greek/EU/global macro indicators, plus the
user's own *virtual* practice portfolio (simulated prices and virtual cash: no real money moves).

Model estimates (risk, quality, market conditions) come only from models that passed out-of-sample
validation; quote their uncertainty and never present them as certain. Ground every number in a tool
result and say where it comes from. This is education, not
investment advice: don't tell the user what to buy or sell; explain data, risk and trade-offs.
Prices for Athens stocks are end-of-day; crypto updates every few hours."""

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

_SCOPE_HELP = {
    "portfolio:write": "This access key is read-only. To let the assistant place virtual trades, create a key with "
                       "'trade' access in the app (Security → AI assistant access).",
}


class Api:
    """Calls the API as the customer behind the current access key."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http

    async def call(self, method: str, path: str, scope: str, *, params: dict | None = None, body: dict | None = None) -> Any:
        tok = get_access_token()
        if tok is None or not tok.subject:
            raise ToolError("Not authenticated")
        if scope not in tok.scopes:
            raise PermissionError(_SCOPE_HELP.get(scope, f"This access key does not include '{scope}'."))
        if not limiter.allow(tok.client_id, settings.calls_per_minute):
            raise OverflowError(f"Too many requests: at most {settings.calls_per_minute} per minute per access key.")
        api_token = mint(settings.api_audience, tok.subject, " ".join(tok.scopes))
        params = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            r = await self.http.request(method, f"{settings.api_base_url}{path}", params=params, json=body,
                                        headers={"Authorization": f"Bearer {api_token}"})
        except httpx.HTTPError:
            raise ToolError("The market data service is temporarily unavailable. Try again shortly.")
        if r.status_code in (400, 404, 409, 422):
            detail = r.json().get("detail") if "json" in r.headers.get("content-type", "") else None
            raise ToolError(detail if isinstance(detail, str) else f"Request rejected ({r.status_code})")
        if r.status_code in (401, 403):
            raise ToolError("The service refused this request. The access key may lack permission or be expired.")
        if r.status_code >= 500:
            raise ToolError("The market data service had an error. Try again shortly.")
        return r.json()


def tracked(fn):
    """Per-tool metrics; turns permission/limit problems into clear tool errors."""
    name = fn.__name__

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        started = time.perf_counter()
        try:
            result = await fn(*args, **kwargs)
            TOOL_CALLS.labels(name, "ok").inc()
            return result
        except PermissionError as e:
            TOOL_CALLS.labels(name, "denied").inc()
            raise ToolError(str(e))
        except OverflowError as e:
            TOOL_CALLS.labels(name, "limited").inc()
            raise ToolError(str(e))
        except ToolError:
            TOOL_CALLS.labels(name, "error").inc()
            raise
        finally:
            TOOL_LATENCY.labels(name).observe(time.perf_counter() - started)

    return wrapper


def _thin(points: list, max_points: int) -> list:
    """Evenly keep at most max_points (always the first and last)."""
    if len(points) <= max_points:
        return points
    step = (len(points) - 1) / (max_points - 1)
    return [points[round(i * step)] for i in range(max_points)]


def build_server(http: httpx.AsyncClient, verifier: AccessKeyVerifier) -> MCPServer:
    api = Api(http)
    server = MCPServer(
        name="investment-lab", title="Investment Lab market data", version="1.0.0", instructions=INSTRUCTIONS,
        token_verifier=verifier,
        auth=AuthSettings(issuer_url=settings.auth_server_url, resource_server_url=settings.public_url,
                          required_scopes=["market:read"], validate_token_resource=True),
    )

    # ------------------------------------------------------------ market data
    @server.tool(annotations=READ)
    @tracked
    async def search_instruments(query: str | None = None,
                                 market: Literal["athens", "europe", "us", "etf", "crypto", "index"] | None = None,
                                 asset_type: Literal["equity", "index", "etf", "crypto"] | None = None,
                                 country: str | None = None, sector: str | None = None) -> list[dict]:
        """Find instruments with real market data by market: athens (Athens-listed stocks, e.g. ETE.AT),
        europe (euro-area large caps, e.g. SAP.DE), us (US large caps, tickers end in .US, e.g. AAPL.US),
        etf (EUR-listed ETFs, e.g. IWDA.AS), crypto (BTC-EUR...) and index (GD.AT, ^STOXX50E, ^GSPC;
        not tradable). Returns last close, 1-day change and 1-month / 1-year returns (0.05 = +5%)."""
        return await api.call("GET", "/v1/instruments", "market:read",
                              params={"q": query, "market": market, "asset_type": asset_type, "country": country,
                                      "sector": sector})

    @server.tool(annotations=READ)
    @tracked
    async def get_instrument(ticker: str) -> dict:
        """Details for one instrument: returns over 1w..5y and YTD, 1-year volatility and max drawdown,
        and for crypto the market cap and rank."""
        return await api.call("GET", f"/v1/instruments/{ticker}", "market:read")

    @server.tool(annotations=READ)
    @tracked
    async def get_price_history(ticker: str, start: datetime.date | None = None, end: datetime.date | None = None,
                                interval: Literal["auto", "daily", "weekly", "monthly"] = "auto") -> dict:
        """Price bars (open/high/low/close/adjusted close/volume). 'auto' picks daily up to 6 months,
        weekly up to 3 years, monthly beyond. At most 400 bars are returned (the most recent)."""
        end = end or datetime.date.today()
        start = start or end - datetime.timedelta(days=365)
        if interval == "auto":
            span = (end - start).days
            interval = "daily" if span <= 183 else "weekly" if span <= 1100 else "monthly"
        data = await api.call("GET", f"/v1/instruments/{ticker}/prices", "market:read",
                              params={"start": start.isoformat(), "end": end.isoformat(), "interval": interval})
        data["truncated"] = len(data["bars"]) > 400
        data["bars"] = data["bars"][-400:]
        return data

    @server.tool(annotations=READ)
    @tracked
    async def compare_instruments(tickers: list[str], start: datetime.date | None = None,
                                  end: datetime.date | None = None) -> dict:
        """Compare 2-10 instruments rebased to 100 at a common start (default: last year): total return
        per instrument plus up to 120 chart points. Returns are in each instrument's own currency."""
        data = await api.call("GET", "/v1/compare", "market:read", params={
            "tickers": ",".join(tickers), "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None})
        data["points"] = _thin(data["points"], 120)
        return data

    @server.tool(annotations=READ)
    @tracked
    async def get_fundamentals(ticker: str) -> dict:
        """Annual-report figures (consolidated IFRS, from the company's ESEF filing) per fiscal year:
        revenue, profit, equity, cash flow, bank metrics (net interest income, loans, deposits), ratios
        (ROE, margins, payout, growth) and P/E. Each metric lists the IFRS concept it came from."""
        return await api.call("GET", f"/v1/instruments/{ticker}/fundamentals", "market:read")

    @server.tool(annotations=READ)
    @tracked
    async def get_crypto_market() -> dict:
        """Crypto overview: coins by market-cap rank with price, market cap and volume (EUR), plus the
        Crypto Fear & Greed index and total DeFi value locked."""
        return await api.call("GET", "/v1/crypto/market", "market:read")

    @server.tool(annotations=READ)
    @tracked
    async def list_macro_indicators(category: Literal["macro", "rates", "fx", "sentiment", "commodities", "crypto"] | None = None,
                                    geo: str | None = None) -> list[dict]:
        """Macro indicators with today's snapshot: Greek inflation (HICP), unemployment, GDP growth,
        household saving, government debt, consumer confidence, ECB rates, Euribor, Greek 10y yield and
        spread vs Germany, Greek mortgage/deposit rates, EUR/USD, US rates, VIX, Brent. Each snapshot has
        the 90-day direction, the value a year ago, the EU-27 average where relevant, and whether it is
        fresh enough to quote (payload_eligible)."""
        return await api.call("GET", "/v1/macro/indicators", "market:read", params={"category": category, "geo": geo})

    @server.tool(annotations=READ)
    @tracked
    async def get_macro_indicator(indicator_id: str, start: datetime.date | None = None,
                                  end: datetime.date | None = None) -> dict:
        """One indicator (e.g. hicp_yoy, unemp, spread_10y, ecb_dfr, mortgage_rate) with its snapshot and
        history at its native frequency (default: last 5 years, at most 260 points)."""
        info = await api.call("GET", f"/v1/macro/indicators/{indicator_id}", "market:read")
        series = await api.call("GET", f"/v1/macro/indicators/{indicator_id}/series", "market:read",
                                params={"start": start.isoformat() if start else None, "end": end.isoformat() if end else None})
        info["points"] = _thin(series["points"], 260)
        return info

    # ------------------------------------------------------------ model estimates (validated models only)
    @server.tool(annotations=READ)
    @tracked
    async def get_risk_estimates(ticker: str) -> dict:
        """Model estimates for one instrument: expected 21-day volatility (annualised), probability of a fall
        of more than 10% over the next 21 trading days, beta vs its benchmark, the company's quality score
        within its peer group, and the 1-month direction model (reported as not served when it failed
        validation). Each block names the model version; only validated models are served."""
        return await api.call("GET", f"/v1/predictions/instruments/{ticker}", "market:read")

    @server.tool(annotations=READ)
    @tracked
    async def get_market_conditions() -> dict:
        """Athens market: measured current conditions (volatility percentile, drawdown, calm/normal/stressed)
        and the stress-forecast model, which is reported as not served unless it beat its baseline."""
        return await api.call("GET", "/v1/predictions/market", "market:read")

    @server.tool(annotations=READ)
    @tracked
    async def get_quality_ranking(peer_group: Literal["banks", "non-banks"] | None = None) -> dict:
        """Athens-listed companies ranked 0-100 by annual-report quality (profitability, margins, balance sheet,
        growth) within their peer group. A transparent ranking, not a recommendation."""
        return await api.call("GET", "/v1/predictions/quality", "market:read", params={"peer_group": peer_group})

    @server.tool(annotations=READ)
    @tracked
    async def get_model_validation() -> dict:
        """How every model was validated: out-of-sample metrics vs its baseline, approval status and reason.
        Use this to explain how far the estimates can be trusted."""
        return await api.call("GET", "/v1/predictions/models", "market:read")

    # ------------------------------------------------------------ the customer's virtual portfolio
    @server.tool(annotations=READ)
    @tracked
    async def get_portfolio() -> dict:
        """The user's virtual practice portfolio: cash, positions, value and P&L. Practice money only;
        positions are priced from the app's simulated practice market."""
        return await api.call("GET", "/portfolio", "portfolio:read")

    @server.tool(annotations=READ)
    @tracked
    async def get_watchlist() -> list:
        """Tickers on the user's watchlist."""
        return await api.call("GET", "/portfolio/watchlist", "portfolio:read")

    @server.tool(annotations=READ)
    @tracked
    async def get_my_risk_profile() -> dict:
        """The user's risk profile (1 very conservative .. 7 very adventurous) from the app's questionnaire,
        with why it came out that way. Not found if they have not answered it in the app yet."""
        return await api.call("GET", "/v1/profile", "portfolio:read")

    @server.tool(annotations=READ)
    @tracked
    async def get_my_proposal() -> dict:
        """The user's latest educational proposal for their practice portfolio: illustrative mix by asset class,
        expected volatility, stress tests (incl. a replay of the 2020 crash), how their current practice portfolio
        compares, macro context and example instruments to research. Explain it; never present it as advice.
        Proposals are generated in the app (My plan)."""
        return await api.call("GET", "/v1/proposals/latest", "portfolio:read")

    @server.tool(annotations=WRITE)
    @tracked
    async def place_virtual_trade(side: Literal["buy", "sell"], ticker: str, quantity: float) -> dict:
        """Buy or sell in the user's VIRTUAL practice portfolio (virtual euros, real delayed prices). Only when
        the user explicitly asks for this trade. Needs an access key with 'trade' access."""
        if quantity <= 0:
            raise ToolError("quantity must be positive")
        return await api.call("POST", f"/portfolio/{side}", "portfolio:write", body={"ticker": ticker, "qty": quantity})

    @server.tool(annotations=WRITE)
    @tracked
    async def update_watchlist(action: Literal["add", "remove"], ticker: str) -> list:
        """Add a ticker to, or remove it from, the user's watchlist. Needs an access key with 'trade' access."""
        await api.call("POST" if action == "add" else "DELETE", f"/portfolio/watchlist/{ticker}", "portfolio:write")
        return await api.call("GET", "/portfolio/watchlist", "portfolio:read")

    return server
