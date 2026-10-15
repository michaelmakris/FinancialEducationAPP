import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Send, X } from "lucide-react";
import { api } from "../auth/bff.js";
import { ModelPicker } from "../llm/ModelPicker.jsx";
import { useModelChoice } from "../llm/useModelChoice.js";
import { useCoach } from "./coachContext.js";
import { Mosquito, PreTradeNudges } from "./NudgeCard.jsx";

// Tsimp's chat: the app's AI assistant with the mosquito's voice. Lessons opened from a
// pop-up appear instantly (no AI call); free questions go to /chat with the chosen
// app language (sidebar). The assistant can still look up prices, explain the portfolio and trade.
const pill = (dark) => ({
  borderRadius: 999, padding: "5px 12px", fontSize: 12.5, cursor: "pointer",
  border: dark ? "1px solid #1A1A1A" : "1px solid #CDD3E3", background: dark ? "#1A1A1A" : "transparent", color: dark ? "#fff" : "#3A3F4B",
});

export default function CoachChat({ practice, goTo, setCompareList }) {
  const { lang, popupsOn, setPopups, chatRequest, openLesson, preTrade, chatOpen: open, setChatOpen: setOpen, t } = useCoach();
  const model = useModelChoice();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const bottomRef = useRef(null);
  const handled = useRef(null);

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending, open]);

  const applyAction = useCallback(async (action) => {
    if (action.type === "navigate") {
      if (action.tickers && action.tickers.length >= 2) setCompareList(action.tickers.slice(0, 4).map((x) => x.toUpperCase()));
      goTo(action.page === "analyst" ? "home" : action.page, action.ticker);
      return null;
    }
    if (action.type === "trade") {
      // same check as the Buy/Sell buttons: if Tsimp has something to say, ask before trading
      const nudges = await preTrade(action.side, action.ticker, action.qty);
      if (nudges.length) {
        setMessages((m) => [...m, { role: "pending", trade: action, nudges, id: Date.now() }]);
        return null;
      }
      try {
        await practice.trade(action.side, action.ticker, action.qty);
        return null;
      } catch (e) {
        return `${action.side} ${action.qty} ${action.ticker}: ${e.message}`;
      }
    }
    return null;
  }, [goTo, practice, setCompareList, preTrade]);

  // the customer answered a pre-trade card inside the chat
  const settle = useCallback(async (msg, go) => {
    let note = t.cancel;
    if (go) {
      try {
        await practice.trade(msg.trade.side, msg.trade.ticker, msg.trade.qty);
        note = `✓ ${msg.trade.side} ${msg.trade.qty} ${msg.trade.ticker}`;
      } catch (e) {
        note = e.message;
      }
    }
    setMessages((m) => m.map((x) => (x.id === msg.id ? { role: "assistant", content: note } : x)));
  }, [practice, t.cancel]);

  const send = useCallback(async (text) => {
    const msg = (text ?? input).trim();
    if (!msg || sending) return;
    const history = messages.filter((m) => m.role === "user" || m.role === "assistant").map(({ role, content }) => ({ role, content }));
    setInput("");
    setMessages((m) => [...m, { role: "user", content: msg }]);
    setSending(true);
    try {
      const data = await api("/chat", { method: "POST", body: { message: msg, history, provider: model.value, lang } });
      const lessonOnly = data.lesson && data.reply === data.lesson.text;   // a concept question: show it as a lesson
      if (!lessonOnly) setMessages((m) => [...m, { role: "assistant", content: data.reply || "…" }]);
      if (data.lesson) setMessages((m) => [...m, { role: "lesson", content: data.lesson.text, lesson: data.lesson }]);
      const notes = [];
      for (const a of data.actions || []) {
        const note = await applyAction(a);
        if (note) notes.push(note);
      }
      if (notes.length) setMessages((m) => [...m, { role: "assistant", content: notes.join("\n\n") }]);
    } catch (e) {
      // daily allowance used up (429) or question too long (422): the server's message says why
      const why = e.status === 429 || e.status === 422 ? e.message : t.error;
      setMessages((m) => [...m, { role: "assistant", content: why }]);
    } finally {
      setSending(false);
    }
  }, [input, sending, messages, model.value, lang, applyAction, t.error]);

  // a pop-up button asked for a lesson or a question
  useEffect(() => {
    if (!chatRequest || handled.current === chatRequest.at) return;
    handled.current = chatRequest.at;
    if (chatRequest.question) {
      Promise.resolve().then(() => send(chatRequest.question));
      return;
    }
    api(`/v1/coach/lessons/${chatRequest.lesson}?lang=${lang}`)
      .then((l) => setMessages((m) => [...m, { role: "lesson", content: l.text, lesson: l }]))
      .catch(() => {});
  }, [chatRequest, lang, send]);

  if (!open) {
    return (
      <button className="ip-coach-fab" onClick={() => setOpen(true)} title={t.name} aria-label={t.name}
        style={{ position: "fixed", right: 20, bottom: 20, zIndex: 1000, width: 58, height: 58, borderRadius: "50%",
          border: "1px solid #E6E9F2", background: "#fff", boxShadow: "0 6px 20px rgba(0,0,0,0.2)", cursor: "pointer", fontSize: 30 }}>
        🦟
      </button>
    );
  }

  const shown = messages.length ? messages : [{ role: "assistant", content: t.hello }];
  return (
    <div className="ip-coach-chat" style={{ position: "fixed", right: 16, bottom: 16, zIndex: 1000, width: 390, maxWidth: "calc(100vw - 32px)",
      background: "#fff", border: "1px solid #E6E9F2", borderRadius: 20, boxShadow: "0 12px 40px rgba(0,0,0,0.25)",
      display: "flex", flexDirection: "column", overflow: "hidden", color: "#0B1220" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderBottom: "1px solid #E6E9F2" }}>
        <Mosquito size={36} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 14.5 }}>{t.name}</div>
          <div style={{ fontSize: 11.5, color: "#636B7E" }}>{t.role}</div>
        </div>
        <button onClick={() => setOpen(false)} aria-label={t.dismiss} style={{ border: 0, background: "transparent", cursor: "pointer", padding: 4 }}><X size={16} /></button>
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, padding: "6px 12px", borderBottom: "1px solid #F0F1F5", fontSize: 12 }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
          <input type="checkbox" checked={popupsOn} onChange={(e) => setPopups(e.target.checked)} /> {t.popups}
        </label>
        <ModelPicker providers={model.providers} value={model.value} onChange={model.change} compact />
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10, maxHeight: 420, minHeight: 160, overflowY: "auto", padding: 12 }}>
        {shown.map((m, i) => m.role === "pending" ? (
          <PreTradeNudges key={m.id} nudges={m.nudges} side={m.trade.side}
            onContinue={() => settle(m, true)} onCancel={() => settle(m, false)} />
        ) : (
          <div key={i} style={{ display: "flex", justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
            <div style={{ maxWidth: "86%", borderRadius: 16, padding: "9px 12px", fontSize: 13.5, lineHeight: 1.5, whiteSpace: "pre-wrap",
              background: m.role === "user" ? "#1A1A1A" : "#F2F2F2", color: m.role === "user" ? "#fff" : "#0B1220" }}>
              {m.lesson && <div style={{ fontWeight: 700, marginBottom: 4 }}>{m.lesson.title}</div>}
              {m.content}
              {m.lesson && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                  <button style={pill(true)} onClick={() => send(m.lesson.ask)} disabled={sending}>{t.askMore}: {m.lesson.ask}</button>
                  {m.lesson.next.map((n) => <button key={n.id} style={pill(false)} onClick={() => openLesson(n.id)}>{n.title}</button>)}
                </div>
              )}
            </div>
          </div>
        ))}
        {sending && <div style={{ display: "flex", gap: 6, alignItems: "center", color: "#636B7E", fontSize: 13 }}><Loader2 size={14} className="ip-spin" /> {t.thinking}…</div>}
        <div ref={bottomRef} />
      </div>

      <div style={{ display: "flex", gap: 8, padding: 10, borderTop: "1px solid #E6E9F2" }}>
        <input className="ip-input" style={{ flex: 1 }} placeholder={t.placeholder} value={input} disabled={sending}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
        <button className="ip-btn" onClick={() => send()} disabled={sending || !input.trim()} aria-label="Send"><Send size={14} /></button>
      </div>
    </div>
  );
}
