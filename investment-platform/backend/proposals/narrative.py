"""
Plain-language explanation of a proposal.

template(): deterministic, always available, every number taken from the proposal.
ai_rewrite(): optional -- asks the configured LLM (LLM_PROVIDER) to make the template
friendlier, then ACCEPTS it only if
  * every number in it also appears in the template (no new or changed numbers),
  * it contains no advice / promise language and no forward-looking return claims
    (a correct number from the facts could otherwise be reused as a promise),
  * it is not too long;
otherwise the template is served and the rejection reason is stored.
"""
from __future__ import annotations

import json
import re

from app.config import settings

DISCLAIMER = ("This is an educational illustration for your practice portfolio, built from your questionnaire "
              "answers and current market data. It is not investment advice and not a recommendation to buy or "
              "sell anything with real money. Past data and model estimates do not guarantee future results.")

BANNED = [r"\byou should (buy|sell|invest)", r"\bbuy now\b", r"\bsell now\b", r"\bguarantee", r"\bwill (rise|fall|go up|go down)\b",
          r"\brisk[- ]free\b", r"\bsure (bet|thing)\b", r"\bwe recommend\b", r"\bI recommend\b", r"\bcan't lose\b",
          # forward-looking return claims: a correct number from the facts must not become a promise
          r"\b(could|would|will|may|might|can|should|expected to)\s+(return|earn|gain|make|grow|yield|double)\b",
          r"\b(return|earn|gain|profit|grow)\w*\b[^.]{0,40}\bnext (year|month|quarter)\b",
          r"\b(expected|projected|forecast) (return|profit|gain)s?\b"]
_NUM = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?")


def _pct(x: float, digits: int = 0) -> str:
    return f"{x * 100:.{digits}f}%"


def template(p: dict) -> str:
    alloc = {a["sleeve"]: a for a in p["allocation"]}
    parts = [f"Your profile: {p['profile_name']} ({p['profile']} of 7)."]
    if p["assessment"].get("reasons"):
        parts.append("Why: " + "; ".join(p["assessment"]["reasons"]) + ".")
    if p["assessment"].get("emergency_fund_first"):
        parts.append("Before investing, most people first build an emergency fund of a few months of expenses.")
    mix = ", ".join(f"{a['name']} {a['weight_pct']:.0f}%" for a in p["allocation"] if a["weight_pct"] > 0)
    parts.append(f"Illustrative mix: {mix}.")
    parts.append(f"Its expected volatility is about {_pct(p['expected_volatility'])} a year, within the "
                 f"{_pct(p['volatility_band'])} limit for your profile.")
    for adj in p["adjustments"][1:]:
        parts.append(f"Adjustment: {adj['detail']}.")
    worst = min(p["stress_tests"], key=lambda s: s["portfolio_return"])
    parts.append(f"In the hardest scenario we test ({worst['name']}), this mix would lose about "
                 f"{_pct(-worst['portfolio_return'])}, or €{-worst['on_10000_eur']:,} on €10,000.")
    if worst.get("historical"):
        parts.append(f"That scenario replays real market moves from {worst['period']}.")
    else:
        rep = next((s for s in p["stress_tests"] if s["historical"]), None)
        if rep:
            parts.append(f"Replaying the real {rep['name']} ({rep['period']}), it would have moved about {_pct(rep['portfolio_return'])}.")
    cur = p.get("current")
    if cur and not cur.get("empty"):
        if cur["positions"] == 0:
            parts.append(f"Your practice portfolio is all cash (€{cur['total_value']:,.0f}) with nothing invested yet, "
                         "so it has no market risk but also no growth beyond deposit rates.")
        else:
            parts.append(f"Your practice portfolio today: {cur['positions']} holdings, measured volatility about "
                         f"{_pct(cur['measured_volatility'])} a year.")
            for f in cur["flags"][:3]:
                parts.append(f"Note: {f['text']}.")
    for c in p.get("context", [])[:4]:
        parts.append(c["text"])
    greek = alloc.get("greek_equity", {}).get("ideas") or []
    if greek:
        parts.append("Greek shares to research (highest annual-report quality in their groups): "
                     + ", ".join(f"{i['ticker']} (quality {i['quality_score']:.0f})" for i in greek[:4]) + ".")
    return " ".join(parts)


def _call_llm(system: str, user: str) -> str:
    from app.services import llm  # selfhosted (vLLM), azure (Azure OpenAI in Foundry) or anthropic
    if llm.current() == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        r = client.messages.create(model="claude-sonnet-5", max_tokens=900, system=system,
                                   messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in r.content if b.type == "text")
    msg = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                   max_tokens=900, temperature=0.2)
    return msg.get("content") or ""


SYSTEM = ("You rewrite an investment-education explanation in warm, plain English for a beginner. Rules: keep every "
          "number exactly as written and add no new numbers; do not tell the reader to buy or sell anything; make no "
          "predictions or promises; keep it under 230 words; no headings, no lists, no disclaimer (one is added).")


def validate(candidate: str, source_text: str) -> str | None:
    """None if acceptable, else the reason it was rejected."""
    if not candidate.strip():
        return "empty"
    if len(candidate) > 2200:
        return "too long"
    for pat in BANNED:
        if re.search(pat, candidate, re.I):
            return f"advice/promise language ({pat})"
    allowed = {n.replace(",", "") for n in _NUM.findall(source_text)}
    new = sorted({n.replace(",", "") for n in _NUM.findall(candidate)} - allowed)
    if new:
        return f"numbers not in the facts: {', '.join(new[:5])}"
    return None


def ai_rewrite(template_text: str, facts: dict) -> tuple[str, str]:
    """(text, source) where source is 'ai' or 'template (ai rejected: reason)'."""
    try:
        out = _call_llm(SYSTEM, "Explanation to rewrite:\n" + template_text + "\n\nFacts (for reference only):\n"
                        + json.dumps(facts, default=str)[:6000])
    except Exception as e:  # provider down / misconfigured: never block the proposal
        return template_text, f"template (ai unavailable: {type(e).__name__})"
    reason = validate(out, template_text)
    return (out.strip(), "ai") if reason is None else (template_text, f"template (ai rejected: {reason})")
