"""
Deterministic chat answers: the common questions Tsimp answers itself, instantly, from
real data and fixed wording -- no AI call, no tokens. Only what this module cannot
recognise goes to the AI (routers/chat.py).

Recognised, in English and Greek (accents optional), in this order:
  trade      "buy 5 ETE.AT", "πούλησε 2 alpha"           -> a trade action (the app checks it first)
  navigate   "open my portfolio", "άνοιξε τις αγορές"     -> a page action
  compare    "compare ETE vs ALPHA", "σύγκρινε ..."        -> 1-year return, volatility, worst fall
  portfolio  "how is my portfolio", "πώς πάει το χαρτοφυλάκιό μου"
  risk       "how risky is BTC", "ρίσκο της Εθνικής"      -> measured + model risk
  price      "price of AAPL", "τιμή ETE", or just a ticker
  concept    "what is an ETF", "τι είναι η διαφοροποίηση" -> the lesson from coach_content
  greeting   "hi", "γεια", "help", "τι μπορείς να κάνεις"
"""
from __future__ import annotations

import datetime
import re
import unicodedata

from sqlalchemy.orm import Session

from .. import market_repo as mr
from .. import models as M
from .. import repo
from . import coach_content as C
from . import market as calc
from . import practice

# ---------------------------------------------------------------- text helpers
def norm(text: str) -> str:
    """Lower-case, no Greek accents, final sigma -> sigma: 'Τι είναι;' -> 'τι ειναι;'."""
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return t.replace("ς", "σ")


def _has(text: str, *words: str) -> bool:
    return any(re.search(rf"(?<![\w]){re.escape(norm(w))}", text) for w in words)


def _pct(x, signed: bool = True) -> str:
    if x is None:
        return "–"
    return f"{'+' if signed and x > 0 else ''}{x * 100:.1f}%"


def _eur(x: float, lang: str) -> str:
    s = f"{x:,.2f}"
    return f"€{s.replace(',', 'X').replace('.', ',').replace('X', '.')}" if lang == "el" else f"EUR {s}"


def _num(x: float, lang: str) -> str:
    s = f"{x:,.2f}" if abs(x) < 1000 else f"{x:,.0f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") if lang == "el" else s


# ---------------------------------------------------------------- instruments named in a message
ALIASES = {  # Greek / everyday names -> ticker
    "εθνικη": "ETE.AT", "εθνικησ": "ETE.AT", "πειραιωσ": "TPEIR.AT", "αλφα": "ALPHA.AT",
    "γιουρομπανκ": "EUROB.AT", "οτε": "HTO.AT", "δεη": "PPC.AT", "μυτιληναιοσ": "MTLN.AT", "τζαμπο": "BELA.AT",
    "jumbo": "BELA.AT", "μοτορ οιλ": "MOH.AT", "ελλακτωρ": "ELLAKTOR.AT", "τιτανασ": "TITC.AT", "αεγεαν": "AEGN.AT",
    "aegean": "AEGN.AT", "οπαπ": "ALWN.AT", "opap": "ALWN.AT", "κυπρου": "BOCHGR.AT", "μπιτκοιν": "BTC-EUR",
    "bitcoin": "BTC-EUR", "ethereum": "ETH-EUR", "εθεριουμ": "ETH-EUR", "solana": "SOL-EUR", "ripple": "XRP-EUR",
    "dogecoin": "DOGE-EUR", "cardano": "ADA-EUR", "google": "GOOGL.US", "facebook": "META.US",
}
NAME_STOP = {"national", "bank", "group", "hellenic", "holdings", "holding", "general", "international", "public",
             "athens", "ishares", "vanguard", "amundi", "xtrackers", "invesco", "test", "core", "real", "trade",
             "technical", "thessaloniki", "piraeus", "united", "texas", "bank of", "alpha", "the"}


