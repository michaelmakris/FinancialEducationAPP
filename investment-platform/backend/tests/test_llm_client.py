"""Request shapes for the OpenAI-style providers (no network)."""
import pytest

from app.config import settings
from app.services import llm


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        return _Resp({"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    return calls


def test_azure_uses_v1_endpoint_deployment_and_gpt5_parameters(monkeypatch, sent):
    monkeypatch.setattr(settings, "llm_provider", "azure")
    monkeypatch.setattr(settings, "azure_openai_endpoint", "https://res.openai.azure.com/")
    monkeypatch.setattr(settings, "azure_openai_deployment", "gpt-5.2")
    monkeypatch.setattr(settings, "azure_openai_api_key", "test-key")
    monkeypatch.setattr(settings, "azure_openai_reasoning_effort", "low")
    msg = llm.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}], max_tokens=900, temperature=0.2)
    c = sent[-1]
    assert msg["content"] == "ok"
    assert c["url"] == "https://res.openai.azure.com/openai/v1/chat/completions"
    assert c["headers"] == {"api-key": "test-key"}
    assert c["json"]["model"] == "gpt-5.2" and c["json"]["reasoning_effort"] == "low"
    assert c["json"]["max_completion_tokens"] >= 2048 and "max_tokens" not in c["json"]
    assert "temperature" not in c["json"] and c["json"]["tools"] == [{"type": "function"}]


def test_azure_without_key_uses_entra_token_and_caches_it(monkeypatch, sent):
    monkeypatch.setattr(settings, "llm_provider", "azure")
    monkeypatch.setattr(settings, "azure_openai_endpoint", "https://res.openai.azure.com")
    monkeypatch.setattr(settings, "azure_openai_deployment", "gpt-5-mini")
    monkeypatch.setattr(settings, "azure_openai_api_key", "")

    class Cred:
        n = 0

        def get_token(self, scope):
            Cred.n += 1
            assert scope == "https://cognitiveservices.azure.com/.default"
            return type("T", (), {"token": "entra-token", "expires_on": __import__("time").time() + 3600})()

    monkeypatch.setattr(llm, "_credential", Cred())
    monkeypatch.setattr(llm, "_token", None)
    llm.chat([{"role": "user", "content": "a"}])
    llm.chat([{"role": "user", "content": "b"}])
    assert sent[-1]["headers"] == {"Authorization": "Bearer entra-token"} and Cred.n == 1  # token reused


def test_azure_requires_endpoint_and_deployment(monkeypatch, sent):
    monkeypatch.setattr(settings, "llm_provider", "azure")
    monkeypatch.setattr(settings, "azure_openai_endpoint", "")
    with pytest.raises(RuntimeError, match="AZURE_OPENAI_ENDPOINT"):
        llm.chat([{"role": "user", "content": "x"}])


def test_selfhosted_keeps_its_original_request(monkeypatch, sent):
    monkeypatch.setattr(settings, "llm_provider", "selfhosted")
    monkeypatch.setattr(settings, "selfhosted_base_url", "http://localhost:8001/v1")
    llm.chat([{"role": "user", "content": "x"}], max_tokens=900, temperature=0.2)
    c = sent[-1]
    assert c["url"] == "http://localhost:8001/v1/chat/completions" and c["headers"] == {}
    assert c["json"]["max_tokens"] == 900 and c["json"]["temperature"] == 0.2


def _configure_both(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "azure")
    monkeypatch.setattr(settings, "azure_openai_endpoint", "https://res.openai.azure.com")
    monkeypatch.setattr(settings, "azure_openai_deployment", "gpt-5.2")
    monkeypatch.setattr(settings, "azure_openai_api_key", "k")
    monkeypatch.setattr(settings, "selfhosted_base_url", "http://localhost:8001/v1")
    monkeypatch.setattr(settings, "anthropic_api_key", None)


def test_both_providers_are_offered_and_choice_is_per_request(monkeypatch, sent):
    _configure_both(monkeypatch)
    ids = {p["id"]: p["default"] for p in llm.available()}
    assert ids == {"azure": True, "selfhosted": False}
    with llm.use("selfhosted"):
        llm.chat([{"role": "user", "content": "x"}])
    assert sent[-1]["url"].startswith("http://localhost:8001")
    llm.chat([{"role": "user", "content": "x"}])                    # outside the block: back to the default
    assert sent[-1]["url"].startswith("https://res.openai.azure.com")
    with pytest.raises(ValueError):
        with llm.use("anthropic"):                                   # not configured
            pass


