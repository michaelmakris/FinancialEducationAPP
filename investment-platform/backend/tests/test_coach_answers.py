"""Deterministic chat answers: recognised questions never reach the AI."""
import pytest

from app.config import settings
from app.services import coach_answers as A


@pytest.fixture
def ai_calls(client, practice_market, monkeypatch):
    """Records what reaches the AI (nothing should, for recognised questions)."""
    from app.services.agents import orchestrator
    calls = []

    def fake(message, history, lang="en"):
        calls.append(message)
        return "from the AI", [], []

    monkeypatch.setattr(orchestrator, "run_chat", fake)
    client.post("/portfolio/reset")
    return calls


def ask(client, message, lang="en"):
    r = client.post("/chat", json={"message": message, "history": [], "lang": lang})
    assert r.status_code == 200, r.text
    return r.json()


def test_trades_in_english_and_greek(client, ai_calls):
    r = ask(client, "buy 5 TESTA.AT")
    assert r["source"] == "rules" and r["actions"] == [{"type": "trade", "side": "buy", "ticker": "TESTA.AT", "qty": 5.0,
                                                        "page": None, "tickers": None}]
    assert "EUR 50.00" in r["reply"]
    r = ask(client, "Πούλησε 2,5 TST-EUR", "el")
    assert r["actions"][0]["side"] == "sell" and r["actions"][0]["qty"] == 2.5 and r["reply"].startswith("Πώληση")
    assert "Πόσα" in ask(client, "αγόρασε TESTA.AT", "el")["reply"]                # quantity missing
    assert ai_calls == []


def test_navigation_compare_portfolio(client, ai_calls):
    assert ask(client, "open my portfolio")["actions"][0] == {"type": "navigate", "page": "portfolio", "ticker": None,
                                                             "tickers": None, "side": None, "qty": None}
    assert ask(client, "άνοιξε τις αγορές", "el")["actions"][0]["page"] == "discover"
    cmp = ask(client, "compare TESTA.AT vs TSTUS.US")
    assert cmp["actions"][0]["page"] == "compare" and cmp["actions"][0]["tickers"] == ["TESTA.AT", "TSTUS.US"]
    assert "TESTA.AT (Test Athens Co): 1 year" in cmp["reply"]
    pf = ask(client, "how is my portfolio doing?")
    assert "EUR 10,000.00" in pf["reply"] and "Cash" in pf["reply"]
    assert "αξίζει €10.000,00" in ask(client, "πώς πάει το χαρτοφυλάκιό μου;", "el")["reply"]
    assert ai_calls == []


def test_risk_price_concepts_greeting(client, ai_calls):
    risk = ask(client, "how risky is TST-EUR?")
    assert "volatility" in risk["reply"] and risk["lesson"]["id"] == "volatility"
    price = ask(client, "price of TSTUS.US")
    assert "100.00 USD" in price["reply"] and price["actions"][0]["page"] == "asset"
    assert ask(client, "TESTA.AT")["actions"][0]["ticker"] == "TESTA.AT"            # just a ticker
    concept = ask(client, "Τι είναι η διαφοροποίηση;", "el")
    assert concept["lesson"]["id"] == "diversification" and concept["reply"].startswith("Διαφοροποίηση")
    assert ask(client, "what is an ETF?")["lesson"]["id"] == "etf"
    assert "practice" in ask(client, "hi")["reply"]
    assert ai_calls == []


def test_everything_else_goes_to_the_ai(client, ai_calls):
    r = ask(client, "Should I worry about inflation and interest rates next year for my savings?")
    assert r["source"] == "ai" and r["reply"] == "from the AI" and len(ai_calls) == 1


def test_rules_answer_even_when_the_ai_budget_is_used_up(client, ai_calls, monkeypatch):
    from app import repo
    monkeypatch.setattr(settings, "llm_daily_token_budget", 1)
    monkeypatch.setattr(repo, "tokens_used_today", lambda db, cid: 10)
    assert ask(client, "what is an ETF?")["source"] == "rules"
    assert client.post("/chat", json={"message": "Tell me a story about markets", "history": []}).status_code == 429