def _index(db: Session) -> list[tuple[str, str]]:
    """(lookup key, ticker) pairs, longest keys first so 'motor oil' wins over 'oil'. Plain strings,
    so the cached list never holds database objects from an earlier request."""
    def build():
        pairs = []
        tickers = set()
        for i in mr.list_instruments(db):
            tickers.add(i.ticker)
            pairs.append((norm(i.ticker), i.ticker))
            base = re.split(r"[.\-]", i.ticker)[0]
            if base and not i.ticker.startswith("^"):  # 1-3 letter ones only match in capitals
                pairs.append((norm(base), i.ticker))
            name = norm(i.name)
            pairs.append((name, i.ticker))
            first = name.split()[0] if name.split() else ""
            if len(first) >= 5 and first not in NAME_STOP:
                pairs.append((first, i.ticker))
        pairs += [(alias, t) for alias, t in ALIASES.items() if t in tickers]
        return sorted(pairs, key=lambda p: -len(p[0]))
    return mr.cached(("coach-index",), build)


def find_instruments(db: Session, message: str) -> list[M.Instrument]:
    """Instruments named in the message, in the order they appear. Bare short tickers (1-3
    letters, e.g. 'V', 'MA', 'T') only count when written in capitals, so words don't match."""
    text = norm(message)
    caps = set(re.findall(r"\b[A-Z][A-Z0-9.\-]{0,11}\b", message))
    hits: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for key, ticker in _index(db):
        for m in re.finditer(rf"(?<![\w.\-^]){re.escape(key)}(?![\w])", text):
            a, b = m.span()
            if any(a < y and x < b for x, y in taken):
                continue
            original = message[a:b] if len(message) == len(text) else key.upper()
            if len(key) <= 3 and "." not in key and "-" not in key and original.upper() not in caps:
                continue
            taken.append((a, b))
            hits.append((a, ticker))
    ordered = list(dict.fromkeys(t for _, t in sorted(hits, key=lambda h: h[0])))
    found = mr.get_instruments(db, ordered)
    return [found[t.upper()] for t in ordered if t.upper() in found]


# ---------------------------------------------------------------- intents
PAGES = {
    "discover": ("markets", "market", "stocks", "αγορεσ", "αγορα", "μετοχεσ"),
    "portfolio": ("portfolio", "holdings", "χαρτοφυλακιο", "θεσεισ"),
    "plan": ("my plan", "plan", "proposal", "πλανο", "προταση", "προφιλ"),
    "learn": ("learn", "lessons", "μαθηση", "μαθηματα"),
    "compare": ("compare page", "σελιδα συγκρισησ"),
    "simulator": ("simulator", "προσομοιωση", "προσομοιωτη"),
    "home": ("home", "αρχικη"),
}
OPEN_WORDS = ("open", "go to", "show me the", "take me", "navigate", "ανοιξε", "πηγαινε", "παμε", "δειξε μου τη", "δειξε μου το")
CONCEPTS = {  # words that point to a lesson
    "diversification": ("diversif", "διαφοροποιη", "διασπορα"),
    "concentration": ("concentration", "eggs in one basket", "συγκεντρωσ", "ενα καλαθι"),
    "volatility": ("volatility", "μεταβλητοτητα", "διακυμανσ"),
    "crypto_risk": ("crypto", "κρυπτο"),
    "fomo": ("fomo", "chasing", "κυνηγ"),
    "loss_selling": ("sell at a loss", "selling at a loss", "πουλαω με ζημια", "πωληση με ζημια"),
    "market_moves": ("why did the market", "daily moves", "γιατι επεσε", "γιατι ανεβηκε"),
    "cash_role": ("cash", "μετρητα"),
    "currency_risk": ("currency", "exchange rate", "dollar", "νομισμα", "ισοτιμια", "δολαριο"),
    "risk_profile": ("risk profile", "προφιλ ρισκου", "προφιλ κινδυνου"),
    "realised_unrealised": ("realised", "realized", "unrealised", "unrealized", "πραγματοποιημεν"),
    "etf": ("etf",),
    "index": ("index", "indices", "δεικτη", "δεικτεσ"),
    "pe_ratio": ("p/e", "pe ratio", "price to earnings", "τιμη προσ κερδη"),
    "luck_vs_skill": ("luck", "τυχη"),
    "compounding": ("compound", "ανατοκισ"),
    "delayed_prices": ("delayed", "real time", "real-time", "καθυστερ"),
    "time_horizon": ("time horizon", "horizon", "οριζοντα"),
    "drawdown": ("drawdown", "worst fall", "χειροτερη πτωση"),
    "transaction_costs": ("transaction cost", "trading cost", "commission", "broker fee", "fees", "κοστη συναλλαγ",
                          "κοστοσ συναλλαγ", "προμηθεια", "χρεωσεισ"),
    "fixed_vs_variable": ("fixed rate", "variable rate", "fixed or variable", "σταθερο επιτοκιο",
                          "κυμαινομενο", "σταθερο η κυμαινομενο"),
}
QUESTION_WORDS = ("what is", "what are", "what's", "explain", "meaning", "define", "why", "how does",
                  "τι ειναι", "τι σημαινει", "εξηγησε", "εξηγησ", "γιατι", "πωσ λειτουργει", "τι ειν")


