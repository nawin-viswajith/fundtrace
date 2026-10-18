"""Customer portal: isolation from staff APIs, form and chat intake with fixed options, and the bank-side mapping."""
import io
from contextlib import asynccontextmanager

import pytest
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


def login(c, user):
    c.cookies.clear()
    r = c.post("/api/auth/login", json={"username": user, "password": PW})
    assert r.status_code == 200, r.text
    return r.json()["user"]


def test_customer_logins_are_kept_out_of_the_bank_view(client):
    u = login(client, "cust.kiran")
    assert u["role"] == "customer"
    for path in ("/api/cases", "/api/cases/CASE-24051", "/api/overview", "/api/ops/metrics", "/api/rules", "/api/network/rings", "/api/meta"):
        assert client.get(path).status_code == 403, path
    assert client.post("/api/cases/CASE-24051/actions", json={"type": "note", "body": "hello there"}).status_code == 403
    assert client.get("/api/auth/me").status_code == 200  # own sign-in endpoints still work
    login(client, "inv.asha")
    assert client.get("/api/portal/me").status_code == 403  # and staff can't use the portal
    assert {c["username"] for c in client.get("/api/auth/config").json()["demo_customers"]} == {"cust.priya", "cust.kiran", "cust.kabir"}


def test_customer_sees_only_own_accounts_and_disputes(client):
    login(client, "cust.priya")
    me = client.get("/api/portal/me").json()
    assert me["customer_id"] == "CUST-1075" and me["accounts"] and len(me["reasons"]) == 6
    assert set(me["options"]["noticed"]) == {"today", "yesterday", "2_7_days", "over_week"}
    own = {a["id"] for a in me["accounts"]}
    txns = client.get("/api/portal/transactions").json()["transactions"]
    assert txns and all(t["from_account"] in own for t in txns)
    mine = client.get("/api/portal/disputes").json()["disputes"]
    assert [d["case_id"] for d in mine] == ["CASE-24051"]
    view = client.get("/api/portal/disputes/CASE-24051").json()
    assert view["status"] in ("Received", "Being investigated", "We need something from you", "Final review", "With a senior team", "Decided")
    assert "rules" not in view and "graph" not in view and "notes" not in view  # nothing internal
    login(client, "cust.kiran")
    assert client.get("/api/portal/disputes/CASE-24051").status_code == 404  # another customer's dispute
    assert client.get("/api/portal/disputes").json()["disputes"] == []


def _form(txn_id, **over):
    body = {"txn_id": txn_id, "reason": "scam", "description": "Someone called saying they were from my bank and I paid them.",
            "otp_shared": "no", "noticed": "yesterday", "cyber_complaint_ref": "31810250012345", "contact_preference": "sms",
            "declaration": True}
    body.update(over)
    return body


def test_form_dispute_validates_fixed_options_and_lands_in_the_bank_queue(client):
    login(client, "cust.kiran")
    txn = client.get("/api/portal/transactions").json()["transactions"][0]
    bad = [({"reason": "something_else"}, 422), ({"otp_shared": None}, 422), ({"noticed": "last tuesday"}, 422),
           ({"contact_preference": "pigeon"}, 422), ({"description": "too short"}, 422), ({"declaration": False}, 422),
           ({"cyber_complaint_ref": "<script>"}, 422), ({"txn_id": "TXN-NOT-MINE"}, 404)]
    for over, code in bad:
        assert client.post("/api/portal/disputes", json={**_form(txn["id"]), **over}).status_code == code, over
    r = client.post("/api/portal/disputes", json=_form(txn["id"], description="I never got the item. OTP is 482913 they said, sorry."))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["case_id"].startswith("CASE-") and d["status"] == "Received" and d["deadlines"]
    assert "482913" not in d["description"] and d["masked"]  # an OTP typed by the customer is hidden
    assert client.post("/api/portal/disputes", json=_form(txn["id"])).status_code == 409  # same payment twice

    login(client, "sup.meera")
    queue = {c["id"]: c for c in client.get("/api/cases").json()["cases"]}
    assert d["case_id"] in queue and queue[d["case_id"]]["status"] == "new"
    ctx = client.get(f"/api/cases/{d['case_id']}").json()
    assert ctx["case"]["category"] == "app_scam" and ctx["case"]["category_source"] == "customer"
    assert ctx["case"]["channel"] == "portal_form" and ctx["case"]["customer_id"] == "CUST-1002"
    assert ctx["case"]["disputed_txn_id"] == txn["id"] and ctx["case"]["intake"]["cyber_complaint_ref"] == "31810250012345"
    events = [e["action"] for e in client.get(f"/api/cases/{d['case_id']}/audit").json()["events"]]
    assert events[0] == "case_created"

    # the bank asks the customer for something; the customer sees it and uploads; the decision reaches them in plain words
    client.post(f"/api/cases/{d['case_id']}/actions", json={"type": "request_evidence", "checklist_key": "customer_evidence",
                                                             "requested_from": "customer"})
    login(client, "cust.kiran")
    view = client.get(f"/api/portal/disputes/{d['case_id']}").json()
    assert [r["checklist_key"] for r in view["requests"]] == ["customer_evidence"]
    up = client.post(f"/api/portal/disputes/{d['case_id']}/evidence", data={"checklist_key": "customer_evidence"},
                     files={"file": ("receipt.txt", io.BytesIO(b"Paid Rs 500 to seller, order 123"), "text/plain")})
    assert up.status_code == 200 and up.json()["requests"] == [] and up.json()["files"][0]["filename"] == "receipt.txt"
    login(client, "sup.meera")
    client.post(f"/api/cases/{d['case_id']}/actions", json={"type": "status", "to": "investigating"})
    client.post(f"/api/cases/{d['case_id']}/actions", json={"type": "status", "to": "ready_for_review"})
    r = client.post(f"/api/cases/{d['case_id']}/actions", json={"type": "decision", "decision": "decline_claim",
                                                                "rationale": "Internal reasoning that names other accounts.",
                                                                "override_reason": "no report needed for this test"})
    assert r.status_code == 200, r.text
    login(client, "cust.kiran")
    view = client.get(f"/api/portal/disputes/{d['case_id']}").json()
    assert view["status"] == "Decided" and "not accepted" in view["decision"]
    assert "Internal reasoning" not in str(view)  # staff rationale never reaches the customer
    assert any("You raised this dispute" in t["text"] for t in view["timeline"])


