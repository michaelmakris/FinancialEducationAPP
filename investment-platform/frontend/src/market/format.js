// Number and time formatting for the real-market pages (prices come in each instrument's
// own currency; the practice portfolio is always in EUR).

export const DASH = "—";

export function money(v, currency = "EUR", digits) {
  if (v == null || !isFinite(v)) return DASH;
  const d = digits ?? (Math.abs(v) >= 1000 ? 0 : Math.abs(v) < 1 ? 4 : 2);
  try {
    return v.toLocaleString(undefined, { style: "currency", currency: currency || "EUR", minimumFractionDigits: d, maximumFractionDigits: d });
  } catch {
    return `${v.toFixed(d)} ${currency}`;
  }
}

export const eur = (v, digits = 2) => money(v, "EUR", digits);

export function signedEur(v) {
  if (v == null || !isFinite(v)) return DASH;
  return `${v > 0 ? "+" : ""}${eur(v)}`;
}

export function pct(v, d = 1) {
  if (v == null || !isFinite(v)) return DASH;
  return `${v > 0 ? "+" : ""}${(v * 100).toFixed(d)}%`;
}

export function qtyText(q) {
  if (q == null) return DASH;
  return Number.isInteger(q) ? String(q) : q.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

// Times are shown in Athens time, the app's "today".
export function athensTime(iso) {
  return new Date(iso).toLocaleTimeString("el-GR", { timeZone: "Europe/Athens", hour: "2-digit", minute: "2-digit" });
}

export function athensDateTime(iso) {
  return new Date(iso).toLocaleString("el-GR", { timeZone: "Europe/Athens", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export const tone = (v) => (v == null || !isFinite(v) || v === 0 ? undefined : v > 0 ? "ip-pos" : "ip-neg");
