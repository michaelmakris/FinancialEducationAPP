"""
Tsimp, the mosquito coach: WHEN to say something, with the customer's real numbers.

Deterministic rules over the practice portfolio, the quote and the risk profile --
no AI involved, so a nudge is instant and always states true figures. Each nudge
carries buttons that open a lesson (services/coach_content.py) and, from there,
the chat. Nudges teach; they never tell anyone to buy or sell.

  pre_trade  before a buy/sell is placed (the page shows it and asks to continue)
  event      after something happened (first trade, big mover, down/up day, ...)
  learn      first visit to a page
  tip        one short tip per day

Ids are stable per day (e.g. "big_mover:ETE.AT:2026-10-12") so the app shows each
event nudge at most once.
"""
from __future__ import annotations

import datetime

from sqlalchemy.orm import Session

from .. import market_repo as mr
from .. import models as M
from .. import repo
from . import coach_content as C
from . import market as calc
from . import costs, practice, quotes

# thresholds (fractions)
CONCENTRATION_TRADE = 0.25    # one buy >= 25% of the portfolio
CONCENTRATION_HOLDING = 0.40  # one holding >= 40% after the buy / in the portfolio
CRYPTO_SHARE = 0.10           # crypto buy >= 10% of the portfolio (no profile yet)
CAUTIOUS_PROFILE = 3          # risk profile 1-3
CHASE_1M = 0.20               # bought after +20% in a month ...
CHASE_1D = 0.08               # ... or +8% today
LOW_CASH = 0.05               # cash left after a buy < 5% of the portfolio
LOSS_SELL = -0.10             # selling >= half a position that is down >= 10%
PANIC_DAY = -0.05             # selling on a day the instrument is down >= 5%
BIG_MOVER = 0.05              # a holding moved >= 5% today
PORTFOLIO_DAY = 0.02          # the portfolio moved >= 2% today
IDLE_CASH = 0.90              # >= 90% of the portfolio in cash
COSTLY_TRADE = 0.02           # transaction costs >= 2% of the trade

TITLE = {"el": "Τσιμπ! Μια μικρή σκέψη...", "en": "Bzz! A quick thought..."}
YES = {"el": "Ναι, εξήγησέ μου", "en": "Yes, explain"}


def _lang(lang: str | None) -> str:
    return lang if lang in C.LANGS else "en"


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _eur(x: float, lang: str) -> str:
    s = f"{x:,.2f}"
    return ("€" + s.replace(",", "X").replace(".", ",").replace("X", ".")) if lang == "el" else f"EUR {s}"


def _replies(lang: str, *lesson_ids: str) -> list[dict]:
    out = []
    for i, lid in enumerate(lesson_ids):
        label = YES[lang] if i == 0 else C.LESSONS[lid][lang]["title"]
        out.append({"lesson": lid, "label": label})
    return out


def _nudge(nid: str, kind: str, lang: str, text: str, lessons: tuple[str, ...], *, severity: str = "info",
           facts: dict | None = None, page: str | None = None) -> dict:
    return {"id": nid, "kind": kind, "severity": severity, "title": TITLE[lang], "text": text,
            "facts": facts or {}, "replies": _replies(lang, *lessons), "page": page}


def _profile(db: Session, customer_id: str) -> int | None:
    ra = db.query(M.RiskAssessment).filter(M.RiskAssessment.customer_id == customer_id) \
        .order_by(M.RiskAssessment.id.desc()).first()
    return ra.profile if ra else None


def _month_return(db: Session, inst: M.Instrument) -> float | None:
    since = datetime.date.today() - datetime.timedelta(days=45)
    ser = mr.adj_close_series(db, [inst.id], since=since).get(inst.id, [])
    return calc.period_returns(ser).get("1m") if ser else None


