import { useCoach } from "./coachContext.js";

// The app's language (sidebar). Tsimp's pop-ups, lessons and chat answers follow it.
const LANGS = [["en", "English"], ["el", "Ελληνικά"]];

export default function LanguagePicker() {
  const { lang, setLang } = useCoach();
  return (
    <label style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, fontSize: 12.5 }}>
      <span>{lang === "el" ? "Γλώσσα" : "Language"}</span>
      <select className="ip-select" value={lang} onChange={(e) => setLang(e.target.value)} aria-label="Language"
        style={{ fontSize: 12.5, padding: "3px 6px", maxWidth: 130 }}>
        {LANGS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
      </select>
    </label>
  );
}
