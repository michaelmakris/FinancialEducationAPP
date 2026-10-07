# MCP server: Investment Lab for AI assistants

Lets an AI assistant (Claude Code, Claude Desktop via a remote-MCP bridge, or any MCP client that supports
Streamable HTTP with a custom header) use the platform **as a specific customer, with that customer's
permissions or fewer**.

```
AI client ──Bearer fea_mcp_…──► MCP server :8090 ──60 s token (iss=mcp, sub=customer)──► API :8000
                                     │
                                     └──"is this key valid?" (signed 60 s JWT)──► BFF /bff/internal/introspect
```

1. **The customer creates a key** in the web app: *Security → AI assistant access*.
   - Access level: *read only*, or *read + virtual trades*. Expiry: up to 90 days.
   - Creating a key needs the password, plus the MFA code if MFA is on, and sends an email notice.
   - The key is shown once and stored only as a SHA-256 hash.
2. **Every key is checked with the BFF.** The result is cached for `MCP_KEY_CACHE_S` (30 s), so a revoked key stops working within 30 s. A key also stops working when the account is disabled or MFA becomes required but isn't set up. If the BFF is unreachable, calls are refused rather than allowed.
3. **API calls use the key's scopes.** For each call the server signs a 60-second API token with its own Ed25519 key (`secrets/mcp_ed25519_private.pem`), carrying exactly the key's scopes. The API trusts it as issuer `mcp` and enforces the same per-route scopes as for the web app. A key can never get `chat` or staff scopes.

## Tools

| Tool | Needs | What |
|---|---|---|
| `search_instruments`, `get_instrument`, `get_price_history`, `compare_instruments` | read | Athens stocks, indices, ETFs, crypto: prices, returns, volatility, drawdown. Outputs are bounded (≤ 400 bars, ≤ 120 comparison points). |
| `get_fundamentals` | read | ESEF/IFRS annual-report figures and ratios per fiscal year |
| `get_crypto_market` | read | Coins by market cap, Fear & Greed, DeFi TVL |
| `list_macro_indicators`, `get_macro_indicator` | read | Greek/EU/global indicators with snapshot (90-day direction, 1y ago, EU-27) and history |
| `get_risk_estimates`, `get_market_conditions`, `get_quality_ranking`, `get_model_validation` | read | Validated model outputs (volatility, P(fall > 10%), beta, quality score, market conditions) and how each model was validated |
| `get_portfolio`, `get_watchlist` | read | The customer's virtual practice portfolio |
| `place_virtual_trade`, `update_watchlist` | trade | Virtual trades and watchlist edits (no real money) |

The server instructions tell the model to ground numbers in tool results and not to give investment advice.

## Connect

```bash
claude mcp add --transport http investment-lab http://localhost:8090/mcp --header "Authorization: Bearer fea_mcp_..."
```

## Run locally

```powershell
cd bff; python -m scripts.generate_keys --name mcp     # once: ../secrets/mcp_ed25519_{private,public}.pem
cd ../mcp-server
python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt
uvicorn app.main:app --port 8090
```

The API and the BFF pick up `secrets/mcp_ed25519_public.pem` automatically (restart them after creating the key). Settings are in `.env.example` (`MCP_*`).

## Operations

- `/health`, `/metrics`: `mcp_tool_calls_total{tool,outcome}` (ok / error / denied / limited), `mcp_tool_latency_seconds`, `mcp_auth_total{result}`.
- Alerts (`infra/prometheus/alerts.yml`, group `ai-assistants-mcp`): server down, key checks failing, tool error rate, invalid-key spike.
- Dashboard: *Customer Access (BFF)* → row *AI assistants (MCP)*.
- Limits: 60 tool calls per minute per key (in memory, per instance); stateless HTTP, so any replica can serve any request. DNS-rebinding protection is on, so set `MCP_ALLOWED_HOSTS` to the public hostname.
- Tests: `pytest` (11 tests). A real MCP client runs over Streamable HTTP in-process, against a fake BFF and API that verify the signed tokens.

## Later

- **OAuth instead of pasted keys:** let MCP clients sign the customer in with OAuth 2.1 (the BFF as the authorization server). The SDK already serves the protected-resource metadata; the key check and API-token flow stay as they are.