def test_short_words_do_not_match_tickers(client, practice_market):
    from app.db import SessionLocal
    from pipelines import market_writer as w
    db = SessionLocal()
    w.ensure_instrument(db, ticker="T.US", name="AT&T", sector="Telecom", asset_type="equity", exchange="NYSE",
                        currency="USD", data_source="yahoo", vendor_symbol="T", market="us")
    db.commit()
    assert [i.ticker for i in A.find_instruments(db, "is it a good time to invest?")] == []
    assert [i.ticker for i in A.find_instruments(db, "price of T")] == ["T.US"]
    assert A.norm("Τι ΕΊΝΑΙ ο Δείκτης;") == "τι ειναι ο δεικτησ;"
    db.close()


def test_cached_lookup_works_across_requests(practice_market, monkeypatch):
    """The instrument lookup is cached between requests; it must not hold objects from an old session."""
    from app import market_repo
    from app.db import SessionLocal
    monkeypatch.setattr(settings, "market_cache_ttl_s", 300)
    market_repo.clear_cache()
    first = SessionLocal()
    assert [i.ticker for i in A.find_instruments(first, "price of TESTA.AT")] == ["TESTA.AT"]
    first.close()
    second = SessionLocal()
    found = A.find_instruments(second, "price of TESTA.AT")
    assert found[0].name == "Test Athens Co"          # loading an attribute failed before the fix
    second.close()
    market_repo.clear_cache()


def test_greek_answers_use_decimal_commas(client, ai_calls):
    import re
    reply = ask(client, "τιμή TSTUS.US", "el")["reply"]
    assert "100,00 USD" in reply and "0,0%" in reply          # price and today's change, Greek style
    assert not re.search(r"[0-9][.][0-9]+%", reply)


@pytest.fixture
def macro_and_moves(practice_market):
    """Inflation/unemployment snapshots and two daily closes for the test instruments."""
    import datetime as dt
    from app import market_repo
    from app.db import SessionLocal
    from app.models import Instrument, IndicatorSnapshot
    from pipelines import catalog, market_writer as w
    db = SessionLocal()
    today = dt.date.today()
    for iid, value, eu, direction in (("hicp_yoy", 5.1, 3.2, "rising"), ("unemp", 7.4, 6.1, "falling")):
        w.ensure_indicator(db, catalog.INDICATORS_BY_ID[iid])
        db.query(IndicatorSnapshot).filter_by(indicator_id=iid, as_of_date=today).delete()
        db.add(IndicatorSnapshot(indicator_id=iid, as_of_date=today, obs_date=dt.date(2026, 9, 1), value=value,
                                 value_90d_prior=value - 1, direction_90d=direction, value_1y=value, value_eu=eu,
                                 staleness_d=10, payload_eligible=True))
    for ticker, prev, last in (("TESTA.AT", 10.0, 11.0), ("TSTUS.US", 100.0, 95.0), ("TST-EUR", 50.0, 51.0)):
        inst = db.query(Instrument).filter_by(ticker=ticker).one()
        w.upsert_bars(db, inst, {today - dt.timedelta(days=1): {"close": prev, "adj_close": prev},
                                 today: {"close": last, "adj_close": last}})
    db.commit()
    db.close()
    market_repo.clear_cache()


def test_economy_questions(client, ai_calls, macro_and_moves):
    r = ask(client, "What is inflation in Greece now?")
    assert r["source"] == "rules" and "Inflation in Greece: 5.1% (Sep 2026), rising" in r["reply"] and "EU-27: 3.2%" in r["reply"]
    el = ask(client, "Πώς πάει η ανεργία;", "el")["reply"]
    assert "Ανεργία στην Ελλάδα: 7,4% (Σεπ 2026), καθοδικά" in el and "· ΕΕ-27: 6,1%" in el and ";" not in el
    de = ask(client, "Is the Greek economy doing better than Germany?")["reply"]
    assert "For Germany we only have its 10-year bond yield" in de
    assert ai_calls == []
    assert ask(client, "Why do central banks raise rates when inflation is high?")["source"] == "ai"


def test_top_movers(client, ai_calls, macro_and_moves):
    r = ask(client, "top movers today")
    assert r["source"] == "rules" and r["lesson"]["id"] == "market_moves"
    up, down = r["reply"].split("\n")[1], r["reply"].split("\n")[2]
    assert up.startswith("▲ TESTA.AT") and "+10.0%" in up and down.startswith("▼ TSTUS.US") and "-5.0%" in down
    athens = ask(client, "ποιες ανέβηκαν περισσότερο στην Αθήνα;", "el")["reply"]
    assert "TESTA.AT" in athens and "TSTUS.US" not in athens and "+10,0%" in athens
    assert ai_calls == []