# ---------------------------------------------------------------- before a trade
def pre_trade(db: Session, customer_id: str, side: str, ticker: str, qty: float, lang: str | None = None) -> list[dict]:
    lang = _lang(lang)
    portfolio = repo.get_or_create_portfolio(db, customer_id)
    inst = practice.tradable_instrument(db, ticker)
    q = practice.quote_eur(db, inst)
    summ = practice.summary(db, portfolio)
    total = summ["total_value"] or 0.0
    amount = qty * q["price_eur"]
    held = next((p for p in summ["positions"] if p["ticker"] == inst.ticker), None)
    day = (q["price_eur"] / q["prev_close_eur"] - 1) if q["prev_close_eur"] else None
    out: list[dict] = []
    if total <= 0:
        return out

    if side == "buy":
        share = amount / total
        after = ((held["value"] if held else 0.0) + amount) / total
        facts = {"portfolio_value": total, "amount": amount, "share": share}
        if share >= CONCENTRATION_TRADE or after >= CONCENTRATION_HOLDING:
            text = {"el": f"Βλέπω ότι επιλέγεις να τοποθετήσεις μεγάλο μέρος των χρημάτων σου ({_pct(max(share, after))}) "
                          f"σε μία επένδυση. Θες να δούμε τι σημαίνει αυτό για το ρίσκο σου;",
                    "en": f"I see you're putting a large part of your money ({_pct(max(share, after))}) into one investment. "
                          f"Want to see what that means for your risk?"}[lang]
            out.append(_nudge("concentration", "pre_trade", lang, text, ("concentration", "diversification"),
                              severity="caution", facts=facts))
        profile = _profile(db, customer_id)
        if inst.asset_type == "crypto" and ((profile is not None and profile <= CAUTIOUS_PROFILE)
                                             or (profile is None and share >= CRYPTO_SHARE)):
            text = {"el": (f"Το προφίλ ρίσκου σου είναι {profile} από 7 (προσεκτικό) και αγοράζεις κρυπτονόμισμα. "
                           if profile is not None else f"Βάζεις {_pct(share)} του χαρτοφυλακίου σε κρυπτονόμισμα. ")
                          + "Ξέρεις πόσο έντονα μπορεί να πέσει;",
                    "en": (f"Your risk profile is {profile} of 7 (cautious) and you're buying crypto. "
                           if profile is not None else f"You're putting {_pct(share)} of your portfolio into crypto. ")
                          + "Do you know how hard it can fall?"}[lang]
            out.append(_nudge("crypto_risk", "pre_trade", lang, text, ("crypto_risk", "risk_profile"), severity="caution", facts=facts))
        month = _month_return(db, inst)
        if (month is not None and month >= CHASE_1M) or (day is not None and day >= CHASE_1D):
            moved = f"+{_pct(day)} σήμερα" if day is not None and day >= CHASE_1D else f"+{_pct(month)} τον τελευταίο μήνα"
            moved_en = f"+{_pct(day)} today" if day is not None and day >= CHASE_1D else f"+{_pct(month)} over the last month"
            text = {"el": f"Το {inst.ticker} έχει ανέβει {moved}. Αγοράζεις επειδή σου αρέσει η εταιρεία ή επειδή ανέβηκε;",
                    "en": f"{inst.ticker} is up {moved_en}. Are you buying because you like it, or because it went up?"}[lang]
            out.append(_nudge("fomo", "pre_trade", lang, text, ("fomo", "volatility"), facts=facts))
        cash_after = summ["cash"] - amount
        if 0 <= cash_after < LOW_CASH * total:
            text = {"el": f"Μετά από αυτή την αγορά θα σου μείνουν μόνο {_eur(cash_after, lang)} σε μετρητά. Τι ρόλο παίζουν τα μετρητά;",
                    "en": f"After this buy you'd have only {_eur(cash_after, lang)} left in cash. What role does cash play?"}[lang]
            out.append(_nudge("low_cash", "pre_trade", lang, text, ("cash_role", "diversification"), facts=facts))
        fee = costs.estimate(inst.market, amount, practice.cost_profile(portfolio))
        if fee["total"] > 0 and fee["pct"] >= COSTLY_TRADE:
            text = {"el": f"Τα κόστη αυτής της αγοράς είναι περίπου {_eur(fee['total'], lang)}, δηλαδή {_pct(fee['pct'])} του ποσού. "
                          f"Σε μικρές αγορές η ελάχιστη προμήθεια βαραίνει πολύ.",
                    "en": f"This buy costs about {_eur(fee['total'], lang)} in fees, {_pct(fee['pct'])} of the amount. "
                          f"On small trades the minimum commission weighs a lot."}[lang]
            out.append(_nudge("costly_trade", "pre_trade", lang, text, ("transaction_costs", "compounding"), facts=facts))
        if q["currency"] == "USD" and not any(p.get("currency") == "USD" for p in summ["positions"]):
            text = {"el": "Η πρώτη σου αμερικανική μετοχή! Η τιμή της είναι σε δολάρια, οπότε η αξία της σε ευρώ αλλάζει και με την ισοτιμία.",
                    "en": "Your first US share! It's priced in dollars, so its value in euros also moves with the exchange rate."}[lang]
            out.append(_nudge("currency_risk", "pre_trade", lang, text, ("currency_risk",), facts=facts))
    else:
        if held and held["qty"] > 0:
            part = min(qty / held["qty"], 1.0)
            if held["unrealized_pnl_pct"] <= LOSS_SELL and part >= 0.5:
                text = {"el": f"Πουλάς {_pct(part)} της θέσης ενώ είναι {_pct(held['unrealized_pnl_pct'])} κάτω από την τιμή αγοράς. "
                              f"Η ζημιά θα γίνει πραγματική. Θες να το σκεφτούμε μαζί;",
                        "en": f"You're selling {_pct(part)} of the position while it's {_pct(held['unrealized_pnl_pct'])} below what you paid. "
                              f"The loss becomes real. Want to think it through?"}[lang]
                out.append(_nudge("loss_selling", "pre_trade", lang, text, ("loss_selling", "realised_unrealised"),
                                  severity="caution", facts={"pnl_pct": held["unrealized_pnl_pct"], "share_sold": part}))
            if day is not None and day <= PANIC_DAY:
                text = {"el": f"Το {inst.ticker} είναι {_pct(day)} σήμερα. Πουλάς λόγω της σημερινής πτώσης;",
                        "en": f"{inst.ticker} is {_pct(day)} today. Are you selling because of today's fall?"}[lang]
                out.append(_nudge("panic_sell", "pre_trade", lang, text, ("market_moves", "loss_selling"), facts={"day": day}))
    return out