def _reply(text: str, *, actions=None, lesson=None, intent: str) -> dict:
    return {"reply": text, "actions": actions or [], "lesson": lesson, "source": "rules", "intent": intent}


def _trade(db: Session, message: str, text: str, lang: str):
    m = re.match(r"^\s*(buy|sell|αγορασε|αγοραζω|αγορα|παρε|πουλησε|πουλαω|πωληση)\s+(.*)$", text)
    if not m:
        return None
    side = "buy" if m.group(1) in ("buy", "αγορασε", "αγοραζω", "αγορα", "παρε") else "sell"
    qty_m = re.search(r"(\d+(?:[.,]\d+)?)", m.group(2))
    insts = find_instruments(db, message)
    if not insts:
        return _reply({"el": "Ποιο προϊόν εννοείς; Γράψε π.χ. «αγόρασε 5 ETE.AT».",
                       "en": "Which instrument? Try e.g. \"buy 5 ETE.AT\"."}[lang], intent="trade")
    if not qty_m:
        return _reply({"el": f"Πόσα {insts[0].ticker}; Γράψε π.χ. «αγόρασε 5 {insts[0].ticker}».",
                       "en": f"How many {insts[0].ticker}? Try e.g. \"buy 5 {insts[0].ticker}\"."}[lang], intent="trade")
    qty = float(qty_m.group(1).replace(",", "."))
    inst = insts[0]
    if inst.market not in practice.TRADABLE_MARKETS:
        return _reply({"el": f"Το {inst.ticker} είναι δείκτης· δεν αγοράζεται απευθείας. Ένα ETF μπορεί να τον ακολουθεί.",
                       "en": f"{inst.ticker} is an index; it can't be bought directly. An ETF can track it."}[lang], intent="trade")
    q = practice.quote_eur(db, inst)
    amount = qty * q["price_eur"]
    verb = {("buy", "el"): "Αγορά", ("sell", "el"): "Πώληση", ("buy", "en"): "Buying", ("sell", "en"): "Selling"}[(side, lang)]
    text_out = {"el": f"{verb} {qty:g} {inst.ticker} ({inst.name}) στα {_num(q['price_local'], lang)} {q['currency']}, περίπου {_eur(amount, lang)}.",
                "en": f"{verb} {qty:g} {inst.ticker} ({inst.name}) at {_num(q['price_local'], lang)} {q['currency']}, about {_eur(amount, lang)}."}[lang]
    return _reply(text_out, actions=[{"type": "trade", "side": side, "ticker": inst.ticker, "qty": qty}], intent="trade")


def _navigate(text: str, lang: str):
    if not _has(text, *OPEN_WORDS):
        return None
    for page, words in PAGES.items():
        if _has(text, *words):
            names = {"discover": ("Markets", "Αγορές"), "portfolio": ("Portfolio", "Χαρτοφυλάκιο"), "plan": ("My plan", "My plan"),
                     "learn": ("Learn", "Μάθηση"), "compare": ("Compare", "Σύγκριση"), "simulator": ("Simulator", "Simulator"),
                     "home": ("Home", "Αρχική")}[page]
            return _reply({"el": f"Πάμε στη σελίδα «{names[1]}».", "en": f"Opening {names[0]}."}[lang],
                          actions=[{"type": "navigate", "page": page}], intent="navigate")
    return None