def test_guided_chat_uses_fixed_options_and_files_the_same_dispute(client):
    login(client, "cust.kabir")
    r = client.post("/api/portal/chat", json={}).json()
    assert r["step"] == "payment" and r["payments"] and r["messages"][0].startswith("Hello Kabir")
    st = r["state"]
    r = client.post("/api/portal/chat", json={"state": st, "text": "I want my money back"}).json()
    assert r["step"] == "payment" and "choose one of the options" in r["messages"][0]  # free text is not an answer here
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "more"}).json()
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "newer"}).json()
    txn = r["payments"][0]["id"]
    assert client.post("/api/portal/chat", json={"state": r["state"], "choice": "txn:TXN-NOT-MINE"}).status_code == 404
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": f"txn:{txn}"}).json()
    assert r["step"] == "reason" and len(r["options"]) == 6
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "reason:unauthorised"}).json()
    assert r["step"] == "otp"
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "otp:no"}).json()
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "noticed:today"}).json()
    assert r["step"] == "cyber"
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "cyber:yes"}).json()
    assert r["step"] == "cyber_ref" and r["input"]["kind"] == "complaint_ref"
    r = client.post("/api/portal/chat", json={"state": r["state"], "text": "1930-ACK-77881"}).json()
    assert r["step"] == "description"
    r = client.post("/api/portal/chat", json={"state": r["state"], "text": "short"}).json()
    assert r["step"] == "description" and "at least 20" in r["messages"][0]
    r = client.post("/api/portal/chat", json={"state": r["state"], "text": "Money left my account at night. My card 4111 1111 1111 1111 was with me."}).json()
    assert r["masked"] and "4111" not in r["state"]["description"] and r["step"] == "contact"
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "contact:email"}).json()
    assert r["ready"] and r["summary"]["reason"] == "I didn't make or allow this payment" and r["summary"]["cyber_complaint"] == "1930-ACK-77881"
    # changing the reason to a non-fraud one drops the fraud-only questions
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "change:reason"}).json()
    assert r["step"] == "reason"
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "reason:charged_wrong"}).json()
    assert r["ready"] and r["summary"]["otp_shared"] is None and r["summary"]["cyber_complaint"] is None
    st = r["state"]
    body = {"txn_id": st["txn_id"], "reason": st["reason"], "description": st["description"], "otp_shared": st.get("otp_shared"),
            "noticed": st["noticed"], "cyber_complaint_ref": st.get("cyber_complaint_ref"), "contact_preference": st["contact_preference"],
            "declaration": True, "channel": "portal_chat"}
    d = client.post("/api/portal/disputes", json=body).json()
    assert d["case_id"].startswith("CASE-") and d["channel"] == "portal_chat"
    r = client.post("/api/portal/chat", json={}).json()
    assert txn not in [p["id"] for p in r["payments"]]  # a disputed payment is no longer offered
    login(client, "sup.meera")
    ctx = client.get(f"/api/cases/{d['case_id']}").json()
    assert ctx["case"]["category"] == "processing_error" and ctx["case"]["intake"]["otp_shared"] is None


def test_customer_answers_reach_the_ai_snapshot_as_untrusted_text(db):
    from sqlalchemy import select

    from app import models as m
    from app.ai.snapshot import build_snapshot
    from app.services.investigation import build_context

    case = db.scalars(select(m.DisputeCase).where(m.DisputeCase.channel == "portal_form")).first()
    snap = build_snapshot(build_context(db, case))
    answers = snap["records"][case.id]["customer_answers"]
    assert answers.startswith("<untrusted>") and "31810250012345" in answers


# ---------------------------------------------------------------------------- "tell us in your own words" (free-text intake)

