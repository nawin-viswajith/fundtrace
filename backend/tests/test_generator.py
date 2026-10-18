"""Demo data generator: complete, consistent synthetic disputes on demand, AI statements within a budget."""
import re
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models as m
from app.ai.llm import FakeGateway
from app.services.generator import GenerateIn, generate

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


def login(c, user):
    c.cookies.clear()
    assert c.post("/api/auth/login", json={"username": user, "password": PW}).status_code == 200


def test_only_supervisors_and_admins_can_generate_and_inputs_are_checked(client):
    login(client, "inv.asha")
    assert client.post("/api/admin/generate-data", json={"count": 1}).status_code == 403
    login(client, "sup.meera")
    for body in ({"count": 0}, {"count": 51}, {"amount_min": 90000, "amount_max": 1000}, {"categories": ["lottery"]},
                 {"status_mode": "lost"}, {"assign": "nobody.here"}, {"ai_budget_usd": 5}):
        assert client.post("/api/admin/generate-data", json=body).status_code == 422, body


def test_generated_cases_are_complete_and_flow_through_the_bank_view(client, db):
    login(client, "sup.meera")
    r = client.post("/api/admin/generate-data", json={"count": 8, "status_mode": "mixed", "amount_min": 20000, "amount_max": 60000,
                                                      "days_back": 2, "assign": "spread", "with_trail": True, "with_evidence": True})
    assert r.status_code == 200, r.text
    out = r.json()
    ids = [c["case_id"] for c in out["created"]]
    assert len(ids) == 8 and out["statements"]["template"] == 8 and out["statements"]["ai_cost_usd"] == 0
    queue = {c["id"] for c in client.get("/api/cases").json()["cases"]}
    assert set(ids) <= queue
    db.expire_all()
    for cid in ids:
        case = db.get(m.DisputeCase, cid)
        t = case.disputed_txn
        assert case.is_synthetic and case.scenario == "GEN" and 2_000_000 <= t.amount_minor <= 6_000_000
        assert db.get(m.Account, t.debit_account_id).customer_id == case.customer_id  # the payer is the disputing customer
        assert case.priority in ("P1", "P2", "P3", "P4") and case.due_at is not None
        if case.status != "new":
            assert case.owner_id is not None
        if case.status == "resolved":
            assert case.decision and case.decided_at
        if case.status == "awaiting_evidence":
            assert db.scalars(select(m.EvidenceRequest).where(m.EvidenceRequest.case_id == cid)).all()
        if case.category in ("unauthorised_transfer", "account_takeover", "app_scam"):
            assert db.scalars(select(m.EvidenceItem).where(m.EvidenceItem.case_id == cid)).all()  # a receipt to read
            ctx = client.get(f"/api/cases/{cid}").json()
            assert not [w for w in ctx["attribution"]["warnings"] if "exceeds computed balance" in w]  # the payer could afford it
            assert ctx["graph"]["stats"]["transactions"] >= 2  # a money trail beyond the disputed payment
    events = [e for e in db.scalars(select(m.AuditEvent).where(m.AuditEvent.action == "demo_data_generated")).all()]
    assert events and events[-1].details["count"] == 8


def test_fraud_trails_leave_money_behind_so_holds_are_suggested(client, db):
    login(client, "sup.meera")
    out = client.post("/api/admin/generate-data", json={"count": 4, "categories": ["app_scam"], "status_mode": "new", "assign": "nobody",
                                                        "amount_min": 50000, "amount_max": 90000}).json()
    db.expire_all()
    holds = db.scalars(select(m.Hold).where(m.Hold.case_id.in_([c["case_id"] for c in out["created"]]))).all()
    assert holds and all(h.status == "recommended" for h in holds)
    assert all(c["status"] == "new" for c in out["created"])


def test_ai_statements_stay_within_budget_and_are_checked(db, seeded):
    sup = db.scalar(select(m.User).where(m.User.username == "sup.meera"))
    calls = {"n": 0}

    def responder(node, contents):
        calls["n"] += 1
        amount = re.search(r"Amount: (₹[\d,]+)", contents[0]).group(1)
        if calls["n"] == 2:  # one statement states the wrong amount: it must be rejected
            return {"statement": "Someone took ₹1,23,456 from my account without asking me."}
        return {"statement": f"I never made this payment of {amount}. My phone was with me all along."}

    p = GenerateIn(count=5, statements="ai", ai_budget_usd=0.0025, status_mode="new", assign="nobody")
    out = generate(db, sup, p, gateway=FakeGateway(responder))  # each fake call costs $0.001
    st = out["statements"]
    assert calls["n"] == 3 and st["ai"] == 2 and st["ai_rejected"] == 1 and st["template"] == 3
    assert st["ai_cost_usd"] == pytest.approx(0.003)
    texts = [db.get(m.DisputeCase, c["case_id"]).allegation for c in out["created"]]
    assert sum("My phone was with me all along" in t for t in texts) == 2 and not any("1,23,456" in t for t in texts)
    db.rollback()


def test_generated_data_never_touches_existing_cases(db, seeded):
    """Generating must only add to the world: seeded cases keep exactly the same assessment."""
    from app.services.investigation import build_context

    def snapshot():
        out = {}
        for c in db.scalars(select(m.DisputeCase).where(m.DisputeCase.scenario.is_not(None), m.DisputeCase.scenario != "GEN")).all():
            ctx = build_context(db, c, now=m.utcnow().replace(second=0, microsecond=0))
            out[c.id] = ({r["rule_id"]: r["status"] for r in ctx["rules"]}, ctx["attribution"]["buckets"])
        return out

    before = snapshot()
    sup = db.scalar(select(m.User).where(m.User.username == "sup.meera"))
    generate(db, sup, GenerateIn(count=12, status_mode="new", assign="nobody"))
    assert snapshot() == before
    db.rollback()