def _stats(db: Session, inst: M.Instrument) -> dict:
    since = datetime.date.today() - datetime.timedelta(days=400)
    ser = mr.adj_close_series(db, [inst.id], since=since).get(inst.id, [])
    rets = calc.period_returns(ser) if ser else {}
    return {"y1": rets.get("1y"), "m1": rets.get("1m"), "vol": calc.annualized_volatility(ser) if ser else None,
            "dd": calc.max_drawdown(ser) if ser else None, "last": ser[-1][1] if ser else None}


def _compare(db: Session, message: str, text: str, lang: str):
    if not _has(text, "compare", "versus", "vs", "συγκρινε", "συγκριση", "εναντι", "η καλυτερη"):
        return None
    insts = find_instruments(db, message)[:4]
    if len(insts) < 2:
        return None
    lines = []
    for i in insts:
        s = _stats(db, i)
        lines.append({"el": f"• {i.ticker} ({i.name}): 1 έτος {_pct(s['y1'])}, μεταβλητότητα {_pct(s['vol'], False)}, χειρότερη πτώση {_pct(s['dd'])}",
                      "en": f"• {i.ticker} ({i.name}): 1 year {_pct(s['y1'])}, volatility {_pct(s['vol'], False)}, worst fall {_pct(s['dd'])}"}[lang])
    tail = {"el": "Μεγαλύτερη απόδοση συχνά έρχεται με μεγαλύτερες διακυμάνσεις. Άνοιξα και τη σελίδα Σύγκριση με τα γραφήματα.",
            "en": "Higher returns often come with bigger swings. I've also opened the Compare page with the charts."}[lang]
    head = {"el": "Τα τελευταία 12 μήνες:", "en": "Over the last 12 months:"}[lang]
    return _reply("\n".join([head, *lines, "", tail]),
                  actions=[{"type": "navigate", "page": "compare", "tickers": [i.ticker for i in insts]}], intent="compare")


def _portfolio(db: Session, customer_id: str, text: str, lang: str):
    if not _has(text, "my portfolio", "how am i doing", "my holdings", "my positions", "how much cash", "my cash",
                "have i paid", "i have paid", "my costs", "my fees", "χαρτοφυλακιο μου", "χαρτοφυλακιο", "πωσ παω",
                "θεσεισ μου", "μετρητα μου", "ποσα μετρητα", "εχω πληρωσει", "τα κοστη μου"):
        return None
    s = practice.summary(db, repo.get_or_create_portfolio(db, customer_id))
    top = sorted(s["positions"], key=lambda p: -p["value"])[:3]
    total = s["total_value"] or 1
    if lang == "el":
        out = [f"Το χαρτοφυλάκιό σου αξίζει {_eur(s['total_value'], lang)}: σήμερα {_pct(s['day_change_pct'])} ({_eur(s['day_change'], lang)}), "
               f"από την αρχή {_pct(s['total_pnl_pct'])}.",
               f"Μετρητά: {_eur(s['cash'], lang)} ({_pct(s['cash'] / total, False)})."]
        if top:
            out.append("Μεγαλύτερες θέσεις: " + ", ".join(f"{p['ticker']} {_pct(p['value'] / total, False)}" for p in top) + ".")
        if s["realized_pnl"]:
            out.append(f"Από πωλήσεις: {_eur(s['realized_pnl'], lang)}.")
        out.append(f"Κόστη συναλλαγών μέχρι τώρα: {_eur(s['fees_paid'], lang)}.")
    else:
        out = [f"Your portfolio is worth {_eur(s['total_value'], lang)}: {_pct(s['day_change_pct'])} today ({_eur(s['day_change'], lang)}), "
               f"{_pct(s['total_pnl_pct'])} since you started.",
               f"Cash: {_eur(s['cash'], lang)} ({_pct(s['cash'] / total, False)})."]
        if top:
            out.append("Largest holdings: " + ", ".join(f"{p['ticker']} {_pct(p['value'] / total, False)}" for p in top) + ".")
        if s["realized_pnl"]:
            out.append(f"From sales: {_eur(s['realized_pnl'], lang)}.")
        out.append(f"Transaction costs so far: {_eur(s['fees_paid'], lang)}.")
    if top and top[0]["value"] / total >= 0.4:
        out.append({"el": f"Το {top[0]['ticker']} είναι μεγάλο κομμάτι του συνόλου· δες το μάθημα «Όλα τα αυγά σε ένα καλάθι».",
                    "en": f"{top[0]['ticker']} is a big slice of the total; see the lesson 'All your eggs in one basket'."}[lang])
    return _reply(" ".join(out), intent="portfolio")


