"""Deterministic verifier and Gemini hypothesis flow: "Gemini proposes, the ledger proves"."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import models as m
from app.services import hypothesis_check as hc
from app.services.investigation import build_context


def _ledger(db, case_id: str) -> hc.Ledger:
    case = db.get(m.DisputeCase, case_id)
    ctx = build_context(db, case)
    return hc.Ledger(db, ctx)


@pytest.fixture()
def headline(db):
    return _ledger(db, "CASE-24051")


# ---- the claim language --------------------------------------------------------------------------

def test_parse_check_rejects_incomplete_values():
    check, problem = hc.parse_check({"kind": "flow_at_least", "from_account": "ACC-1"})
    assert check is None and problem is not None


def test_parse_check_accepts_each_kind():
    for raw in (
        {"kind": "flow_at_least", "from_account": "ACC-1", "to_account": "ACC-2", "amount_rupees": 100},
        {"kind": "still_in_account", "account": "ACC-1", "amount_rupees": 100},
        {"kind": "left_bank", "amount_rupees": 100},
        {"kind": "rapid_pass_through", "account": "ACC-1", "share_pct": 80, "within_minutes": 60},
        {"kind": "shared_device", "account_a": "ACC-1", "account_b": "ACC-2"},
        {"kind": "linked_disputes", "account": "ACC-1", "min_cases": 1},
        {"kind": "typology", "pattern": "fan_out"},
    ):
        check, problem = hc.parse_check(raw)
        assert check is not None and problem is None, raw


# ---- CASE-24051 headline numbers (₹50,000 -> Rahul, ₹30,000 -> Sunil, ₹20,000 -> other bank) -----

def test_flow_at_least_lower_bound_proven(headline):
    r = hc.run_check({"kind": "flow_at_least", "from_account": "ACC-100209", "to_account": "ACC-100210", "amount_rupees": 28800}, headline)
    assert r["verdict"] == hc.PROVEN
    assert r["amounts_minor"]["lower"] == 28800 * 100


def test_flow_at_least_within_upper_bound_possible(headline):
    r = hc.run_check({"kind": "flow_at_least", "from_account": "ACC-100209", "to_account": "ACC-100210", "amount_rupees": 30000}, headline)
    assert r["verdict"] == hc.POSSIBLE


def test_flow_at_least_above_upper_bound_refuted(headline):
    r = hc.run_check({"kind": "flow_at_least", "from_account": "ACC-100209", "to_account": "ACC-100210", "amount_rupees": 31000}, headline)
    assert r["verdict"] == hc.REFUTED


def test_fan_out_proven_on_headline_case(headline):
    r = hc.run_check({"kind": "typology", "pattern": "fan_out"}, headline)
    assert r["verdict"] == hc.PROVEN


def test_layering_chain_proven_on_headline_case(headline):
    r = hc.run_check({"kind": "typology", "pattern": "layering_chain"}, headline)
    assert r["verdict"] == hc.PROVEN


def test_still_in_account_uses_attribution_residual(headline):
    # Sunil's account forces at least ₹18,000 (the 'disputed money spent first' residual) to remain.
    r = hc.run_check({"kind": "still_in_account", "account": "ACC-100210", "amount_rupees": 18000}, headline)
    assert r["verdict"] == hc.PROVEN
    r2 = hc.run_check({"kind": "still_in_account", "account": "ACC-100210", "amount_rupees": 19001}, headline)
    assert r2["verdict"] == hc.REFUTED


def test_left_bank_matches_exit_bounds(headline):
    r = hc.run_check({"kind": "left_bank", "amount_rupees": 29800}, headline)
    assert r["verdict"] == hc.PROVEN


def test_linked_disputes_on_mule_account(headline):
    r = hc.run_check({"kind": "linked_disputes", "account": "ACC-100209", "min_cases": 1}, headline)
    assert r["verdict"] == hc.PROVEN
    assert r["amounts_minor"]["cases"] == 2


def test_round_trip_refuted_on_a_linear_trail(headline):
    r = hc.run_check({"kind": "typology", "pattern": "round_trip"}, headline)
    assert r["verdict"] == hc.REFUTED


def test_round_trip_proven_on_cycle_case(db):
    lg = _ledger(db, "CASE-24039")
    r = hc.run_check({"kind": "typology", "pattern": "round_trip"}, lg)
    assert r["verdict"] == hc.PROVEN


# ---- rejecting invented records -----------------------------------------------------------------

def test_invented_account_is_rejected(headline):
    h = hc.check_hypothesis(
        {"statement": "Money went to a made-up account.", "rationale": "x",
         "checks": [{"kind": "flow_at_least", "from_account": "ACC-999999", "to_account": "ACC-100210", "amount_rupees": 100}]},
        headline,
    )
    assert h["verdict"] == hc.INVENTED
    assert "ACC-999999" in h["invented_ids"]


def test_invented_id_mentioned_only_in_statement_is_also_caught(headline):
    h = hc.check_hypothesis(
        {"statement": "Funds went through TXN-NOTREAL on the way out.", "rationale": "x",
         "checks": [{"kind": "left_bank", "amount_rupees": 1000}]},
        headline,
    )
    assert h["verdict"] == hc.INVENTED
    assert "TXN-NOTREAL" in h["invented_ids"]


def test_hypothesis_takes_its_weakest_check(headline):
    h = hc.check_hypothesis(
        {"statement": "x", "rationale": "x",
         "checks": [
             {"kind": "flow_at_least", "from_account": "ACC-100209", "to_account": "ACC-100210", "amount_rupees": 28800},  # proven
             {"kind": "flow_at_least", "from_account": "ACC-100209", "to_account": "ACC-100210", "amount_rupees": 31000},  # refuted
         ]},
        headline,
    )
    assert h["verdict"] == hc.REFUTED


# ---- system (code-only) hypotheses, used when AI is unavailable ---------------------------------

def test_system_hypotheses_cover_headline_patterns(headline):
    hyps = hc.system_hypotheses(headline)
    typologies = {h["typology"] for h in hyps}
    assert "fan_out" in typologies
    assert all(h["source"] == "system" for h in hyps)
    assert len(hyps) <= 6


def test_counts_tally_verdicts(headline):
    hyps = [hc.check_hypothesis(h, headline) for h in hc.system_hypotheses(headline)]
    c = hc.counts(hyps)
    assert sum(c.values()) == len(hyps)


# ---- the AI (Gemini) proposer and "Ask the ledger" via the gateway ------------------------------

def test_propose_hypotheses_uses_fake_gateway(db):
    from app.ai import hypotheses as ai_hyp
    from app.ai.llm import FakeGateway

    case = db.get(m.DisputeCase, "CASE-24051")

    def responder(node, contents):
        from app.ai.schemas import HypothesisSet

        return HypothesisSet(hypotheses=[{
            "statement": "Some of the money may still be with Sunil.",
            "rationale": "Sunil's account shows an inflow with no matching outflow for the full amount.",
            "typology": "other",
            "record_ids": ["ACC-100210"],
            "checks": [{"kind": "still_in_account", "account": "ACC-100210", "amount_rupees": 18000}],
        }])

    gw = FakeGateway(responder)
    out = ai_hyp.run(db, case, user=db.scalar(select(m.User).where(m.User.username == "inv.asha")), gateway=gw)
    assert out["status"] == "ok"
    assert out["hypotheses"][0]["source"] == "ai"
    assert out["hypotheses"][0]["verdict"] == hc.PROVEN
    assert gw.calls and gw.calls[0]["node"] == "hypotheses"
    run = db.scalar(select(m.AIRun).where(m.AIRun.case_id == case.id, m.AIRun.kind == "hypotheses").order_by(m.AIRun.started_at.desc()))
    assert run is not None and run.status == "ok"


def test_propose_hypotheses_rejects_ai_invented_account(db):
    from app.ai import hypotheses as ai_hyp
    from app.ai.llm import FakeGateway

    case = db.get(m.DisputeCase, "CASE-24051")

    def responder(node, contents):
        from app.ai.schemas import HypothesisSet

        return HypothesisSet(hypotheses=[{
            "statement": "Money reached a made-up account.", "rationale": "x", "typology": "other",
            "record_ids": ["ACC-NOPE"],
            "checks": [{"kind": "flow_at_least", "from_account": "ACC-100209", "to_account": "ACC-NOPE", "amount_rupees": 100}],
        }])

    gw = FakeGateway(responder)
    out = ai_hyp.run(db, case, user=db.scalar(select(m.User).where(m.User.username == "inv.asha")), gateway=gw)
    assert out["hypotheses"][0]["verdict"] == hc.INVENTED


def test_propose_hypotheses_falls_back_to_system_when_ai_unavailable(db):
    from app.ai import hypotheses as ai_hyp
    from app.ai.llm import FakeGateway

    case = db.get(m.DisputeCase, "CASE-24051")
    gw = FakeGateway(lambda n, c: {}, status="disabled")
    out = ai_hyp.run(db, case, user=db.scalar(select(m.User).where(m.User.username == "inv.asha")), gateway=gw)
    assert out["status"] == "ai_unavailable"
    assert out["hypotheses"]
    assert all(h["source"] == "system" for h in out["hypotheses"])


def test_latest_hypotheses_persist_without_rerunning_ai(db):
    from app.ai import hypotheses as ai_hyp
    from app.ai.llm import FakeGateway

    case = db.get(m.DisputeCase, "CASE-24051")

    def responder(node, contents):
        from app.ai.schemas import HypothesisSet

        return HypothesisSet(hypotheses=[{
            "statement": "x", "rationale": "y", "typology": "fan_out", "record_ids": [],
            "checks": [{"kind": "typology", "pattern": "fan_out"}],
        }])

    gw = FakeGateway(responder)
    first = ai_hyp.run(db, case, user=db.scalar(select(m.User).where(m.User.username == "inv.asha")), gateway=gw)
    db.commit()
    latest = ai_hyp.latest(db, case)
    assert latest is not None
    assert latest["hypotheses"][0]["statement"] == first["hypotheses"][0]["statement"]


def test_ask_the_ledger_translates_and_answers(db):
    from app.ai import hypotheses as ai_hyp
    from app.ai.llm import FakeGateway

    case = db.get(m.DisputeCase, "CASE-24051")

    def responder(node, contents):
        from app.ai.schemas import LedgerQuestion

        return LedgerQuestion(checks=[{"kind": "flow_at_least", "from_account": "ACC-100209", "to_account": "ACC-100210", "amount_rupees": 25000}],
                              cannot_express=False, reason=None)

    gw = FakeGateway(responder)
    out = ai_hyp.ask_ledger(db, case, "Did at least 25,000 reach Sunil?",
                            user=db.scalar(select(m.User).where(m.User.username == "inv.asha")), gateway=gw)
    assert out["status"] == "ok"
    assert out["verdict"] == hc.PROVEN
    assert out["answer"].startswith("Yes.")


def test_ask_the_ledger_when_ai_unavailable(db):
    from app.ai import hypotheses as ai_hyp
    from app.ai.llm import FakeGateway

    case = db.get(m.DisputeCase, "CASE-24051")
    gw = FakeGateway(lambda n, c: {}, status="disabled")
    out = ai_hyp.ask_ledger(db, case, "Is any of the money still at this bank?",
                            user=db.scalar(select(m.User).where(m.User.username == "inv.asha")), gateway=gw)
    assert out["status"] == "ai_unavailable"


# ---- API routes (auth, case-access, fallback behaviour via the real HTTP stack) -------------------

from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

PW = "Investigate@2026"


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture(scope="module")
def client(seeded):
    from app.main import create_app

    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    with TestClient(app) as c:
        yield c


def _login(c, user):
    c.cookies.clear()
    r = c.post("/api/auth/login", json={"username": user, "password": PW})
    assert r.status_code == 200, r.text


def test_hypotheses_routes_require_auth(client):
    client.cookies.clear()
    assert client.get("/api/cases/CASE-24051/hypotheses").status_code == 401
    assert client.post("/api/cases/CASE-24051/hypotheses").status_code == 401
    assert client.post("/api/cases/CASE-24051/ask-ledger", json={"question": "Did money reach Sunil?"}).status_code == 401


def test_hypotheses_route_respects_case_access(client):
    _login(client, "inv.asha")  # CASE-24031 is owned by inv.ravi
    assert client.get("/api/cases/CASE-24031/hypotheses").status_code == 404
    assert client.post("/api/cases/CASE-24031/hypotheses").status_code == 404


def test_run_and_get_hypotheses_without_ai_falls_back_to_system(client):
    # LLM_ENABLED=false in the test environment, so the route exercises the "AI unavailable" fallback.
    _login(client, "inv.asha")
    r = client.post("/api/cases/CASE-24051/hypotheses")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ai_unavailable"
    assert body["hypotheses"] and all(h["source"] == "system" for h in body["hypotheses"])

    latest = client.get("/api/cases/CASE-24051/hypotheses")
    assert latest.status_code == 200
    assert latest.json()["hypotheses"][0]["statement"] == body["hypotheses"][0]["statement"]


def test_ask_ledger_route_without_ai(client):
    _login(client, "inv.asha")
    r = client.post("/api/cases/CASE-24051/ask-ledger", json={"question": "Is any of the money still at this bank?"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ai_unavailable"


def test_ask_ledger_route_validates_question_length(client):
    _login(client, "inv.asha")
    assert client.post("/api/cases/CASE-24051/ask-ledger", json={"question": "a"}).status_code == 422
