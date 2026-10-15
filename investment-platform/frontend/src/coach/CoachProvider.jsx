import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../auth/bff.js";
import { CoachContext, UI } from "./coachContext.js";

// Keeps the app's language (chosen in the sidebar), whether pop-ups are on, which nudges were already shown
// (per device, so each one appears once), the pop-up queue and the chat's requests.
const KEYS = { lang: "fea.lang", popups: "fea.coach.popups", seen: "fea.coach.seen" };  // fea.lang: the app's language
const EVENTS_MS = 5 * 60_000;

function load(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v == null ? fallback : JSON.parse(v);
  } catch {
    return fallback;
  }
}

function save(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode: not remembered */ }
}

export default function CoachProvider({ page, version, children }) {
  const [lang, setLangState] = useState(() => (load(KEYS.lang, "en") === "el" ? "el" : "en"));
  const [popupsOn, setPopupsState] = useState(() => load(KEYS.popups, true));
  const [queue, setQueue] = useState([]);
  const [chatRequest, setChatRequest] = useState(null);   // {lesson} or {question}, picked up by CoachChat
  const [chatOpen, setChatOpen] = useState(false);
  const seen = useRef(load(KEYS.seen, {}));

  const setLang = useCallback((l) => { setLangState(l); save(KEYS.lang, l); }, []);
  const setPopups = useCallback((on) => { setPopupsState(on); save(KEYS.popups, on); if (!on) setQueue([]); }, []);

  const offer = useCallback((nudges) => {
    const fresh = (nudges || []).filter((n) => n && !seen.current[n.id]);
    if (!fresh.length) return;
    const day = new Date().toISOString().slice(0, 10);
    fresh.forEach((n) => { seen.current[n.id] = day; });
    // forget entries older than ~2 months so the store stays small
    const cutoff = new Date(Date.now() - 60 * 864e5).toISOString().slice(0, 10);
    Object.keys(seen.current).forEach((k) => { if (seen.current[k] < cutoff) delete seen.current[k]; });
    save(KEYS.seen, seen.current);
    setQueue((q) => [...q, ...fresh.filter((n) => !q.some((x) => x.id === n.id))]);
  }, []);

  // daily tip + events (on start, after each trade, every 5 minutes) + first visit to each page
  useEffect(() => {
    if (!popupsOn) return undefined;
    let alive = true;
    const pull = () => api(`/v1/coach/events?lang=${lang}`).then((n) => { if (alive) offer(n); }).catch(() => {});
    api(`/v1/coach/tip?lang=${lang}`).then((n) => { if (alive) offer([n]); }).catch(() => {});
    pull();
    const id = setInterval(pull, EVENTS_MS);
    return () => { alive = false; clearInterval(id); };
  }, [popupsOn, lang, version, offer]);

  useEffect(() => {
    if (!popupsOn || !page) return undefined;
    let alive = true;
    api(`/v1/coach/learn/${page}?lang=${lang}`).then((n) => { if (alive) offer([n]); }).catch(() => {});
    return () => { alive = false; };
  }, [popupsOn, page, lang, offer]);

  const dismiss = useCallback((id) => setQueue((q) => q.filter((n) => n.id !== id)), []);

  // Before a trade: what Tsimp would say (empty = go ahead). Pop-ups off or API down = say nothing.
  const preTrade = useCallback(async (side, ticker, qty) => {
    if (!popupsOn) return [];
    try {
      return await api("/v1/coach/pre-trade", { method: "POST", body: { side, ticker, qty, lang } });
    } catch {
      return [];
    }
  }, [popupsOn, lang]);

  const openLesson = useCallback((lesson) => { setChatOpen(true); setChatRequest({ lesson, at: Date.now() }); }, []);
  const ask = useCallback((question) => { setChatOpen(true); setChatRequest({ question, at: Date.now() }); }, []);

  const value = useMemo(() => ({
    lang, setLang, popupsOn, setPopups, queue, dismiss, preTrade, openLesson, ask, chatRequest, chatOpen, setChatOpen,
    t: UI[lang] || UI.en,
  }), [lang, setLang, popupsOn, setPopups, queue, dismiss, preTrade, openLesson, ask, chatRequest, chatOpen]);

  return <CoachContext.Provider value={value}>{children}</CoachContext.Provider>;
}