def _risk(db: Session, message: str, text: str, lang: str):
    if not _has(text, "risk", "risky", "volatil", "safe", "ρισκο", "κινδυνο", "επικινδυν", "ασφαλ", "μεταβλητοτητα"):
        return None
    insts = find_instruments(db, message)
    if not insts:
        return None
    from forecasting import registry
    i = insts[0]
    s = _stats(db, i)
    preds = {p.target: p.value for p in registry.latest_predictions(db, "volatility", i.ticker)}
    model_vol, p_loss = preds.get("vol_21d_annualized"), preds.get("p_loss_10pct_21d")
    if lang == "el":
        out = f"{i.ticker} ({i.name}): τον τελευταίο χρόνο η μεταβλητότητα ήταν {_pct(s['vol'], False)} και η χειρότερη πτώση {_pct(s['dd'])}."
        if model_vol is not None:
            out += f" Το μοντέλο μας εκτιμά μεταβλητότητα {_pct(model_vol, False)} τον επόμενο μήνα"
            out += f" και πιθανότητα {_pct(p_loss, False)} για πτώση πάνω από 10% μέσα σε έναν μήνα." if p_loss is not None else "."
        out += " Είναι εκτίμηση από το παρελθόν, όχι πρόβλεψη."
    else:
        out = f"{i.ticker} ({i.name}): over the last year its volatility was {_pct(s['vol'], False)} and its worst fall {_pct(s['dd'])}."
        if model_vol is not None:
            out += f" Our model estimates {_pct(model_vol, False)} volatility for the next month"
            out += f" and a {_pct(p_loss, False)} chance of falling more than 10% within a month." if p_loss is not None else "."
        out += " That's an estimate from the past, not a forecast."
    return _reply(out, lesson=C.lesson("volatility", lang), intent="risk")


def _price(db: Session, message: str, text: str, lang: str):
    insts = find_instruments(db, message)
    if not insts:
        return None
    short = len(text.split()) <= 3
    if not (short or _has(text, "price", "quote", "how much is", "how is", "τιμη", "ποσο κανει", "ποσο εχει", "πωσ παει", "πωσ τα παει")):
        return None
    i = insts[0]
    if i.market not in practice.TRADABLE_MARKETS and i.market != "index":
        return None
    from . import quotes
    q = quotes.intraday(db, i)
    s = _stats(db, i)
    day = (q.last / q.prev_close - 1) if q.last and q.prev_close else None
    when = {"el": "τώρα" if q.market_open else "στο τελευταίο κλείσιμο", "en": "now" if q.market_open else "at the last close"}[lang]
    if lang == "el":
        out = (f"{i.ticker} ({i.name}): {_num(q.last, lang)} {q.currency} {when}, {_pct(day)} σήμερα, "
               f"{_pct(s['m1'])} τον μήνα, {_pct(s['y1'])} τον χρόνο.")
    else:
        out = (f"{i.ticker} ({i.name}): {_num(q.last, lang)} {q.currency} {when}, {_pct(day)} today, "
               f"{_pct(s['m1'])} over a month, {_pct(s['y1'])} over a year.")
    return _reply(out, actions=[{"type": "navigate", "page": "asset", "ticker": i.ticker}], intent="price")


def _concept(text: str, lang: str, has_instrument: bool):
    asking = _has(text, *QUESTION_WORDS) or text.strip().endswith(("?", ";"))
    if not asking and len(text.split()) > 4:
        return None
    for lesson_id, words in CONCEPTS.items():
        if lesson_id == "crypto_risk" and has_instrument:
            continue
        if _has(text, *words):
            lesson = C.lesson(lesson_id, lang)
            return _reply(lesson["text"], lesson=lesson, intent="concept")
    return None


