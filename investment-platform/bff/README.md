# BFF: customer login and the only door to the API

```
browser ──cookie + CSRF──► BFF :8080 ──60 s Ed25519-signed token──► API :8000
          /bff/auth/*  register · login · logout · me · password · sessions
          /bff/api/*   allowlisted API routes, as the signed-in customer
```

- **Customers and credentials** live in the BFF's own tables (`auth_customers`, `auth_sessions`, `auth_tokens`, `auth_recovery_codes`, `auth_events`), never in the API's database tables. Passwords are stored as Argon2id hashes only.
- **Sessions are server-side.** The browser gets a random token in an `HttpOnly`, `SameSite=Strict` cookie (`__Host-` prefixed when `BFF_COOKIE_SECURE=true`); the database stores only its SHA-256. Sessions expire after 30 min idle and 12 h absolute, and a fresh ID is issued on every login.
- **CSRF:** every write needs the `X-CSRF-Token` from `/bff/auth/me`, and writes whose `Origin` is not in `BFF_ALLOWED_ORIGINS` are refused.
- **Brute force:** per-IP rate limit on login/register. Lockout after 5 failed attempts for 15 min, applied the same way to unknown emails, so responses don't reveal which accounts exist.
- **Password rules:** 12–128 characters, not a common or repetitive password, and not containing the user's name or email. Changing the password signs out all other devices and sends a security notice.
- **Email verification:** registration always answers 202 "check your inbox", whether or not the email exists, and the account works only after the link is clicked (valid 24 h). Signing in before verifying sends a fresh link; earlier links keep working until they expire.
- **Password reset:** the request always answers 202. The emailed link is single-use, expires in 30 min, and only the newest link works. Using it changes the password, unlocks the account, signs out every device and sends a notice. **MFA is still required at the next sign-in.**
- **Two-step verification (TOTP):** works with any authenticator app. Setup needs the password, then a QR code and a confirming code, and gives 10 one-time recovery codes.
  - Secrets are encrypted with a data key; recovery codes are stored as keyed hashes.
  - A code can't be reused, and each login challenge allows 5 tries, with 10 MFA failures per 15 min per account.
  - With `BFF_REQUIRE_MFA=true`, customers can't reach the API until they enrol, and can't turn it off.
- **Security notices** are emailed when the password is changed or reset, when two-step verification is turned on or off, when recovery codes are regenerated, and when a recovery code is used.
- **API access:** the BFF mints a token per call (`sub` = customer id, scopes by role, 60 s; 300 s for the chat assistant) and forwards only allowlisted routes. The API verifies the token with the BFF's public key, so it can check tokens but never create them.
- **Audit:** every security event is a row in `auth_events`, a count in `bff_auth_events_total`, and visible with `scripts.manage events`.
- **Rate limits:** in memory for a single instance; set `BFF_REDIS_URL` (docker-compose does) to share them between replicas.
- **Monitoring:** `/metrics`, alert rules in `infra/prometheus/alerts.yml` (group `customer-access`, including failing email delivery), Grafana dashboard *Customer Access (BFF)*.

## Email

| `BFF_EMAIL_BACKEND` | Behaviour |
|---|---|
| `outbox` (default) | Each email is written as a `.eml` file to `bff/outbox/`: open it and click the link. Nothing leaves the machine. |
| `smtp` | Any SMTP server or provider relay: `BFF_SMTP_HOST`, `BFF_SMTP_PORT`, `BFF_SMTP_USER`, `BFF_SMTP_PASSWORD`, `BFF_SMTP_SECURITY=starttls\|ssl\|none`. |

Links point at `BFF_PUBLIC_URL` (the frontend), e.g. `https://app.example/?action=reset-password&token=…`. The frontend removes the token from the address bar immediately.

## Staff administration

```powershell
python -m scripts.manage list
python -m scripts.manage set-role maria@example.com staff     # ends her sessions; new scopes at next sign-in
python -m scripts.manage unlock maria@example.com
python -m scripts.manage disable maria@example.com            # blocks sign-in, ends all sessions
python -m scripts.manage reset-mfa maria@example.com          # lost phone AND recovery codes: verify identity first
python -m scripts.manage events maria@example.com
```

Every action is written to `auth_events` with the operator's OS user name.

## Run locally

```powershell
cd bff
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m scripts.generate_keys            # once: ../secrets/bff_ed25519_{private,public}.pem + bff_data_key (git-ignored)
$env:BFF_COOKIE_SECURE="false"             # plain http dev (or keep true and use http://localhost only)
uvicorn app.main:app --port 8080
```

Then start the API as usual (it picks up `../secrets/bff_ed25519_public.pem` by default) and the frontend with `npm run dev`. Vite proxies `/bff/*` to `:8080`, and the app shows a sign-in screen first.

Tests: `pytest` (77 tests, no network). Migrations: `alembic upgrade head` (own version table `alembic_version_bff`, so it can share a Postgres database with the API).

## Before going live

- Set `BFF_EMAIL_BACKEND=smtp` with your provider or corporate relay, `BFF_PUBLIC_URL` to the real site, `BFF_COOKIE_SECURE=true` (HTTPS), and `BFF_REQUIRE_MFA=true`.
- Back up `secrets/bff_data_key` securely: without it, stored TOTP secrets can't be decrypted and everyone would need `reset-mfa`. Unlike the signing key, it is not rotated by `generate_keys --force`.
- Run at least two BFF replicas with `BFF_REDIS_URL` set.
- If the bank already has a customer identity provider with strong customer authentication, signing in through it (OIDC) can replace local passwords and TOTP; the session, CSRF, proxy and API-token parts stay the same.

## AI assistant access keys

`/bff/auth/access-keys` (list / create / revoke) and the internal `/bff/internal/introspect` used by the MCP server. See `../mcp-server/README.md`.