def test_story_too_short_falls_back_to_step_by_step(client):
    login(client, "cust.kiran")
    r = client.post("/api/portal/chat/story", json={"story": "help"}).json()
    assert r["step"] == "payment" and "a little more" in " ".join(r["messages"]).lower()


def test_story_pre_fills_and_requires_confirmation(client, monkeypatch):
    from app.ai import customer_assistant as ca
    from app.ai.llm import FakeGateway

    login(client, "cust.kiran")
    txns = client.get("/api/portal/transactions").json()["transactions"]
    txn = next(t for t in txns if not t["dispute_case_id"])

    def responder(node, contents):
        return {"reason": "scam", "otp_shared": "no", "noticed": "today", "contact_preference": None,
                "amount": txn["amount_minor"] / 100, "payee_name": txn["paid_to"], "payment_date": txn["occurred_at"][:10]}

    monkeypatch.setattr("app.ai.customer_assistant.get_gateway", lambda: FakeGateway(responder))
    r = client.post("/api/portal/chat/story",
                    json={"story": "Someone called pretending to be from the bank and tricked me into paying. I did not share any OTP."}).json()
    assert r["state"]["description"].startswith("Someone called")
    assert r["step"] == "confirm_payment"
    assert r["payments"][0]["id"] == txn["id"]
    # confirm the payment
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "confirmyes:payment"}).json()
    assert r["state"]["txn_id"] == txn["id"]
    assert r["step"] == "confirm_reason"
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "confirmyes:reason"}).json()
    assert r["state"]["reason"] == "scam"
    assert r["step"] == "confirm_otp_shared"
    # decline the OTP suggestion: it must not be auto-accepted, and the real otp question is asked once the
    # other suggestions are settled
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "confirmno:otp_shared"}).json()
    assert "otp_shared" not in r["state"] and r["step"] == "confirm_noticed"
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "confirmyes:noticed"}).json()
    assert r["state"]["noticed"] == "today"
    assert r["step"] == "otp"  # the suggestion was declined, so the real question is still asked
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "otp:no"}).json()
    assert r["step"] == "cyber"  # the normal flow continues after all suggestions are settled
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "cyber:not_yet"}).json()
    assert r["step"] == "contact"  # description was already filled from the story
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "contact:sms"}).json()
    assert r["ready"] and r["summary"]["reason"] == "I was tricked into making this payment"


def test_story_ai_unavailable_continues_step_by_step(client, monkeypatch):
    from app.ai.llm import FakeGateway

    login(client, "cust.kiran")
    monkeypatch.setattr("app.ai.customer_assistant.get_gateway", lambda: FakeGateway(lambda n, c: {}, status="disabled"))
    r = client.post("/api/portal/chat/story", json={"story": "Someone tricked me into paying them over the phone yesterday."}).json()
    assert "step by step" in r["messages"][-2].lower() or "step by step" in " ".join(r["messages"]).lower()
    assert r["step"] == "payment"


def test_story_declining_the_payment_match_falls_back_to_the_list(client, monkeypatch):
    from app.ai.llm import FakeGateway

    login(client, "cust.kiran")
    txns = client.get("/api/portal/transactions").json()["transactions"]
    txn = next(t for t in txns if not t["dispute_case_id"])

    def responder(node, contents):
        return {"reason": None, "otp_shared": None, "noticed": None, "contact_preference": None,
                "amount": txn["amount_minor"] / 100, "payee_name": txn["paid_to"], "payment_date": None}

    monkeypatch.setattr("app.ai.customer_assistant.get_gateway", lambda: FakeGateway(responder))
    r = client.post("/api/portal/chat/story", json={"story": "I paid someone and now I think it was a mistake, please help."}).json()
    assert r["step"] == "confirm_payment"
    r = client.post("/api/portal/chat", json={"state": r["state"], "choice": "confirmno:payment"}).json()
    assert r["step"] == "payment" and r["payments"]


# ---------------------------------------------------------------------------- "Ask Demo Bank" API isolation

def test_customer_can_call_help_endpoints_staff_cannot(client, monkeypatch):
    from app.ai.llm import FakeGateway

    login(client, "cust.kiran")
    assert client.get("/api/portal/help").status_code == 200
    assert client.get("/api/portal/safety-check").status_code == 200

    def responder(node, contents):
        return {"intent": "faq", "answer": "You can raise a dispute from your recent payments.",
                "cited_article_ids": ["DSP-HOW"], "cited_case_ids": [], "actions": []}

    monkeypatch.setattr("app.ai.customer_assistant.get_gateway", lambda: FakeGateway(responder))
    r = client.post("/api/portal/help/ask", json={"message": "How do I raise a dispute?"})
    assert r.status_code == 200 and r.json()["status"] == "ok"

    login(client, "inv.asha")
    assert client.get("/api/portal/help").status_code == 403
    assert client.get("/api/portal/safety-check").status_code == 403
    assert client.post("/api/portal/help/ask", json={"message": "hello"}).status_code == 403
    assert client.post("/api/portal/chat/story", json={"story": "x" * 25}).status_code == 403