def _greeting(text: str, lang: str):
    t = text.strip(" !.?;")
    if not (t in ("hi", "hello", "hey", "γεια", "γεια σου", "καλησπερα", "καλημερα", "help", "βοηθεια")
            or _has(text, "what can you do", "τι μπορεισ")):
        return None
    return _reply({
        "el": "Γεια! Μπορώ να σου πω τιμές («τιμή ETE.AT»), το ρίσκο μιας επένδυσης («ρίσκο BTC»), πώς πάει το χαρτοφυλάκιό σου, "
              "να συγκρίνω επενδύσεις («σύγκρινε ETE με ALPHA»), να εξηγήσω έννοιες («τι είναι ETF;») ή να κάνω μια εκπαιδευτική "
              "αγορά («αγόρασε 5 ETE.AT»). Για οτιδήποτε άλλο, ρώτα ελεύθερα.",
        "en": "Hi! I can give you prices (\"price of ETE.AT\"), the risk of an investment (\"how risky is BTC\"), how your portfolio "
              "is doing, compare investments (\"compare ETE vs ALPHA\"), explain ideas (\"what is an ETF?\") or place a practice "
              "trade (\"buy 5 ETE.AT\"). For anything else, just ask.",
    }[lang], intent="greeting")


# ---------------------------------------------------------------- economy (macro snapshots)
# indicator id -> (English name, Greek name)
INDICATOR_NAMES = {
    "hicp_yoy": ("Inflation in Greece", "Πληθωρισμός στην Ελλάδα"), "hicp_yoy_eu": ("EU inflation", "Πληθωρισμός ΕΕ"),
    "unemp": ("Unemployment in Greece", "Ανεργία στην Ελλάδα"), "unemp_eu": ("EU unemployment", "Ανεργία ΕΕ"),
    "youth_unemp": ("Youth unemployment in Greece", "Ανεργία νέων στην Ελλάδα"),
    "gdp_qoq": ("Greek GDP growth (quarter on quarter)", "Ανάπτυξη ΑΕΠ Ελλάδας (ανά τρίμηνο)"),
    "gov_debt_gdp": ("Greek public debt", "Δημόσιο χρέος Ελλάδας"), "hh_saving": ("Greek household saving rate", "Αποταμίευση νοικοκυριών"),
    "consumer_conf": ("Greek consumer confidence", "Καταναλωτική εμπιστοσύνη"),
    "ecb_dfr": ("ECB deposit rate", "Επιτόκιο καταθέσεων ΕΚΤ"), "euribor_3m": ("3-month Euribor", "Euribor 3 μηνών"),
    "mortgage_rate": ("Greek new mortgage rate", "Επιτόκιο νέων στεγαστικών"), "deposit_rate": ("Greek term-deposit rate", "Επιτόκιο προθεσμιακών καταθέσεων"),
    "ggb_10y": ("Greek 10-year bond yield", "Απόδοση 10ετούς ελληνικού ομολόγου"),
    "bund_10y": ("German 10-year bond yield", "Απόδοση 10ετούς γερμανικού ομολόγου"),
    "spread_10y": ("Greece–Germany 10-year spread", "Spread Ελλάδας–Γερμανίας (10ετές)"),
    "eurusd": ("EUR/USD", "Ισοτιμία ευρώ/δολαρίου"), "us_fed_funds": ("US Fed funds rate", "Επιτόκιο Fed (ΗΠΑ)"),
    "us_10y": ("US 10-year Treasury yield", "Απόδοση 10ετούς αμερικανικού ομολόγου"), "vix": ("VIX (US market fear gauge)", "VIX (δείκτης «φόβου» ΗΠΑ)"),
    "brent": ("Brent oil", "Πετρέλαιο Brent"), "crypto_fear_greed": ("Crypto Fear & Greed", "Crypto Fear & Greed"),
}
MACRO_TOPICS = [  # (words, indicators); the first matching topic wins
    (("inflation", "prices rising", "cost of living", "πληθωρισμ", "ακριβει"), ("hicp_yoy",)),
    (("unemploy", "jobs", "ανεργια", "δουλειεσ", "απασχοληση"), ("unemp", "youth_unemp")),
    (("gdp", "growth", "recession", "αεπ", "αναπτυξη", "υφεση"), ("gdp_qoq",)),
    (("mortgage", "loan", "στεγαστικ", "δανει"), ("mortgage_rate", "euribor_3m", "ecb_dfr")),
    (("deposit", "savings rate", "καταθεσ"), ("deposit_rate", "ecb_dfr")),
    (("interest rate", "rates", "ecb", "euribor", "επιτοκι", "εκτ"), ("ecb_dfr", "euribor_3m", "mortgage_rate")),
    (("spread", "bond", "yield", "ομολογ", "αποδοση ομολογ"), ("ggb_10y", "bund_10y", "spread_10y")),
    (("public debt", "government debt", "δημοσιο χρεοσ", "χρεοσ"), ("gov_debt_gdp",)),
    (("oil", "brent", "πετρελαι"), ("brent",)),
    (("euro dollar", "eur/usd", "eurusd", "ευρω δολαριο", "ισοτιμια ευρω"), ("eurusd",)),
    (("fear", "sentiment", "confidence", "vix", "φοβοσ", "εμπιστοσυνη", "κλιμα"), ("vix", "crypto_fear_greed", "consumer_conf")),
    (("economy", "economic", "οικονομια", "οικονομικ"), ("gdp_qoq", "hicp_yoy", "unemp", "ecb_dfr")),
]
EU_PAIR = {"hicp_yoy": "EU", "unemp": "EU", "gdp_qoq": "EU"}
UNITS = {"pct_yoy": "%", "pct": "%", "pct_qoq": "%", "pct_gdp": "% of GDP", "bps": " bps", "usd": " USD",
         "usd_per_eur": " USD", "index": "", "balance": ""}