def test_chat_endpoint_accepts_a_provider_and_records_it(client, monkeypatch):
    _configure_both(monkeypatch)
    from app.services.agents import orchestrator
    seen = {}

    def fake_run_chat(message, history, lang="en"):
        seen["provider"] = llm.current()
        return "hi", [], ["analysis"]

    monkeypatch.setattr(orchestrator, "run_chat", fake_run_chat)
    assert client.post("/chat", json={"message": "x", "history": [], "provider": "selfhosted"}).status_code == 200
    assert seen["provider"] == "selfhosted"
    assert client.post("/chat", json={"message": "x", "history": []}).status_code == 200
    assert seen["provider"] == "azure"
    assert client.post("/chat", json={"message": "x", "history": [], "provider": "nope"}).status_code == 422
    providers = client.get("/v1/llm/providers").json()
    assert [p["id"] for p in providers] == ["azure", "selfhosted"]
    from app.db import SessionLocal
    from app.models import ChatInteraction
    db = SessionLocal()
    rows = db.query(ChatInteraction).order_by(ChatInteraction.id.desc()).limit(2).all()
    assert [r.provider for r in rows] == ["azure", "selfhosted"]
    db.close()


# ---------------------------------------------------------------- limits: tokens, history, tool results
def test_usage_is_counted_per_request(monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return _Resp({"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 120, "completion_tokens": 30}})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    monkeypatch.setattr(settings, "llm_provider", "selfhosted")
    monkeypatch.setattr(settings, "selfhosted_base_url", "http://localhost:8001/v1")
    with llm.count_usage() as used:
        llm.chat([{"role": "user", "content": "a"}])
        llm.chat([{"role": "user", "content": "b"}])
    assert used == {"prompt": 240, "completion": 60, "total": 300}
    llm.chat([{"role": "user", "content": "c"}])          # outside a block: nothing to count, no error


def test_tool_results_and_history_are_capped(monkeypatch):
    from app.services.agents import base
    monkeypatch.setattr(settings, "llm_max_tool_result_chars", 600)
    big = {"rows": [{"ticker": f"T{i}", "name": "x" * 30, "value": i} for i in range(500)]}
    text = base.compact(big)
    assert len(text) <= 600 and "more left out" in text
    assert base.compact({"a": 1}) == '{"a":1}'                         # small results untouched
    monkeypatch.setattr(settings, "llm_max_history_messages", 3)
    monkeypatch.setattr(settings, "llm_max_history_chars", 10)
    hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"message number {i}"} for i in range(9)]
    out = base.trim_history(hist)
    assert len(out) == 3 and out[-1]["content"] == "message nu ..." and out[0]["content"].startswith("message nu")


def test_agent_loop_sends_capped_tool_results_and_output_budget(monkeypatch):
    from app.services.agents import base
    monkeypatch.setattr(settings, "llm_provider", "selfhosted")
    monkeypatch.setattr(settings, "llm_max_output_tokens", 321)
    monkeypatch.setattr(settings, "llm_max_tool_result_chars", 500)
    sent = []

    def fake_chat(messages, tools=None, max_tokens=None, **kw):
        sent.append((list(messages), max_tokens))
        if len(sent) == 1:
            return {"role": "assistant", "content": None,
                    "tool_calls": [{"id": "1", "type": "function", "function": {"name": "dump", "arguments": "{}"}}]}
        return {"role": "assistant", "content": "done"}

    monkeypatch.setattr(llm, "chat", fake_chat)
    reply = base.run_agent("sys", [{"name": "dump", "description": "d", "input_schema": {"type": "object"}}],
                           lambda n, i: {"series": list(range(10_000))}, "q", history=[])
    assert reply == "done" and all(mt == 321 for _, mt in sent)
    tool_msg = next(m for m in sent[1][0] if m.get("role") == "tool")
    assert len(tool_msg["content"]) <= 500


def test_chat_daily_budget_and_question_length(client, monkeypatch):
    from app.db import SessionLocal
    from app.models import ChatInteraction
    from app.services.agents import orchestrator
    from tests.conftest import TEST_CUSTOMER
    monkeypatch.setattr(orchestrator, "run_chat", lambda message, history, lang="en": ("ok", [], []))
    monkeypatch.setattr(settings, "llm_max_message_chars", 50)
    assert client.post("/chat", json={"message": "x" * 51, "history": []}).status_code == 422
    monkeypatch.setattr(settings, "llm_daily_token_budget", 1000)
    db = SessionLocal()
    db.add(ChatInteraction(customer_id=TEST_CUSTOMER, user_message="earlier", assistant_reply="r", provider="azure",
                           agents_used="", actions_json="[]", status="ok", detail="", latency_ms=1, tokens_used=1000))
    db.commit()
    r = client.post("/chat", json={"message": "tell me a story about markets", "history": [], "lang": "el"})
    assert r.status_code == 429 and "όριο" in r.json()["detail"]
    monkeypatch.setattr(settings, "llm_daily_token_budget", 0)          # 0 = no budget
    assert client.post("/chat", json={"message": "tell me a story about markets", "history": []}).status_code == 200
    db.query(ChatInteraction).filter_by(customer_id=TEST_CUSTOMER, user_message="earlier").delete()
    db.commit()
    db.close()
