import { useEffect, useMemo, useState } from "react";
import { Star } from "lucide-react";
import { api } from "../auth/bff.js";
import { ChangePill } from "./parts.jsx";
import { money } from "./format.js";

// Browse the real instruments by market (Athens, Europe, US, ETFs, Crypto, Indices).
const KEY = "fea.market";

function storedMarket() {
  try {
    return localStorage.getItem(KEY) || "athens";
  } catch {
    return "athens";
  }
}

export default function MarketsPage({ watchlist, toggleWatch, goTo }) {
  const [markets, setMarkets] = useState([]);
  const [market, setMarket] = useState(storedMarket);
  const [rows, setRows] = useState({});          // market id -> instruments
  const [query, setQuery] = useState("");
  const [sector, setSector] = useState("");
  const [sort, setSort] = useState({ key: "name", dir: 1 });
  const [error, setError] = useState(null);

  useEffect(() => {
    api("/v1/markets").then(setMarkets).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (rows[market]) return;
    let alive = true;
    api(`/v1/instruments?market=${market}`)
      .then((list) => { if (alive) setRows((r) => ({ ...r, [market]: list })); })
      .catch((e) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [market, rows]);

  const choose = (id) => {
    setMarket(id);
    setSector("");
    try { localStorage.setItem(KEY, id); } catch { /* not remembered */ }
  };

  const list = rows[market];
  const sectors = useMemo(() => [...new Set((list || []).map((r) => r.sector))].sort(), [list]);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const out = (list || []).filter((r) => (!sector || r.sector === sector) &&
      (!q || r.ticker.toLowerCase().includes(q) || r.name.toLowerCase().includes(q)));
    const { key, dir } = sort;
    return out.sort((a, b) => {
      const av = a[key], bv = b[key];
      if (av == null) return 1;
      if (bv == null) return -1;
      return (typeof av === "string" ? av.localeCompare(bv) : av - bv) * dir;
    });
  }, [list, query, sector, sort]);

  const sortBy = (key) => setSort((s) => ({ key, dir: s.key === key ? -s.dir : key === "name" || key === "ticker" ? 1 : -1 }));
  const current = markets.find((m) => m.id === market);
  const th = (key, label) => (
    <th onClick={() => sortBy(key)} style={{ cursor: "pointer", whiteSpace: "nowrap" }}>
      {label}{sort.key === key ? (sort.dir > 0 ? " ↑" : " ↓") : ""}
    </th>
  );

  return (
    <div>
      <h1 className="ip-page-title">Markets</h1>
      <p className="ip-page-sub">
        Real instruments to research and practise with. Prices are end-of-day closes and delayed intraday
        quotes from free sources, for learning only.
      </p>

      <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
        {markets.map((m) => (
          <span key={m.id} className={`ip-chip ${market === m.id ? "on" : ""}`} onClick={() => choose(m.id)}>
            {m.label} <span style={{ opacity: 0.6 }}>{m.count}</span>
          </span>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
        <input className="ip-input" style={{ flex: "1 1 220px" }} placeholder="Search by name or ticker"
          value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search instruments" />
        <select className="ip-select" style={{ flex: "0 1 200px" }} value={sector} onChange={(e) => setSector(e.target.value)} aria-label="Sector">
          <option value="">All sectors</option>
          {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {current && !current.tradable && (
        <p style={{ fontSize: 12.5, color: "#636B7E" }}>Indices are shown for reference and cannot be traded.</p>
      )}
      {error && <p role="alert" style={{ color: "#EF3D3D" }}>{error}</p>}
      {!list ? <div className="ip-empty">Loading…</div> : (
        <div className="ip-table-wrap">
          <table className="ip-table">
            <thead>
              <tr>
                <th></th>{th("ticker", "Ticker")}{th("name", "Name")}<th className="ip-hide-sm">Sector</th>
                {th("last_close", "Last")}{th("change_1d", "1D")}<th className="ip-hide-sm" onClick={() => sortBy("return_1m")}>1M</th>{th("return_1y", "1Y")}
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.ticker} className="clickable" onClick={() => goTo("asset", r.ticker)}>
                  <td onClick={(e) => { e.stopPropagation(); toggleWatch(r.ticker); }}>
                    <Star size={14} fill={watchlist.includes(r.ticker) ? "var(--ip-accent)" : "none"}
                      color={watchlist.includes(r.ticker) ? "var(--ip-accent)" : "#CDD3E3"} />
                  </td>
                  <td style={{ fontWeight: 600, whiteSpace: "nowrap" }}>{r.ticker}</td>
                  <td>{r.name}</td>
                  <td className="ip-hide-sm" style={{ color: "#636B7E" }}>{r.sector}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{money(r.last_close, r.currency)}</td>
                  <td><ChangePill value={r.change_1d} size={12} /></td>
                  <td className="ip-hide-sm"><ChangePill value={r.return_1m} size={12} /></td>
                  <td><ChangePill value={r.return_1y} size={12} /></td>
                </tr>
              ))}
              {shown.length === 0 && <tr><td colSpan={8} className="ip-empty">Nothing matches.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
