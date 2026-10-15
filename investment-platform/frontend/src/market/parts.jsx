import { useEffect, useState } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../auth/bff.js";
import { athensTime, eur, money, pct, qtyText } from "./format.js";
import { useCoach } from "../coach/coachContext.js";
import { PreTradeNudges } from "../coach/NudgeCard.jsx";

// Building blocks shared by the Markets, Instrument and Portfolio pages.

export function Card({ title, right, children }) {
  return (
    <div className="ip-card">
      {(title || right) && (
        <div className="ip-row" style={{ marginBottom: 10, justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
          {title && <div className="ip-card-title">{title}</div>}
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

export function ChangePill({ value, size = 12.5 }) {
  if (value == null || !isFinite(value)) return <span style={{ color: "var(--ip-muted, #636B7E)" }}>{"—"}</span>;
  const up = value >= 0;
  return (
    <span className={up ? "ip-pos" : "ip-neg"} style={{
      fontSize: size, fontWeight: 700, padding: "2px 9px", borderRadius: 999, whiteSpace: "nowrap",
      background: up ? "#E1F9EC" : "#FEECEC",
    }}>{pct(value)}</span>
  );
}

export function MarketStatus({ open, live }) {
  const text = !live ? "Last close (live price unavailable)" : open ? "Market open · delayed" : "Market closed · last price";
  return (
    <span style={{ fontSize: 11.5, padding: "2px 8px", borderRadius: 999, border: "1px solid #CDD3E3",
      color: open && live ? "#0EA65C" : "#636B7E", whiteSpace: "nowrap" }}>
      {"●"} {text}
    </span>
  );
}

// A value or price through the day. points: [{t, v}]; base: the reference line (previous close / start value).
export function IntradayChart({ points, base, format, height = 220 }) {
  if (!points || points.length < 2) {
    return <div className="ip-empty">No price moves yet today.</div>;
  }
  const data = points.map((p) => ({ t: p.t, v: p.v, label: athensTime(p.t) }));
  const last = data[data.length - 1].v;
  const up = base == null || last >= base;
  const color = up ? "#0EA65C" : "#EF3D3D";
  const vals = data.map((d) => d.v).concat(base != null ? [base] : []);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.002 || 1;
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={`fill-${up ? "up" : "down"}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.25} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#E6E9F2" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} minTickGap={40} />
          <YAxis domain={[lo - pad, hi + pad]} tick={{ fontSize: 11 }} width={70} tickFormatter={(v) => format(v)} />
          <Tooltip formatter={(v) => [format(v), "Value"]} labelFormatter={(l) => `${l} (Athens)`} />
          {base != null && <ReferenceLine y={base} stroke="#94A3B8" strokeDasharray="4 4" />}
          <Area type="monotone" dataKey="v" stroke={color} strokeWidth={2} fill={`url(#fill-${up ? "up" : "down"})`} dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// Buy / sell box. quote: {last, last_eur, currency}; position: from the portfolio or null.
// Transaction costs of the trade being typed: your broker profile, and the low-high range (GET /portfolio/costs).
function useTradeCosts(ticker, qty) {
  const [costs, setCosts] = useState(null);
  useEffect(() => {
    if (!(qty > 0)) return undefined;
    let alive = true;
    const id = setTimeout(() => {
      api(`/portfolio/costs?ticker=${encodeURIComponent(ticker)}&qty=${qty}`)
        .then((c) => { if (alive) setCosts(c); }).catch(() => {});
    }, 300);
    return () => { alive = false; clearTimeout(id); };
  }, [ticker, qty]);
  return qty > 0 ? costs : null;
}

const COST_PARTS = [["commission", "Broker commission"], ["exchange", "Exchange fees"], ["spread", "Bid/ask spread"], ["fx", "Currency conversion"]];

function CostLine({ costs }) {
  const [open, setOpen] = useState(false);
  if (!costs) return null;
  const c = costs.costs, r = costs.range;
  const label = costs.profiles?.[costs.profile]?.en || costs.profile;
  return (
    <div style={{ fontSize: 12.5, background: "#F6F7FB", borderRadius: 10, padding: "8px 10px", marginBottom: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <span>Costs ({label}): <b>{eur(c.total)}</b>{c.total > 0 ? ` · ${(c.pct * 100).toFixed(2)}%` : ""}</span>
        <button onClick={() => setOpen(!open)} style={{ border: 0, background: "none", color: "var(--ip-accent, #2F5BFF)", cursor: "pointer", padding: 0 }}>
          {open ? "Hide" : "Details"}
        </button>
      </div>
      <div style={{ color: "#636B7E", marginTop: 2 }}>
        Range for this trade: {eur(r.low.total)} (low-cost broker) to {eur(r.high.total)} (expensive broker)
      </div>
      {open && (
        <table style={{ width: "100%", marginTop: 6, fontSize: 12 }}>
          <thead><tr><th style={{ textAlign: "left" }}></th><th>Yours</th><th>Low</th><th>Typical</th><th>High</th></tr></thead>
          <tbody>
            {COST_PARTS.filter(([k]) => r.high[k] > 0).map(([k, name]) => (
              <tr key={k}><td>{name}</td><td>{eur(c[k])}</td><td>{eur(r.low[k])}</td><td>{eur(r.typical[k])}</td><td>{eur(r.high[k])}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      {open && <div style={{ color: "#636B7E", marginTop: 4 }}>Illustrative broker costs; taxes are not included. Change your broker profile on the Portfolio page.</div>}
    </div>
  );
}

export function TradeBox({ ticker, quote, position, cash, onTrade, crypto }) {
  const [qty, setQty] = useState(crypto ? "0.01" : "1");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const n = parseFloat(qty);
  const valid = isFinite(n) && n > 0;
  const tradeCosts = useTradeCosts(ticker, valid ? n : 0);
  const fees = tradeCosts?.costs?.total ?? 0;
  const est = valid && quote?.last_eur ? n * quote.last_eur : null;
  const tooMuch = est != null && cash != null && est + fees > cash + 1e-9;
  const canSell = valid && position && n <= position.qty + 1e-9;

  const coach = useCoach();
  const [pending, setPending] = useState(null);   // Tsimp has something to say before this trade

  const run = async (side) => {
    setBusy(true);
    setMsg(null);
    const nudges = coach ? await coach.preTrade(side, ticker, n) : [];
    setBusy(false);
    if (nudges.length) setPending({ side, nudges });
    else execute(side);
  };

  const execute = async (side) => {
    setPending(null);
    setBusy(true);
    setMsg(null);
    try {
      await onTrade(side, ticker, n);
      setMsg({ ok: true, text: `${side === "buy" ? "Bought" : "Sold"} ${qtyText(n)} ${ticker} at ${money(quote.last, quote.currency)}.` });
    } catch (e) {
      setMsg({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="ip-grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
        <div>
          <label className="ip-label">Quantity</label>
          <input className="ip-input" type="number" min="0" step={crypto ? "0.0001" : "1"} value={qty}
            onChange={(e) => setQty(e.target.value)} aria-label="Quantity" />
        </div>
        <div>
          <label className="ip-label">Estimated amount</label>
          <div style={{ fontSize: 18, fontWeight: 600, paddingTop: 6 }}>{eur(est)}</div>
        </div>
      </div>
      <div style={{ fontSize: 12.5, color: "#636B7E", marginBottom: 10 }}>
        Price {money(quote?.last, quote?.currency)}
        {quote?.currency && quote.currency !== "EUR" ? ` = ${eur(quote.last_eur)}` : ""} · Cash {eur(cash)}
        {position ? ` · You hold ${qtyText(position.qty)}` : ""}
      </div>
      <CostLine costs={tradeCosts} />
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="ip-btn" disabled={busy || !valid || tooMuch || !quote?.last_eur} onClick={() => run("buy")}>Buy</button>
        <button className="ip-btn secondary" disabled={busy || !canSell} onClick={() => run("sell")}>Sell</button>
        {position && (
          <button className="ip-btn secondary sm" disabled={busy} onClick={() => setQty(String(position.qty))}>Sell all ({qtyText(position.qty)})</button>
        )}
      </div>
      {tooMuch && <div style={{ fontSize: 12, color: "#EF3D3D", marginTop: 6 }}>Not enough virtual cash for this buy.</div>}
      {pending && <PreTradeNudges nudges={pending.nudges} side={pending.side} onContinue={() => execute(pending.side)} onCancel={() => setPending(null)} />}
      {msg && <div role="status" style={{ fontSize: 12.5, marginTop: 8, color: msg.ok ? "#0EA65C" : "#EF3D3D" }}>{msg.text}</div>}
    </div>
  );
}
