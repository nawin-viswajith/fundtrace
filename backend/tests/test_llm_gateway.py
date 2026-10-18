"""GeminiGateway against a mocked google-genai client: parsing, cost, fallback chain, timeouts, budget."""
from types import SimpleNamespace

import pytest

from app import models as m
from app.ai.llm import GeminiGateway
from app.ai.pricing import cost_usd
from app.ai.schemas import Classification


class FakeModels:
    def __init__(self, behaviours):
        self.behaviours = behaviours
        self.seen = []
        self.configs = []

    def generate_content(self, model, contents, config):
        self.seen.append(model)
        self.configs.append(config)
        b = self.behaviours[model]
        if isinstance(b, list):  # a sequence of behaviours, one per call
            b = b.pop(0) if len(b) > 1 else b[0]
        if isinstance(b, Exception):
            raise b
        return b


def resp(text, parsed=None, it=1200, ot=150, tt=50, lp=-0.08):
    return SimpleNamespace(text=text, parsed=parsed, usage_metadata=SimpleNamespace(prompt_token_count=it, candidates_token_count=ot,
                                                                                    thoughts_token_count=tt),
                           candidates=[SimpleNamespace(avg_logprobs=lp)])


@pytest.fixture()
def gw(seeded, monkeypatch):
    g = GeminiGateway()
    g.BUSY_BACKOFF_S = 0
    g.s = g.s.model_copy(update={"llm_enabled": True, "gcp_project": "test-project", "gemini_fast_models": "gemini-3-flash,gemini-2.5-flash",
                                 "llm_daily_budget_usd": 5.0, "llm_case_budget_usd": 1.0})
    return g


GOOD = '{"category": "app_scam", "rationale": "customer paid a job fee", "english_translation": "I was offered a job", "detected_language": "hi"}'


def test_parses_validates_and_costs(gw, db):
    fm = FakeModels({"gemini-3-flash": resp(GOOD)})
    gw._client = SimpleNamespace(models=fm)
    r = gw.generate(node="classify", prompt_version="t", contents=["x"], schema=Classification, case_id="CASE-24044", db=db)
    assert r.ok and r.data.category.value == "app_scam"
    assert r.cost_usd == cost_usd("gemini-3-flash", 1200, 150, 50)[0]
    assert r.avg_logprob == -0.08
    row = db.query(m.AICall).filter(m.AICall.node == "classify").order_by(m.AICall.id.desc()).first()
    assert row.status == "ok" and row.input_tokens == 1200 and row.thinking_tokens == 50
    db.rollback()


def test_invalid_json_is_a_failure_not_a_guess(gw, db):
    gw._client = SimpleNamespace(models=FakeModels({"gemini-3-flash": resp('{"category": "pizza"}')}))
    r = gw.generate(node="classify", prompt_version="t", contents=["x"], schema=Classification, db=db)
    assert not r.ok and r.status == "invalid" and "Not analysed" not in r.not_analysed_reason
    assert r.not_analysed_reason == "AI returned output that failed validation"
    db.rollback()


def test_missing_model_falls_back_to_next_in_chain(gw, db):
    fm = FakeModels({"gemini-3-flash": RuntimeError("404 NOT_FOUND: model not found"), "gemini-2.5-flash": resp(GOOD)})
    gw._client = SimpleNamespace(models=fm)
    r = gw.generate(node="classify", prompt_version="t", contents=["x"], schema=Classification, db=db)
    assert r.ok and r.model == "gemini-2.5-flash" and fm.seen == ["gemini-3-flash", "gemini-2.5-flash"]
    db.rollback()


def test_timeout_does_not_fall_through(gw, db):
    fm = FakeModels({"gemini-3-flash": TimeoutError("Deadline exceeded"), "gemini-2.5-flash": resp(GOOD)})
    gw._client = SimpleNamespace(models=fm)
    r = gw.generate(node="classify", prompt_version="t", contents=["x"], schema=Classification, db=db)
    assert not r.ok and r.status == "timeout" and fm.seen == ["gemini-3-flash"]
    db.rollback()


def test_budget_guard_blocks_calls(gw, db):
    db.add(m.AICall(node="x", model="gemini-2.5-pro", prompt_version="t", status="ok", cost_usd=1.5, case_id="CASE-24051"))
    db.flush()
    gw._client = SimpleNamespace(models=FakeModels({"gemini-3-flash": resp(GOOD)}))
    r = gw.generate(node="classify", prompt_version="t", contents=["x"], schema=Classification, case_id="CASE-24051", db=db)
    assert not r.ok and r.status == "budget"
    db.rollback()


def test_disabled_without_project(seeded, db):
    g = GeminiGateway()
    g.s = g.s.model_copy(update={"gcp_project": None})
    r = g.generate(node="classify", prompt_version="t", contents=["x"], schema=Classification, db=db)
    assert r.status == "disabled"
    db.rollback()


def test_slow_pro_model_falls_back_to_next_in_chain(gw, db):
    gw.s = gw.s.model_copy(update={"gemini_pro_models": "gemini-3.1-pro-preview,gemini-3.8-flash"})
    fm = FakeModels({"gemini-3.1-pro-preview": TimeoutError("Deadline exceeded"), "gemini-3.8-flash": resp(GOOD)})
    gw._client = SimpleNamespace(models=fm)
    r = gw.generate(node="draft_report", prompt_version="t", contents=["x"], schema=Classification, tier="pro", db=db)
    assert r.ok and r.model == "gemini-3.8-flash" and fm.seen == ["gemini-3.1-pro-preview", "gemini-3.8-flash"]
    db.rollback()


