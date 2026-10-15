// Model picker for the assistant / AI wording; state lives in useModelChoice.js.

export function ModelPicker({ providers, value, onChange, compact = false }) {
  if (providers.length < 2) return null; // nothing to choose
  const current = providers.find((p) => p.id === value);
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: compact ? 12 : 13 }} title={current?.note}>
      {!compact && "Model"}
      <select className="ip-select" value={value || ""} onChange={(e) => onChange(e.target.value)}
        aria-label="AI model" style={{ fontSize: compact ? 12 : 13, padding: compact ? "2px 6px" : undefined, maxWidth: compact ? 170 : 260 }}>
        {providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
      </select>
    </label>
  );
}
