// The browser only ever talks to the BFF, on the same origin (/bff/*, proxied by
// Vite in dev). The session lives in an HttpOnly cookie the page cannot read; the
// CSRF token comes from /bff/auth/me and is sent on every non-GET request.

let csrfToken = null;
const listeners = new Set();

export function setCsrfToken(token) {
  csrfToken = token;
}

// Called when the BFF says the session is gone (expired, revoked, logged out elsewhere).
export function onSignedOut(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export class BffError extends Error {
  constructor(status, detail) {
    super(detail || `Request failed (${status})`);
    this.status = status;
  }
}

export async function bffFetch(path, { method = "GET", body, headers = {} } = {}) {
  const opts = { method, credentials: "same-origin", headers: { Accept: "application/json", ...headers } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  if (method !== "GET" && csrfToken) opts.headers["X-CSRF-Token"] = csrfToken;
  const resp = await fetch(path, opts);
  if (resp.status === 204) return null;
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    if (resp.status === 401 && !path.startsWith("/bff/auth/login") && !path.startsWith("/bff/auth/register")) {
      listeners.forEach((fn) => fn());
    }
    const detail = typeof data.detail === "string" ? data.detail : null;
    throw new BffError(resp.status, detail);
  }
  return data;
}

// Calls to the API always go through the BFF proxy: api("/v1/instruments") -> /bff/api/v1/instruments
export const api = (path, opts) => bffFetch(`/bff/api${path.startsWith("/") ? path : `/${path}`}`, opts);