DIRECTION = {"rising": ("rising", "ανοδικά"), "falling": ("falling", "καθοδικά"), "stable": ("about stable", "σταθερά")}
MONTHS_EL = ["Ιαν", "Φεβ", "Μαρ", "Απρ", "Μαΐ", "Ιουν", "Ιουλ", "Αυγ", "Σεπ", "Οκτ", "Νοε", "Δεκ"]


def _short(x: float, lang: str) -> str:
    """2.50 -> 2.5, 2.635 -> 2.64, 143.0 -> 143 (decimal comma in Greek)."""
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") if lang == "el" else s


def _when(d: datetime.date, lang: str) -> str:
    return f"{MONTHS_EL[d.month - 1]} {d.year}" if lang == "el" else d.strftime("%b %Y")


def _macro(db: Session, text: str, lang: str):
    topic = next((ids for words, ids in MACRO_TOPICS if _has(text, *words)), None)
    if topic is None:
        return None
    if _has(text, "why", "how does", "how do", "explain", "γιατι", "πωσ λειτουργ", "πωσ επηρεαζ", "εξηγησ"):
        return None  # asking for an explanation, not the figures: the AI answers
    day = mr.latest_snapshot_date(db)
    snaps = mr.snapshots_on(db, day) if day else {}
    from pipelines.catalog import INDICATORS_BY_ID
    units = {k: v["unit"] for k, v in INDICATORS_BY_ID.items()}
    lines = []
    for iid in topic:
        s = snaps.get(iid)
        if s is None:
            continue
        en, el = INDICATOR_NAMES.get(iid, (iid, iid))
        unit = UNITS.get(units.get(iid, ""), "")
        val = _short(s.value, lang) if abs(s.value) < 1e6 else f"{s.value:,.0f}"
        trend = DIRECTION.get(s.direction_90d, ("", ""))[1 if lang == "el" else 0]
        line = (f"• {el}: {val}{unit} ({_when(s.obs_date, lang)}), {trend} τους τελευταίους 3 μήνες" if lang == "el"
                else f"• {en}: {val}{unit} ({_when(s.obs_date, lang)}), {trend} over the last 3 months")
        if s.value_eu is not None and iid in EU_PAIR:
            line += f" · ΕΕ-27: {_short(s.value_eu, lang)}{unit}" if lang == "el" else f"; EU-27: {_short(s.value_eu, lang)}{unit}"
        lines.append(line)
    if not lines:
        return None
    head = {"el": "Τα πιο πρόσφατα στοιχεία:", "en": "The latest figures:"}[lang]
    notes = []
    if _has(text, "germany", "german", "γερμανι"):
        notes.append({"el": "Για τη Γερμανία έχουμε μόνο την απόδοση του 10ετούς ομολόγου· η σύγκριση εδώ γίνεται με τον μέσο όρο της ΕΕ.",
                      "en": "For Germany we only have its 10-year bond yield; the comparison here is with the EU average."}[lang])
    notes.append({"el": "Πηγές: Eurostat, ΕΚΤ, FRED. Τα στοιχεία δημοσιεύονται με καθυστέρηση και δεν είναι πρόβλεψη.",
                  "en": "Sources: Eurostat, ECB, FRED. Figures are published with a delay and are not a forecast."}[lang])
    return _reply("\n".join([head, *lines, "", *notes]), intent="macro")


