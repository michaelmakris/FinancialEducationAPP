"""Tsimp, the mosquito coach: when it speaks, with which numbers, in which language."""
import datetime as dt

import pytest

from app.services import coach_content


@pytest.fixture
def fresh(client, practice_market):
    client.post("/portfolio/reset")
    return practice_market


def ids(nudges):
    return [n["id"] for n in nudges]


def test_big_buy_triggers_concentration_with_the_real_share(client, fresh):
    # 700 x 10 EUR = 7,000 of a 10,000 portfolio: the example from the design (70%)
    out = client.post("/v1/coach/pre-trade", json={"side": "buy", "ticker": "TESTA.AT", "qty": 700, "lang": "el"}).json()
    n = next(x for x in out if x["id"] == "concentration")
    assert n["facts"]["share"] == pytest.approx(0.7) and n["facts"]["amount"] == pytest.approx(7000)
    assert "70%" in n["text"] and n["title"].startswith("Τσιμπ")
    assert [r["lesson"] for r in n["replies"]] == ["concentration", "diversification"]
    assert n["replies"][0]["label"] == "Ναι, εξήγησέ μου"
    assert client.get("/portfolio").json()["positions"] == []          # nothing was traded


def test_small_buy_says_nothing(client, fresh):
    # 10 x 50 EUR = 5% of the portfolio, a coin that has not moved today
    assert client.post("/v1/coach/pre-trade", json={"side": "buy", "ticker": "TST-EUR", "qty": 10}).json() == []


def test_chasing_a_jump_and_crypto_and_low_cash(client, fresh):
    fresh["TESTA.AT"] = 10.0                                              # prev close 9 -> +11% today
    out = client.post("/v1/coach/pre-trade", json={"side": "buy", "ticker": "TESTA.AT", "qty": 980, "lang": "en"}).json()
    assert {"fomo", "low_cash", "concentration"} <= set(ids(out))
    crypto = client.post("/v1/coach/pre-trade", json={"side": "buy", "ticker": "TST-EUR", "qty": 30}).json()  # 15%
    assert "crypto_risk" in ids(crypto)


def test_first_us_share_explains_currency_risk(client, fresh):
    out = client.post("/v1/coach/pre-trade", json={"side": "buy", "ticker": "TSTUS.US", "qty": 1}).json()
    assert ids(out) == ["currency_risk"]
    client.post("/portfolio/buy", json={"ticker": "TSTUS.US", "qty": 1})
    assert client.post("/v1/coach/pre-trade", json={"side": "buy", "ticker": "TSTUS.US", "qty": 1}).json() == []


def test_selling_at_a_loss_and_on_a_bad_day(client, fresh):
    client.post("/portfolio/buy", json={"ticker": "TST-EUR", "qty": 10})        # 10 x 50
    fresh["TST-EUR"] = 40.0                                                        # -20% vs cost, -20% today
    out = client.post("/v1/coach/pre-trade", json={"side": "sell", "ticker": "TST-EUR", "qty": 10}).json()
    assert {"loss_selling", "panic_sell"} <= set(ids(out))
    small = client.post("/v1/coach/pre-trade", json={"side": "sell", "ticker": "TST-EUR", "qty": 1}).json()
    assert "loss_selling" not in ids(small)                                       # selling 10% of it


def test_events_after_trading(client, fresh):
    start = client.get("/v1/coach/events", params={"lang": "en"}).json()
    today = dt.date.today().isoformat()
    assert any(i.startswith("idle_cash:") for i in ids(start))                   # all cash after reset
    client.post("/portfolio/buy", json={"ticker": "TESTA.AT", "qty": 600})     # 6,000 = 60%
    out = client.get("/v1/coach/events", params={"lang": "en"}).json()
    got = ids(out)
    assert "first_trade" in got
    assert any(i.startswith("big_mover:TESTA.AT:") for i in got)                 # +11% today
    assert any(i.startswith("concentrated:TESTA.AT:") for i in got)
    assert not any(i.startswith("idle_cash:") for i in got)
    big = next(n for n in out if n["id"].startswith("big_mover"))
    assert "+11%" in big["text"] and today[:4] in big["id"]


def test_portfolio_down_day(client, fresh):
    client.post("/portfolio/buy", json={"ticker": "TST-EUR", "qty": 100})       # 5,000 at 50
    fresh["TST-EUR"] = 40.0                                                        # -1,000 on the day = -10%
    got = ids(client.get("/v1/coach/events").json())
    assert any(i.startswith("day_down:") for i in got)


def test_page_notes_tip_and_lessons_in_both_languages(client, fresh):
    for page in ("discover", "asset", "portfolio", "plan", "compare", "simulator", "home"):
        el = client.get(f"/v1/coach/learn/{page}", params={"lang": "el"}).json()
        en = client.get(f"/v1/coach/learn/{page}", params={"lang": "en"}).json()
        assert el["id"] == en["id"] == f"learn:{page}" and el["text"] != en["text"]
    assert client.get("/v1/coach/learn/nowhere").status_code == 404
    tip = client.get("/v1/coach/tip", params={"lang": "el"}).json()
    assert tip["kind"] == "tip" and tip["id"].startswith("tip:") and tip["title"] == "Η σκέψη της ημέρας"
    lesson = client.get("/v1/coach/lessons/diversification", params={"lang": "el"}).json()
    assert lesson["title"] == "Τι είναι η διαφοροποίηση;" and lesson["ask"] and lesson["next"]
    assert client.get("/v1/coach/lessons/nope").status_code == 404


def test_every_lesson_and_reference_exists_in_both_languages():
    for lid, item in coach_content.LESSONS.items():
        for lang in coach_content.LANGS:
            assert item[lang]["title"] and item[lang]["text"] and item[lang]["ask"], (lid, lang)
        assert all(n in coach_content.LESSONS for n in item.get("next", [])), lid
    assert all(n["lesson"] in coach_content.LESSONS for n in coach_content.PAGE_NOTES.values())
    assert all(t[0] in coach_content.LESSONS for t in coach_content.DAILY_TIPS)


def test_lessons_never_tell_people_to_buy_or_sell():
    import re
    banned = re.compile(r"\b(you should (buy|sell)|buy now|sell now|guaranteed|will rise|will fall)\b|"
                        r"(πρέπει να (αγοράσεις|πουλήσεις)|εγγυημένη|σίγουρα θα ανέβει)", re.I)
    texts = [item[lang][k] for item in coach_content.LESSONS.values() for lang in coach_content.LANGS for k in ("title", "text")]
    texts += [t[1] for t in coach_content.DAILY_TIPS] + [t[2] for t in coach_content.DAILY_TIPS]
    assert not [t for t in texts if banned.search(t)]


def test_chat_passes_the_language_to_tsimp(client, monkeypatch):
    from app.services.agents import orchestrator
    seen = {}

    def fake(message, history, lang="en"):
        seen["lang"] = lang
        return "ok", [], []

    monkeypatch.setattr(orchestrator, "run_chat", fake)
    assert client.post("/chat", json={"message": "πες μου μια ιστορία για τις αγορές", "history": [], "lang": "el"}).status_code == 200
    assert seen["lang"] == "el"
    assert client.post("/chat", json={"message": "x", "history": [], "lang": "fr"}).status_code == 422