# ---------------------------------------------------------------- after events
def events(db: Session, customer_id: str, lang: str | None = None) -> list[dict]:
    lang = _lang(lang)
    portfolio = repo.get_or_create_portfolio(db, customer_id)
    summ = practice.summary(db, portfolio)
    today = quotes.athens_midnight_utc().astimezone(quotes.ATHENS).date().isoformat()
    total = summ["total_value"] or 0.0
    out: list[dict] = []
    n_tx = len(portfolio.transactions)

    if n_tx == 1:
        t = portfolio.transactions[0]
        text = {"el": f"Η πρώτη σου συναλλαγή: {t.qty:g} {t.ticker}! Από εδώ και πέρα θα βλέπεις την αξία της να αλλάζει. "
                      "Ξέρεις τη διαφορά ανάμεσα σε πραγματοποιημένο και μη πραγματοποιημένο κέρδος;",
                "en": f"Your first trade: {t.qty:g} {t.ticker}! From now on you'll see its value change. "
                      "Do you know the difference between a realised and an unrealised gain?"}[lang]
        out.append(_nudge("first_trade", "event", lang, text, ("realised_unrealised", "market_moves")))
    for p in summ["positions"]:
        d = p.get("day_change_pct")
        if d is not None and abs(d) >= BIG_MOVER:
            text = {"el": f"Το {p['ticker']} κινείται {'+' if d > 0 else ''}{_pct(d)} σήμερα. Τέτοιες μέρες συμβαίνουν· τι σημαίνουν για σένα;",
                    "en": f"{p['ticker']} is moving {'+' if d > 0 else ''}{_pct(d)} today. Days like this happen; what do they mean for you?"}[lang]
            out.append(_nudge(f"big_mover:{p['ticker']}:{today}", "event", lang, text, ("market_moves", "volatility"),
                              facts={"day": d}))
    if summ["positions"]:
        dp = summ["day_change_pct"]
        if dp <= -PORTFOLIO_DAY:
            text = {"el": f"Το χαρτοφυλάκιό σου είναι {_pct(dp)} σήμερα ({_eur(summ['day_change'], lang)}). Πώς νιώθεις; Ας δούμε τι είναι φυσιολογικό.",
                    "en": f"Your portfolio is {_pct(dp)} today ({_eur(summ['day_change'], lang)}). How does that feel? Let's look at what's normal."}[lang]
            out.append(_nudge(f"day_down:{today}", "event", lang, text, ("market_moves", "drawdown"), severity="caution"))
        elif dp >= PORTFOLIO_DAY:
            text = {"el": f"Ωραία μέρα: +{_pct(dp)} ({_eur(summ['day_change'], lang)}). Ήταν τύχη ή στρατηγική;",
                    "en": f"Nice day: +{_pct(dp)} ({_eur(summ['day_change'], lang)}). Luck or strategy?"}[lang]
            out.append(_nudge(f"day_up:{today}", "event", lang, text, ("luck_vs_skill", "time_horizon")))
        top = max(summ["positions"], key=lambda p: p["value"])
        if total > 0 and top["value"] / total >= CONCENTRATION_HOLDING:
            text = {"el": f"Το {top['ticker']} είναι το {_pct(top['value'] / total)} του χαρτοφυλακίου σου. Αν έπεφτε 30%, θα έχανες περίπου {_pct(0.3 * top['value'] / total)} συνολικά.",
                    "en": f"{top['ticker']} is {_pct(top['value'] / total)} of your portfolio. If it fell 30%, you'd lose about {_pct(0.3 * top['value'] / total)} overall."}[lang]
            out.append(_nudge(f"concentrated:{top['ticker']}:{today}", "event", lang, text, ("concentration", "diversification"),
                              severity="caution"))
    if total > 0 and summ["cash"] / total >= IDLE_CASH:
        text = {"el": f"Έχεις {_eur(summ['cash'], lang)} σε μετρητά. Θες να δεις ένα εκπαιδευτικό πλάνο για το πώς θα μπορούσαν να μοιραστούν;",
                "en": f"You have {_eur(summ['cash'], lang)} in cash. Want to see a learning plan for how it could be spread?"}[lang]
        out.append(_nudge(f"idle_cash:{today}", "event", lang, text, ("cash_role", "diversification"), page="plan"))
    if _profile(db, customer_id) is None and n_tx >= 2:
        text = {"el": "Δεν έχεις βρει ακόμη το προφίλ ρίσκου σου. Είναι 8 γρήγορες ερωτήσεις στο «My plan».",
                "en": "You haven't found your risk profile yet. It's 8 quick questions in 'My plan'."}[lang]
        out.append(_nudge("no_profile", "event", lang, text, ("risk_profile",), page="plan"))
    return out


# ---------------------------------------------------------------- page notes, daily tip
def page_note(page: str, lang: str | None = None) -> dict | None:
    lang = _lang(lang)
    note = C.PAGE_NOTES.get(page)
    if note is None:
        return None
    return _nudge(f"learn:{page}", "learn", lang, note[lang], (note["lesson"],))


def daily_tip(lang: str | None = None, day: datetime.date | None = None) -> dict:
    lang = _lang(lang)
    day = day or datetime.datetime.now(quotes.ATHENS).date()
    lid, el, en = C.DAILY_TIPS[day.toordinal() % len(C.DAILY_TIPS)]
    n = _nudge(f"tip:{day.isoformat()}", "tip", lang, el if lang == "el" else en, (lid,))
    n["title"] = {"el": "Η σκέψη της ημέρας", "en": "Today's thought"}[lang]
    n["replies"][0]["label"] = {"el": "Πες μου περισσότερα", "en": "Tell me more"}[lang]
    return n
