import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { api } from "../auth/bff.js";
import { Card, ChangePill, IntradayChart } from "./parts.jsx";
import { athensDateTime, athensTime, eur, money, pct, qtyText, signedEur, tone } from "./format.js";
import { useCoach } from "../coach/coachContext.js";
import { PreTradeNudges } from "../coach/NudgeCard.jsx";

// The customer's practice portfolio on real prices: today's value curve, holdings,
// quick sells, the trade log and reset. Everything is computed by the API (/portfolio/*).
const REFRESH_MS = 60_000;

function SellInline({ position, onTrade }) {
  const [qty, setQty] = useState(String(position.qty));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const coach = useCoach();
  const [pending, setPending] = useState(null);
  const n = parseFloat(qty);
  const ok = isFinite(n) && n > 0 && n <= position.qty + 1e-9;
  const check = async () => {
    setBusy(true);
    const nudges = coach ? await coach.preTrade("sell", position.ticker, n) : [];
    setBusy(false);
    if (nudges.length) setPending(nudges);
    else sell();
  };
  const sell = async () => {
    setPending(null);
    setBusy(true);
    setErr(null);
    try {
      await onTrade("sell", position.ticker, n);
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  };
  return (
    <div>
      <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
        <input className="ip-input" style={{ width: 80, padding: "4px 6px" }} type="number" min="0" value={qty}
          onChange={(e) => setQty(e.target.value)} aria-label={`Quantity of ${position.ticker} to sell`} />
        <button className="ip-btn secondary sm" disabled={busy || !ok} onClick={check}>Sell</button>
        {err && <span style={{ color: "#EF3D3D", fontSize: 11.5 }}>{err}</span>}
      </div>
      {pending && (
        <div style={{ minWidth: 300 }}>
          <PreTradeNudges nudges={pending} side="sell" onContinue={sell} onCancel={() => setPending(null)} />
        </div>
      )}
    </div>
  );
}

const COST_PROFILES = [["low", "Low-cost online broker"], ["typical", "Typical bank broker"], ["high", "Expensive broker"], ["none", "No costs (ideal world)"]];

export default function PortfolioPage({ practice, goTo }) {
  const { portfolio, version, trade, reset } = practice;
  const [day, setDay] = useState(null);
  const [log, setLog] = useState([]);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () => {
      api("/portfolio/intraday").then((d) => { if (alive) setDay(d); }).catch(() => {});
      api("/portfolio/transactions?limit=50").then((t) => { if (alive) setLog(t); }).catch(() => {});
    };
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => { alive = false; clearInterval(id); };
  }, [version]);

  if (!portfolio) return <div className="ip-empty">{practice.error || "Loading your portfolio…"}</div>;
  const p = portfolio;

  return (
    <div>
      <h1 className="ip-page-title">Practice portfolio</h1>
      <p className="ip-page-sub">
        Virtual money on real, delayed prices. You started with {eur(p.starting_cash)}; buying takes cash, selling
        brings it back at the current price. Saved to your account.
      </p>

      <Card>
        <div className="ip-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 14 }}>
          <div>
            <div className="ip-label">Total value</div>
            <div className="ip-serif" style={{ fontSize: 26, fontWeight: 600 }}>{eur(p.total_value)}</div>
          </div>
          <div>
            <div className="ip-label">Today</div>
            <div style={{ fontSize: 18, fontWeight: 600 }} className={tone(p.day_change)}>{signedEur(p.day_change)}</div>
            <ChangePill value={p.day_change_pct} size={11.5} />
          </div>
          <div>
            <div className="ip-label">Since start</div>
            <div style={{ fontSize: 18, fontWeight: 600 }} className={tone(p.total_pnl)}>{signedEur(p.total_pnl)}</div>
            <ChangePill value={p.total_pnl_pct} size={11.5} />
          </div>
          <div>
            <div className="ip-label">Available cash</div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>{eur(p.cash)}</div>
            <div style={{ fontSize: 11.5, color: "#636B7E" }}>Invested {eur(p.holdings_value)}</div>
          </div>
          <div>
            <div className="ip-label">Realised from sales</div>
            <div style={{ fontSize: 18, fontWeight: 600 }} className={tone(p.realized_pnl)}>{signedEur(p.realized_pnl)}</div>
          </div>
          <div>
            <div className="ip-label">Transaction costs paid</div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>{eur(p.fees_paid)}</div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 12, fontSize: 13 }}>
          <label htmlFor="cost-profile">Broker costs:</label>
          <select id="cost-profile" className="ip-select" style={{ maxWidth: 260 }} value={p.cost_profile}
            onChange={async (e) => { await api("/portfolio/cost-profile", { method: "POST", body: { profile: e.target.value } }); practice.refresh(); }}>
            {COST_PROFILES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
          <span style={{ color: "#636B7E", fontSize: 12 }}>Illustrative; applies to your next trades.</span>
        </div>
      </Card>

      <Card title="Value today" right={day && <span style={{ fontSize: 12, color: "#636B7E" }}>Athens time · dashed line: value this morning</span>}>
        <IntradayChart points={(day?.points || []).map((x) => ({ t: x.t, v: x.value }))} base={day?.start_value} format={(v) => eur(v, 0)} />
        {day?.trades?.length > 0 && (
          <div style={{ fontSize: 12.5, color: "#636B7E", marginTop: 6 }}>
            Today's trades: {day.trades.map((t) => `${athensTime(t.executed_at)} ${t.side} ${qtyText(t.qty)} ${t.ticker}`).join(" · ")}
          </div>
        )}
      </Card>

      <Card title="Holdings" right={<button className="ip-btn secondary sm" onClick={() => goTo("discover")}>Buy something</button>}>
        {p.positions.length === 0 ? (
          <div className="ip-empty">No positions yet. Open Markets, pick an instrument and buy it with your virtual cash.</div>
        ) : (
          <div className="ip-table-wrap">
            <table className="ip-table">
              <thead>
                <tr><th>Instrument</th><th>Qty</th><th className="ip-hide-sm">Avg cost</th><th>Price</th><th className="ip-hide-sm">Today</th><th>Value</th><th>Gain / loss</th><th>Sell</th></tr>
              </thead>
              <tbody>
                {p.positions.map((x) => (
                  <tr key={x.ticker}>
                    <td className="clickable" onClick={() => goTo("asset", x.ticker)}>
                      <div style={{ fontWeight: 600 }}>{x.ticker}</div>
                      <div style={{ fontSize: 11.5, color: "#636B7E" }}>{x.name}</div>
                    </td>
                    <td>{qtyText(x.qty)}</td>
                    <td className="ip-hide-sm">{eur(x.avg_cost)}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {money(x.price_local, x.currency)}
                      {x.currency !== "EUR" && <div style={{ fontSize: 11.5, color: "#636B7E" }}>{eur(x.price)}</div>}
                    </td>
                    <td className="ip-hide-sm"><ChangePill value={x.day_change_pct} size={11.5} /></td>
                    <td>{eur(x.value)}</td>
                    <td className={tone(x.unrealized_pnl)} style={{ whiteSpace: "nowrap" }}>
                      {signedEur(x.unrealized_pnl)}<div style={{ fontSize: 11.5 }}>{pct(x.unrealized_pnl_pct)}</div>
                    </td>
                    <td><SellInline key={`${x.ticker}-${x.qty}`} position={x} onTrade={trade} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Trade log">
        {log.length === 0 ? <div className="ip-empty">No trades yet.</div> : (
          <div className="ip-table-wrap">
            <table className="ip-table">
              <thead><tr><th>When</th><th>Side</th><th>Instrument</th><th>Qty</th><th className="ip-hide-sm">Price</th><th>Amount</th><th>Costs</th><th>Realised</th></tr></thead>
              <tbody>
                {log.map((t) => (
                  <tr key={t.id}>
                    <td style={{ whiteSpace: "nowrap" }}>{athensDateTime(t.executed_at)}</td>
                    <td className={t.side === "buy" ? "ip-pos" : "ip-neg"}>{t.side.toUpperCase()}</td>
                    <td>{t.ticker}</td>
                    <td>{qtyText(t.qty)}</td>
                    <td className="ip-hide-sm" style={{ whiteSpace: "nowrap" }}>{money(t.price_local ?? t.price, t.currency)}</td>
                    <td>{t.side === "buy" ? "−" : "+"}{eur(t.amount)}</td>
                    <td>{t.fees ? eur(t.fees) : "–"}</td>
                    <td className={tone(t.realized_pnl)}>{t.realized_pnl == null ? "" : signedEur(t.realized_pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div style={{ marginTop: 12 }}>
          {!confirmReset ? (
            <button className="ip-btn danger sm" onClick={() => setConfirmReset(true)}><Trash2 size={12} /> Start again</button>
          ) : (
            <span style={{ fontSize: 12.5 }}>
              Clear all holdings and trades and go back to {eur(p.starting_cash)} in cash?{" "}
              <span className="ip-link" onClick={async () => { await reset(); setConfirmReset(false); }}>Yes, start again</span>
              {" · "}<span className="ip-link" onClick={() => setConfirmReset(false)}>Cancel</span>
            </span>
          )}
        </div>
      </Card>
    </div>
  );
}
