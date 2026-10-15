import { useCallback, useEffect, useState } from "react";
import { api } from "../auth/bff.js";

// The customer's practice portfolio, kept on the server (GET /portfolio) and
// refreshed every minute so values follow the market. `version` changes after
// every trade or reset so pages showing today's curve or the trade log reload.
const REFRESH_MS = 60_000;

export function usePractice() {
  const [portfolio, setPortfolio] = useState(null);
  const [error, setError] = useState(null);
  const [version, setVersion] = useState(0);

  const refresh = useCallback(async () => {
    try {
      setPortfolio(await api("/portfolio"));
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const load = () => api("/portfolio")
      .then((p) => { if (alive) { setPortfolio(p); setError(null); } })
      .catch((e) => { if (alive) setError(e.message); });
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  // Throws on refusal (not enough cash, not held, unknown ticker) so the caller can show why.
  const trade = useCallback(async (side, ticker, qty) => {
    const next = await api(`/portfolio/${side}`, { method: "POST", body: { ticker, qty } });
    setPortfolio(next);
    setVersion((v) => v + 1);
    return next;
  }, []);

  const reset = useCallback(async () => {
    const next = await api("/portfolio/reset", { method: "POST" });
    setPortfolio(next);
    setVersion((v) => v + 1);
    return next;
  }, []);

  const held = useCallback((ticker) => portfolio?.positions.find((p) => p.ticker === ticker) || null, [portfolio]);

  return { portfolio, error, version, refresh, trade, reset, held };
}
