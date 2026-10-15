import { useCoach } from "./coachContext.js";
import { NudgeCard } from "./NudgeCard.jsx";

// Pop-up messages: one at a time, bottom-left (the chat button is bottom-right),
// with a count of what is waiting. Each one can open a lesson or a page.
export default function CoachPopups({ goTo }) {
  const { queue, dismiss, popupsOn, t } = useCoach();
  if (!popupsOn || queue.length === 0) return null;
  const n = queue[0];
  return (
    <div className="ip-coach-popup" style={{ position: "fixed", left: 16, bottom: 16, zIndex: 999, width: 360, maxWidth: "calc(100vw - 32px)",
      filter: "drop-shadow(0 8px 24px rgba(0,0,0,0.18))", animation: "ip-pop-in 220ms ease-out" }}>
      <style>{"@keyframes ip-pop-in{from{transform:translateY(12px);opacity:0}to{transform:none;opacity:1}}"}</style>
      <div style={{ background: "#fff", borderRadius: 20, padding: 10 }}>
        <NudgeCard nudge={n} onClose={() => dismiss(n.id)} showFacts={n.kind === "pre_trade"}>
          {n.page && (
            <button onClick={() => { goTo(n.page); dismiss(n.id); }}
              style={{ borderRadius: 999, padding: "6px 14px", fontSize: 13, cursor: "pointer", border: "1px solid #CDD3E3", background: "transparent" }}>
              {t.openPage} {n.page === "plan" ? "My plan" : n.page}
            </button>
          )}
        </NudgeCard>
        {queue.length > 1 && <div style={{ fontSize: 11.5, color: "#636B7E", textAlign: "right", marginTop: 4 }}>+{queue.length - 1} {t.more}</div>}
      </div>
    </div>
  );
}
