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

    def generate_content(self, model, contents, config):
        self.seen.append(model)
        b = self.behaviours[model]
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