def test_parallel_calls_share_one_client(monkeypatch):
    """Parallel fact-check batches on a fresh instance must not each build (and close) their own client."""
    import sys
    import threading
    import time
    import types

    made = []

    class Client:
        def __init__(self, **kw):
            time.sleep(0.05)  # widen the race window
            made.append(self)

    fake = types.ModuleType("google.genai")
    fake.Client = Client
    import google

    monkeypatch.setitem(sys.modules, "google.genai", fake)
    monkeypatch.setattr(google, "genai", fake, raising=False)
    from app.ai.llm import GeminiGateway

    gw = GeminiGateway()
    got = []
    threads = [threading.Thread(target=lambda: got.append(gw.client())) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(made) == 1 and all(c is made[0] for c in got)


BUSY = RuntimeError("ClientError: 429 RESOURCE_EXHAUSTED. Resource exhausted. Please try again later.")


def test_busy_model_is_retried_once_then_answers(gw, db):
    """The live failure: Gemini 3.1 Pro (preview) returned 429 and the report fell back to facts only."""
    gw.s = gw.s.model_copy(update={"gemini_pro_models": "gemini-3.1-pro-preview,gemini-3.8-flash"})
    fm = FakeModels({"gemini-3.1-pro-preview": [BUSY, resp(GOOD)], "gemini-3.8-flash": resp(GOOD)})
    gw._client = SimpleNamespace(models=fm)
    r = gw.generate(node="draft_report", prompt_version="t", contents=["x"], schema=Classification, tier="pro", db=db)
    assert r.ok and r.model == "gemini-3.1-pro-preview" and fm.seen == ["gemini-3.1-pro-preview", "gemini-3.1-pro-preview"]
    assert [a["status"] for a in r.attempts] == ["error", "ok"]
    db.rollback()


def test_model_still_busy_falls_back_to_next_in_chain(gw, db):
    gw.s = gw.s.model_copy(update={"gemini_pro_models": "gemini-3.1-pro-preview,gemini-3.8-flash"})
    fm = FakeModels({"gemini-3.1-pro-preview": BUSY, "gemini-3.8-flash": resp(GOOD)})
    gw._client = SimpleNamespace(models=fm)
    r = gw.generate(node="draft_report", prompt_version="t", contents=["x"], schema=Classification, tier="pro", db=db)
    assert r.ok and r.model == "gemini-3.8-flash"
    assert fm.seen == ["gemini-3.1-pro-preview", "gemini-3.1-pro-preview", "gemini-3.8-flash"]
    db.rollback()


def test_busy_fast_model_also_falls_back(gw, db):
    fm = FakeModels({"gemini-3-flash": RuntimeError("ServerError: 503 UNAVAILABLE. The model is overloaded."), "gemini-2.5-flash": resp(GOOD)})
    gw._client = SimpleNamespace(models=fm)
    r = gw.generate(node="judge", prompt_version="t", contents=["x"], schema=Classification, db=db)
    assert r.ok and r.model == "gemini-2.5-flash"
    db.rollback()


def test_bad_request_is_not_retried(gw, db):
    fm = FakeModels({"gemini-3-flash": RuntimeError("ClientError: 400 INVALID_ARGUMENT"), "gemini-2.5-flash": resp(GOOD)})
    gw._client = SimpleNamespace(models=fm)
    r = gw.generate(node="classify", prompt_version="t", contents=["x"], schema=Classification, db=db)
    assert not r.ok and fm.seen == ["gemini-3-flash"]
    db.rollback()


def test_thinking_is_kept_short_and_matches_the_model_family(gw, db):
    """Gemini 3 thinks at length by default (80-95 s drafts); the gateway asks for a short think instead."""
    fm = FakeModels({"gemini-3-flash": resp(GOOD)})
    gw._client = SimpleNamespace(models=fm)
    gw.generate(node="judge", prompt_version="t", contents=["x"], schema=Classification, db=db)
    assert fm.configs[-1].thinking_config.thinking_level.value == "LOW"
    fm.behaviours["gemini-2.5-flash"] = resp(GOOD)
    gw.s = gw.s.model_copy(update={"gemini_fast_models": "gemini-2.5-flash"})
    gw.generate(node="judge", prompt_version="t", contents=["x"], schema=Classification, db=db, thinking="minimal")
    assert fm.configs[-1].thinking_config.thinking_budget == 0
    db.rollback()


def test_unsupported_thinking_setting_is_dropped_not_fatal(gw, db):
    fm = FakeModels({"gemini-3-flash": [RuntimeError("ClientError: 400 INVALID_ARGUMENT. thinking_level is not supported"), resp(GOOD)]})
    gw._client = SimpleNamespace(models=fm)
    r = gw.generate(node="judge", prompt_version="t", contents=["x"], schema=Classification, db=db)
    assert r.ok and fm.configs[0].thinking_config is not None and fm.configs[1].thinking_config is None
    db.rollback()


def test_server_deadline_moves_to_the_next_model(gw, db):
    fm = FakeModels({"gemini-3-flash": RuntimeError("ServerError: 504 DEADLINE_EXCEEDED. Deadline expired before operation could complete."),
                     "gemini-2.5-flash": resp(GOOD)})
    gw._client = SimpleNamespace(models=fm)
    r = gw.generate(node="judge", prompt_version="t", contents=["x"], schema=Classification, db=db)
    assert r.ok and r.model == "gemini-2.5-flash" and fm.seen == ["gemini-3-flash", "gemini-2.5-flash"]
    db.rollback()
