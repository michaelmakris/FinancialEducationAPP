import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowLeft, Star } from "lucide-react";
import { api } from "../auth/bff.js";
import { Card, ChangePill, IntradayChart, MarketStatus, TradeBox } from "./parts.jsx";
import { athensTime, eur, money, pct, qtyText, signedEur, tone } from "./format.js";

// One real instrument: today's delayed price curve, longer history, and the practice trade box.
const RANGES = [["1M", 31], ["6M", 183], ["1Y", 365], ["5Y", 1826]];
const QUOTE_REFRESH_MS = 60_000;

// Older pages (and the AI analyst) may still pass demo tickers such as AAPL or BTC: try the real ones.
async function resolve(ticker) {
  for (const t of [ticker, `${ticker}.US`, `${ticker}-EUR`, `${ticker}.AT`]) {
    try {
      return await api(`/v1/instruments/${encodeURIComponent(t)}`);
    } catch (e) {
      if (e.status !== 404) throw e;
    }
  }
  return null;
}

function isoDaysAgo(days) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export default function InstrumentPage({ ticker, practice, watchlist, toggleWatch, goTo, onBack }) {
  const [detail, setDetail] = useState(undefined);   // undefined = loading, null = not found
  const [quote, setQuote] = useState(null);
  const [range, setRange] = useState(365);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState(null);
  const symbol = detail?.ticker;

  useEffect(() => {
    let alive = true;
    resolve(ticker).then((d) => { if (alive) setDetail(d); }).catch((e) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [ticker]);

  useEffect(() => {
    if (!symbol) return undefined;
    let alive = true;
    const load = () => api(`/v1/instruments/${encodeURIComponent(symbol)}/intraday`)
      .then((q) => { if (alive) setQuote(q); }).catch(() => {});
    load();
    const id = setInterval(load, QUOTE_REFRESH_MS);
    return () => { alive = false; clearInterval(id); };
  }, [symbol]);

  useEffect(() => {
    if (!symbol) return undefined;
    let alive = true;
    const interval = range > 400 ? "weekly" : "daily";
    api(`/v1/instruments/${encodeURIComponent(symbol)}/prices?start=${isoDaysAgo(range)}&interval=${interval}`)
      .then((s) => { if (alive) setHistory(s.bars.map((b) => ({ date: b.date, close: b.close }))); })
      .catch(() => { if (alive) setHistory([]); });
    return () => { alive = false; };
  }, [symbol, range]);

  if (error) return <p role="alert">{error}</p>;
  if (detail === undefined) return <div className="ip-empty">Loading…</div>;
  if (detail === null) {
    return (
      <div>
        <h1 className="ip-page-title">{ticker}</h1>
        <p className="ip-page-sub">This instrument is not in the real-market catalog.</p>
        <button className="ip-back" onClick={onBack}><ArrowLeft size={18} /> Back</button>{" "}
        <button className="ip-btn" onClick={() => goTo("discover")}>Browse markets</button>
      </div>
    );
  }

  const position = practice.held(detail.ticker);
  const cash = practice.portfolio?.cash;
  const watching = watchlist.includes(detail.ticker);
  const histChange = history.length > 1 ? history[history.length - 1].close / history[0].close - 1 : null;

  return (
    <div>
      <button className="ip-back" onClick={onBack} aria-label="Back"><ArrowLeft size={18} /> Back</button>
      <div className="ip-row" style={{ justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div>
          <h1 className="ip-page-title" style={{ marginBottom: 2 }}>{detail.name}</h1>
          <div style={{ fontSize: 13, color: "#636B7E" }}>
            {detail.ticker} · {detail.exchange || detail.asset_type} · {detail.sector} · {detail.currency}
          </div>
        </div>
        <button className="ip-btn secondary sm" onClick={() => toggleWatch(detail.ticker)}>
          <Star size={13} fill={watching ? "var(--ip-accent)" : "none"} /> {watching ? "Watching" : "Watch"}
        </button>
      </div>

      <Card title="Today" right={quote && <MarketStatus open={quote.market_open} live={quote.live} />}>
        <div className="ip-row" style={{ gap: 14, alignItems: "baseline", flexWrap: "wrap", marginBottom: 8 }}>
          <span className="ip-serif" style={{ fontSize: 28, fontWeight: 600 }}>{money(quote?.last, quote?.currency)}</span>
          <ChangePill value={quote?.change_pct} />
          {quote?.currency && quote.currency !== "EUR" && <span style={{ color: "#636B7E", fontSize: 13 }}>= {eur(quote.last_eur)}</span>}
          {quote?.as_of && <span style={{ color: "#636B7E", fontSize: 12 }}>as of {athensTime(quote.as_of)} Athens</span>}
        </div>
        <IntradayChart points={(quote?.points || []).map((p) => ({ t: p.t, v: p.price }))} base={quote?.prev_close}
          format={(v) => money(v, quote?.currency)} />
        <div style={{ fontSize: 11.5, color: "#636B7E", marginTop: 4 }}>Dashed line: previous close.</div>
      </Card>

      {quote?.tradable ? (
        <Card title="Practice trade">
          {position && (
            <div style={{ fontSize: 13, marginBottom: 10 }}>
              You hold <b>{qtyText(position.qty)}</b> worth <b>{eur(position.value)}</b> ·
              {" "}<span className={tone(position.unrealized_pnl)}>{signedEur(position.unrealized_pnl)} ({pct(position.unrealized_pnl_pct)})</span> since you bought
            </div>
          )}
          <TradeBox ticker={detail.ticker} quote={quote} position={position} cash={cash}
            onTrade={practice.trade} crypto={detail.asset_type === "crypto"} />
        </Card>
      ) : quote && (
        <Card><div style={{ fontSize: 13, color: "#636B7E" }}>Indices are for reference and cannot be traded.</div></Card>
      )}

      <Card title="Price history" right={
        <div style={{ display: "flex", gap: 6 }}>
          {RANGES.map(([label, days]) => (
            <span key={label} className={`ip-chip ${range === days ? "on" : ""}`} onClick={() => setRange(days)}>{label}</span>
          ))}
        </div>
      }>
        {history.length < 2 ? <div className="ip-empty">No history loaded yet.</div> : (
          <>
            <div style={{ fontSize: 13, marginBottom: 6 }}>Change over the period: <ChangePill value={histChange} /></div>
            <div style={{ width: "100%", height: 240 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={history} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E6E9F2" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} minTickGap={40} />
                  <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} width={70} tickFormatter={(v) => money(v, detail.currency)} />
                  <Tooltip formatter={(v) => [money(v, detail.currency), "Close"]} />
                  <Line type="monotone" dataKey="close" stroke="var(--ip-accent, #2F5BFF)" strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