# ---------------------------------------------------------------- top movers (latest session)
MARKET_WORDS = {"athens": ("athens", "greek", "greece", "αθηνα", "ελληνικ", "χρηματιστηριο αθηνων"),
                "europe": ("europe", "european", "ευρωπ"), "us": ("us ", "usa", "american", "wall street", "αμερικ", "ηπα"),
                "etf": ("etf",), "crypto": ("crypto", "coins", "κρυπτο")}


def _movers(db: Session, text: str, lang: str):
    if not _has(text, "top movers", "movers", "gainers", "losers", "best performing", "worst performing", "went up the most",
                "fell the most", "biggest rise", "biggest fall", "ανεβηκαν περισσοτερο", "επεσαν περισσοτερο",
                "μεγαλυτερη ανοδο", "μεγαλυτερη πτωση", "κερδισμεν", "χαμεν", "καλυτερεσ σημερα", "χειροτερεσ σημερα"):
        return None
    from ..routers.market import _overview
    market = next((m for m, words in MARKET_WORDS.items() if _has(text, *words)), None)
    rows = [r for r in _overview(db) if r.get("change_1d") is not None and r["market"] in practice.TRADABLE_MARKETS
            and (market is None or r["market"] == market)]
    if not rows:
        return None
    rows.sort(key=lambda r: r["change_1d"])
    up, down = rows[::-1][:3], rows[:3]
    fmt = lambda r: f"{r['ticker']} ({r['name']}) {_pct(r['change_1d'])}"
    label = {"athens": ("Athens", "Αθήνα"), "europe": ("Europe", "Ευρώπη"), "us": ("US", "ΗΠΑ"), "etf": ("ETFs", "ETF"),
             "crypto": ("crypto", "κρυπτονομίσματα")}.get(market, ("all markets", "όλες τις αγορές"))
    if lang == "el":
        out = (f"Στην τελευταία συνεδρίαση ({label[1]}):\n▲ " + ", ".join(map(fmt, up)) + "\n▼ " + ", ".join(map(fmt, down))
               + "\n\nΜεγάλες κινήσεις μιας μέρας είναι συχνές· δεν λένε τι θα γίνει μετά.")
    else:
        out = (f"In the latest session ({label[0]}):\n▲ " + ", ".join(map(fmt, up)) + "\n▼ " + ", ".join(map(fmt, down))
               + "\n\nBig one-day moves are common; they don't tell you what comes next.")
    return _reply(out, lesson=C.lesson("market_moves", lang), intent="movers")


def answer(db: Session, customer_id: str, message: str, lang: str = "en") -> dict | None:
    """A fixed-wording answer with real numbers, or None when the AI should answer."""
    lang = lang if lang in C.LANGS else "en"
    text = norm(message)
    has_inst = bool(find_instruments(db, message))
    for step in (lambda: _trade(db, message, text, lang), lambda: _navigate(text, lang),
                 lambda: _compare(db, message, text, lang), lambda: _portfolio(db, customer_id, text, lang),
                 lambda: _movers(db, text, lang), lambda: _risk(db, message, text, lang),
                 lambda: _concept(text, lang, has_inst), lambda: None if has_inst else _macro(db, text, lang),
                 lambda: _price(db, message, text, lang), lambda: _greeting(text, lang)):
        out = step()
        if out is not None:
            if lang == "el":  # Greek decimal comma in percentages too: +1.6% -> +1,6%
                out["reply"] = re.sub(r"(\d)\.(\d+%)", r"\1,\2", out["reply"])
            return out
    return None
