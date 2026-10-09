"""
Risk questionnaire (version 1).

Modelled on the structure of a MiFID suitability assessment -- capacity for loss,
willingness to take risk, knowledge & experience, horizon -- but used here only to
shape an educational proposal for a practice portfolio.

Profile (1 = very conservative ... 7 = very adventurous) = min(capacity, tolerance),
then capped by the horizon. Knowledge does not change the profile but decides
whether complex/very volatile assets (crypto) may appear at all.
"""
from __future__ import annotations

VERSION = 1

# id -> question, options [(value, label, points)], dimension
QUESTIONS = [
    {"id": "horizon", "dimension": "horizon", "text": "When might you need this money?",
     "options": [("lt1", "Within 1 year", 1), ("1_3", "In 1-3 years", 2), ("3_5", "In 3-5 years", 3),
                 ("5_10", "In 5-10 years", 4), ("gt10", "In more than 10 years", 5)]},
    {"id": "cushion", "dimension": "capacity", "text": "Apart from this money, how many months of expenses do you have saved for emergencies?",
     "options": [("none", "None", 0), ("lt3", "Less than 3 months", 1), ("3_6", "3-6 months", 2), ("gt6", "More than 6 months", 3)]},
    {"id": "share", "dimension": "capacity", "text": "What share of your total savings is this?",
     "options": [("gt75", "More than 75%", 0), ("50_75", "50-75%", 1), ("25_50", "25-50%", 2), ("lt25", "Less than 25%", 3)]},
    {"id": "income", "dimension": "capacity", "text": "How stable is your income over the next few years?",
     "options": [("unstable", "Uncertain or none", 0), ("variable", "Variable", 1), ("stable", "Stable", 2), ("very_stable", "Very stable with savings each month", 3)]},
    {"id": "drop", "dimension": "tolerance", "text": "Your investments fall 20% in three months. What do you do?",
     "options": [("sell_all", "Sell everything to stop further losses", 0), ("sell_some", "Sell some", 1),
                 ("hold", "Wait and hold", 2), ("buy_more", "Invest more while prices are low", 3)]},
    {"id": "goal", "dimension": "tolerance", "text": "Which matters most to you?",
     "options": [("preserve", "Not losing money, even if it grows little", 0), ("income", "Steady modest returns", 1),
                 ("growth", "Growth over time, accepting ups and downs", 2), ("max_growth", "Highest growth, accepting large swings", 3)]},
    {"id": "range", "dimension": "tolerance", "text": "Over one year, which range of outcomes would you accept for €10,000?",
     "options": [("narrow", "€9,800 to €10,400", 0), ("moderate", "€9,200 to €11,000", 1),
                 ("wide", "€8,500 to €11,800", 2), ("very_wide", "€7,000 to €13,500", 3)]},
    {"id": "knowledge", "dimension": "knowledge", "text": "Which of these have you invested in before (or understand well)?",
     "options": [("none", "None yet", 0), ("funds", "Deposits, bond or equity funds", 1),
                 ("stocks", "Individual shares or ETFs", 2), ("complex", "Shares and crypto or other volatile assets", 3)]},
]
_BY_ID = {q["id"]: q for q in QUESTIONS}

PROFILE_NAMES = {1: "Very conservative", 2: "Conservative", 3: "Moderately conservative", 4: "Balanced",
                 5: "Moderately adventurous", 6: "Adventurous", 7: "Very adventurous"}
HORIZON_CAP = {"lt1": 1, "1_3": 3, "3_5": 5, "5_10": 7, "gt10": 7}
HORIZON_YEARS = {"lt1": 1, "1_3": 2, "3_5": 4, "5_10": 7, "gt10": 12}


def public() -> dict:
    """Questions for the client (no scoring)."""
    return {"version": VERSION, "questions": [
        {"id": q["id"], "text": q["text"], "options": [{"value": v, "label": label} for v, label, _ in q["options"]]}
        for q in QUESTIONS]}


class InvalidAnswers(ValueError):
    pass


def _points(qid: str, value: str) -> int:
    for v, _, pts in _BY_ID[qid]["options"]:
        if v == value:
            return pts
    raise InvalidAnswers(f"'{value}' is not an option for '{qid}'")


def _scale(points: int, max_points: int) -> int:
    """0..max -> 1..7"""
    return 1 + round(6 * points / max_points)


def assess(answers: dict[str, str]) -> dict:
    missing = [q["id"] for q in QUESTIONS if q["id"] not in answers]
    if missing:
        raise InvalidAnswers(f"missing answers: {', '.join(missing)}")
    unknown = set(answers) - set(_BY_ID)
    if unknown:
        raise InvalidAnswers(f"unknown questions: {', '.join(sorted(unknown))}")
    pts = {q: _points(q, answers[q]) for q in _BY_ID}
    capacity = _scale(pts["cushion"] + pts["share"] + pts["income"], 9)
    tolerance = _scale(pts["drop"] + pts["goal"] + pts["range"], 9)
    horizon_cap = HORIZON_CAP[answers["horizon"]]
    profile = max(1, min(capacity, tolerance, horizon_cap))
    knowledge = pts["knowledge"]
    reasons = []
    if capacity < tolerance:
        reasons.append("your capacity to absorb losses is lower than your willingness, so capacity sets the level")
    elif tolerance < capacity:
        reasons.append("your willingness to accept swings is lower than your capacity, so willingness sets the level")
    if horizon_cap < min(capacity, tolerance):
        reasons.append("a short horizon limits how much short-term risk makes sense")
    if pts["cushion"] == 0:
        reasons.append("without an emergency fund, building one usually comes before investing")
    return {
        "questionnaire_version": VERSION, "profile": profile, "profile_name": PROFILE_NAMES[profile],
        "capacity": capacity, "tolerance": tolerance, "horizon_cap": horizon_cap,
        "horizon_years": HORIZON_YEARS[answers["horizon"]], "knowledge": knowledge,
        "crypto_allowed": knowledge >= 3 and profile >= 5,
        "emergency_fund_first": pts["cushion"] == 0, "reasons": reasons,
    }
