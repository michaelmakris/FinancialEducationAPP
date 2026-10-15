import { X } from "lucide-react";
import { useCoach } from "./coachContext.js";

// The mosquito's speech bubble: title, text with the customer's real numbers, buttons that
// open a lesson in the chat. Used for pop-ups and before trades.

export function Mosquito({ size = 44 }) {
  return (
    <div aria-hidden="true" style={{
      flexShrink: 0, width: size, height: size, borderRadius: "50%", background: "#F2F2F2",
      display: "flex", alignItems: "center", justifyContent: "center", fontSize: size * 0.55,
    }}>🦟</div>
  );
}

function money(v, lang) {
  return v == null ? "" : v.toLocaleString(lang === "el" ? "el-GR" : "en-GB", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
}

// "Investment decision" panel from the design: portfolio value, chosen amount and its share.
function DecisionFacts({ facts }) {
  const { t, lang } = useCoach();
  if (facts?.share == null) return null;
  const pct = `${Math.round(facts.share * 100)}%`;
  return (
    <div style={{ background: "#F2F2F2", borderRadius: 14, padding: "12px 14px", marginBottom: 10 }}>
      <div style={{ fontSize: 12.5, color: "#636B7E" }}>{t.portfolio}</div>
      <div style={{ fontSize: 22, fontWeight: 700, margin: "2px 0 8px" }}>{money(facts.portfolio_value, lang)}</div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5 }}>
        <span>{t.chosen}</span><b>{money(facts.amount, lang)}</b>
      </div>
      <div style={{ height: 8, borderRadius: 99, background: "#DADADA", margin: "8px 0 6px", overflow: "hidden" }}>
        <div style={{ width: `${Math.min(100, facts.share * 100)}%`, height: "100%", background: "#D4A044", borderRadius: 99 }} />
      </div>
      <div style={{ fontSize: 12, color: "#636B7E" }}>{t.ofAvailable(pct)}</div>
    </div>
  );
}

export function NudgeCard({ nudge, onClose, showFacts = false, children }) {
  const { openLesson, t } = useCoach();
  return (
    <div role="status" style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
      <Mosquito />
      <div style={{ flex: 1, background: "#F2F2F2", borderRadius: 18, padding: "12px 14px", position: "relative", color: "#0B1220" }}>
        {onClose && (
          <button onClick={onClose} aria-label={t.dismiss} style={{ position: "absolute", top: 8, right: 8, border: 0, background: "transparent", cursor: "pointer", color: "#636B7E" }}>
            <X size={15} />
          </button>
        )}
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 4, paddingRight: 18 }}>{nudge.title}</div>
        {showFacts && <DecisionFacts facts={nudge.facts} />}
        <div style={{ fontSize: 14, lineHeight: 1.45 }}>{nudge.text}</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
          {nudge.replies.map((r, i) => (
            <button key={r.lesson} onClick={() => { openLesson(r.lesson); onClose?.(); }}
              style={{
                borderRadius: 999, padding: "6px 14px", fontSize: 13, cursor: "pointer",
                border: i === 0 ? "1px solid #1A1A1A" : "1px solid #CDD3E3",
                background: i === 0 ? "#1A1A1A" : "transparent", color: i === 0 ? "#fff" : "#3A3F4B",
              }}>{r.label}</button>
          ))}
          {children}
        </div>
      </div>
    </div>
  );
}

// Shown in a trade box when Tsimp has something to say before the trade goes through.
export function PreTradeNudges({ nudges, side, onContinue, onCancel }) {
  const { t } = useCoach();
  return (
    <div style={{ border: "1px solid #E6E9F2", borderRadius: 18, padding: 12, marginTop: 10, background: "#fff" }}>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
        <span style={{ fontSize: 12, background: "#F2F2F2", borderRadius: 999, padding: "3px 10px" }}>{t.decision}</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {nudges.map((n, i) => <NudgeCard key={n.id} nudge={n} showFacts={i === 0} />)}
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <button className="ip-btn" onClick={onContinue}>{side === "sell" ? t.continueSell : t.continue}</button>
        <button className="ip-btn secondary" onClick={onCancel}>{t.cancel}</button>
      </div>
    </div>
  );
}
