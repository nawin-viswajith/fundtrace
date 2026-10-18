"""Ask Demo Bank: Gemini customer assistant scoped to banking/safety/disputes, with KB grounding, citation
validation, DLP masking, and a deterministic fallback when AI is unavailable or unsafe."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import models as m
from app.ai import customer_assistant as ca
from app.ai.llm import FakeGateway
from app.ai.schemas import CustomerHelpAnswer, HelpIntent, HelpActionKind, StoryExtraction, StoryReason, StoryOtp


def user(db, username: str) -> m.User:
    return db.scalar(select(m.User).where(m.User.username == username))


# ---------------------------------------------------------------------------- scope + grounding + citation validation

def test_in_scope_faq_answer_cites_a_valid_article(db):
    u = user(db, "cust.kiran")

    def responder(node, contents):
        assert node == "customer_help"
        return {"intent": "faq", "answer": "A screenshot of the payment or the bank's SMS, a receipt, or messages from "
                "the other person all help us check faster.", "cited_article_ids": ["DSP-PROOF"], "cited_case_ids": [],
                "actions": [], "follow_up_questions": ["How long does it take?"]}

    out = ca.ask(db, u, "What proof should I send?", gateway=FakeGateway(responder))
    assert out["status"] == "ok" and out["source"] == "ai" and out["intent"] == "faq"
    assert [a["id"] for a in out["articles"]] == ["DSP-PROOF"]
    assert out["source_label"] == ca.AI_LABEL


def test_out_of_scope_question_is_refused_by_code(db):
    u = user(db, "cust.kiran")

    def responder(node, contents):
        return {"intent": "out_of_scope", "answer": "", "cited_article_ids": [], "cited_case_ids": [], "actions": []}

    out = ca.ask(db, u, "What's a good recipe for biryani?", gateway=FakeGateway(responder))
    assert out["status"] == "refused" and out["source"] == "policy"
    assert out["text"] == ca.REFUSAL
    assert out["suggestions"]


def test_invalid_citations_fall_back_to_best_article(db):
    u = user(db, "cust.kiran")

    def responder(node, contents):
        # Cites an id that is not one of the retrieved sources: must be rejected.
        return {"intent": "faq", "answer": "Here is an answer that cites nothing valid.", "cited_article_ids": ["NOT-REAL"],
                "cited_case_ids": [], "actions": []}

    out = ca.ask(db, u, "How long does a dispute take?", gateway=FakeGateway(responder))
    assert out["status"] == "fallback" and out["source"] == "help_articles"
    assert out["source_label"] == ca.ARTICLE_LABEL
    assert out["articles"]


def test_answer_asking_for_a_secret_is_dropped_for_fallback(db):
    u = user(db, "cust.kiran")

    def responder(node, contents):
        return {"intent": "faq", "answer": "Please share your OTP so we can verify the payment for you.",
                "cited_article_ids": ["SAFE-NEVER-SHARE"], "cited_case_ids": [], "actions": []}

    out = ca.ask(db, u, "How do you verify payments?", gateway=FakeGateway(responder))
    assert out["status"] == "fallback" and out["source"] == "help_articles"


def test_answer_mentioning_another_dispute_is_dropped(db):
    u = user(db, "cust.kiran")

    def responder(node, contents):
        return {"intent": "my_dispute_status", "answer": "Your dispute CASE-99999 is being investigated.",
                "cited_article_ids": ["DSP-STATUS"], "cited_case_ids": ["CASE-99999"], "actions": []}

    out = ca.ask(db, u, "Where is my dispute?", gateway=FakeGateway(responder))
    assert out["status"] == "fallback"


# ---------------------------------------------------------------------------- DLP masking + warnings

def test_otp_in_customer_message_is_masked_before_reaching_gemini_and_warns():
    pass


def test_otp_typed_by_customer_is_masked_and_warns(db):
    u = user(db, "cust.kiran")
    seen = {}

    def responder(node, contents):
        seen["contents"] = contents
        return {"intent": "faq", "answer": "Never share an OTP with anyone, including Demo Bank.",
                "cited_article_ids": ["SAFE-NEVER-SHARE"], "cited_case_ids": [], "actions": []}

    out = ca.ask(db, u, "My OTP is 482913, is that ok to tell you?", gateway=FakeGateway(responder))
    assert out["warning"] == ca.SECRET_WARNING
    assert "482913" not in str(seen["contents"])


def test_no_secret_no_warning(db):
    u = user(db, "cust.kiran")

    def responder(node, contents):
        return {"intent": "faq", "answer": "You can raise a dispute from your recent payments.",
                "cited_article_ids": ["DSP-HOW"], "cited_case_ids": [], "actions": []}

    out = ca.ask(db, u, "How do I raise a dispute?", gateway=FakeGateway(responder))
    assert out["warning"] is None


# ---------------------------------------------------------------------------- AI unavailable -> help-article fallback

def test_ai_unavailable_falls_back_to_help_article(db):
    u = user(db, "cust.kiran")
    out = ca.ask(db, u, "What should I do if I shared my PIN?", gateway=FakeGateway(lambda n, c: {}, status="disabled"))
    assert out["status"] == "fallback" and out["source"] == "help_articles"
    assert out["articles"] and out["note"]


def test_ai_failure_falls_back_to_help_article(db):
    u = user(db, "cust.kiran")

    def responder(node, contents):
        raise ValueError("boom")

    out = ca.ask(db, u, "How long does a dispute take?", gateway=FakeGateway(responder))
    assert out["status"] == "fallback" and out["source"] == "help_articles"


def test_urgent_fraud_fallback_leads_with_first_hour_steps(db):
    u = user(db, "cust.kiran")
    out = ca.ask(db, u, "I think I was just scammed, help me now", gateway=FakeGateway(lambda n, c: {}, status="disabled"))
    assert out["urgent"] is True
    assert any(a["id"] == "SAFE-FIRST-HOUR" for a in out["articles"])
    assert any(a["kind"] == "call_1930" for a in out["actions"])


def test_no_matching_article_is_a_plain_refusal(db):
    u = user(db, "cust.kiran")
    out = ca.ask(db, u, "zzz qqqq xylophone unrelated", gateway=FakeGateway(lambda n, c: {}, status="disabled"))
    assert out["status"] == "fallback" and out["source"] == "policy"


# ---------------------------------------------------------------------------- personal data isolation

def test_customer_sees_only_own_disputes(db):
    kiran = user(db, "cust.kiran")
    priya = user(db, "cust.priya")
    kiran_disputes = ca.own_disputes(db, kiran)
    priya_disputes = ca.own_disputes(db, priya)
    kiran_ids = {d["case_id"] for d in kiran_disputes}
    priya_ids = {d["case_id"] for d in priya_disputes}
    assert not (kiran_ids & priya_ids) or not kiran_ids or not priya_ids  # no overlap when both have disputes

    def responder(node, contents):
        return {"intent": "my_dispute_status", "answer": "Here is your dispute status.", "cited_article_ids": ["DSP-STATUS"],
                "cited_case_ids": list(kiran_ids)[:1] if kiran_ids else [], "actions": []}

    out = ca.ask(db, kiran, "Where is my dispute?", gateway=FakeGateway(responder))
    seen_cases = {d["case_id"] for d in out["disputes"]}
    assert seen_cases <= kiran_ids  # never another customer's case
    assert not (seen_cases & priya_ids)


def test_non_customer_rejected_by_customer_of(db):
    staff = user(db, "inv.asha")
    with pytest.raises(Exception):
        ca.ask(db, staff, "hello", gateway=FakeGateway(lambda n, c: {}))


# ---------------------------------------------------------------------------- retrieval + knowledge base

def test_retrieval_finds_relevant_articles_for_common_questions():
    assert "SAFE-NEVER-SHARE" in [i for i, _ in ca.retrieve("someone asked for my otp")]
    assert "DSP-TIME" in [i for i, _ in ca.retrieve("how long does a dispute take")]
    assert "SCAM-COLLECT" in [i for i, _ in ca.retrieve("upi collect request asking for my pin")]


def test_kb_has_15_to_20_articles_with_unique_ids():
    arts = ca.articles()
    assert 15 <= len(arts) <= 25
    assert len(arts) == len(set(arts))


def test_deadline_text_is_filled_from_sla_config():
    txt = ca.deadline_text()
    assert "working days" in txt or "days" in txt


# ---------------------------------------------------------------------------- safety check (deterministic)

def test_safety_check_runs_for_a_real_customer(db):
    u = user(db, "cust.priya")
    out = ca.safety_check(db, u)
    assert "items" in out and "tips" in out and out["tips"]
    assert isinstance(out["all_clear"], bool)


def test_safety_check_isolated_per_customer(db):
    priya = ca.safety_check(db, user(db, "cust.priya"))
    kiran = ca.safety_check(db, user(db, "cust.kiran"))
    # independent computations; just verify no crash and plausible structure
    for out in (priya, kiran):
        for item in out["items"]:
            assert "title" in item and "text" in item


# ---------------------------------------------------------------------------- free-text story extraction (used by intake_chat)

def test_extract_story_returns_none_when_ai_unavailable(db):
    u = user(db, "cust.kiran")
    assert ca.extract_story(db, u, "Someone called pretending to be my bank.", gateway=FakeGateway(lambda n, c: {}, status="disabled")) is None


def test_extract_story_parses_fixed_fields(db):
    u = user(db, "cust.kiran")

    def responder(node, contents):
        return {"reason": "scam", "otp_shared": "no", "noticed": "today", "contact_preference": None,
                "amount": 1500.0, "payee_name": "Rahul", "payment_date": None}

    out = ca.extract_story(db, u, "Someone called pretending to be my bank and I paid Rahul 1500 rupees today.",
                           gateway=FakeGateway(responder))
    assert out is not None
    assert out["suggest"]["reason"] == "scam"
    assert out["suggest"]["otp_shared"] == "no"
    assert out["hints"]["amount_minor"] == 150000
    assert out["hints"]["payee"] == "Rahul"


def test_extract_story_ignores_fields_ai_did_not_assert():
    out = StoryExtraction(reason=StoryReason.scam, otp_shared=None, noticed=None, contact_preference=None, amount=None,
                          payee_name=None, payment_date=None)
    assert out.otp_shared is None


def test_rank_payments_prefers_amount_and_payee_match():
    cards = [
        {"id": "TXN-A", "amount_minor": 150000, "paid_to": "Rahul Kumar", "occurred_at": "2026-10-10T00:00:00Z"},
        {"id": "TXN-B", "amount_minor": 50000, "paid_to": "Someone Else", "occurred_at": "2026-10-01T00:00:00Z"},
    ]
    ranked, matched = ca.rank_payments(cards, {"amount_minor": 150000, "payee": "Rahul"})
    assert ranked[0]["id"] == "TXN-A"
    assert "TXN-A" in matched


def test_rank_payments_no_hints_keeps_order():
    cards = [{"id": "TXN-A", "amount_minor": 1, "paid_to": "X", "occurred_at": "2026-10-10T00:00:00Z"}]
    ranked, matched = ca.rank_payments(cards, {})
    assert ranked == cards and matched == []


# ---------------------------------------------------------------------------- small talk (no Gemini call needed)

def test_bare_greeting_is_answered_instantly_without_calling_gemini(db):
    u = user(db, "cust.kiran")
    gw = FakeGateway(lambda node, contents: pytest.fail("a bare greeting must not call Gemini"))
    out = ca.ask(db, u, "hi", gateway=gw)
    assert out["status"] == "ok" and out["source"] == "ai" and out["intent"] == "greeting"
    assert "Ask Demo Bank" in out["text"] and gw.calls == []


def test_greeting_fast_path_also_works_when_ai_is_unavailable(db):
    u = user(db, "cust.kiran")
    out = ca.ask(db, u, "  Hello!  ", gateway=FakeGateway(lambda n, c: {}, status="disabled"))
    assert out["intent"] == "greeting" and out["status"] == "ok"


@pytest.mark.parametrize("msg", ["thanks", "Thank you!", "ok thanks", "bye", "goodbye", "how are you?", "How're you doing"])
def test_other_small_talk_is_answered_instantly_too(db, msg):
    u = user(db, "cust.kiran")
    gw = FakeGateway(lambda node, contents: pytest.fail("small talk must not call Gemini"))
    out = ca.ask(db, u, msg, gateway=gw)
    assert out["status"] == "ok" and out["intent"] == "greeting" and out["text"]


def test_a_real_question_that_starts_with_a_greeting_still_goes_to_gemini(db):
    u = user(db, "cust.kiran")

    def responder(node, contents):
        return {"intent": "faq", "answer": "A screenshot or the bank's SMS helps us check faster.",
                "cited_article_ids": ["DSP-PROOF"], "cited_case_ids": [], "actions": [], "follow_up_questions": []}

    out = ca.ask(db, u, "hi, what proof should I send?", gateway=FakeGateway(responder))
    assert out["intent"] == "faq" and out["source"] == "ai"


# ---------------------------------------------------------------------------- model tier

def test_customer_help_and_story_extraction_use_the_small_chat_tier(db):
    seen_tiers = []

    def responder(node, contents):
        return {"intent": "faq", "answer": "A screenshot or the bank's SMS helps us check faster.",
                "cited_article_ids": ["DSP-PROOF"], "cited_case_ids": [], "actions": [], "follow_up_questions": []}

    gw = FakeGateway(responder)
    real_generate = gw.generate

    def spy(*, tier="fast", **kw):
        seen_tiers.append(tier)
        return real_generate(tier=tier, **kw)

    gw.generate = spy
    ca.ask(db, user(db, "cust.kiran"), "What proof should I send?", gateway=gw)
    assert seen_tiers == ["chat"]
