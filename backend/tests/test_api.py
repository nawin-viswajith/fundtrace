"""API: authentication, case-level authorisation, input validation, error shape, workflow guards."""
import io

import pytest
from fastapi.testclient import TestClient

PW = "Investigate@2026"


@pytest.fixture(scope="module")
def client(seeded):
    from app.main import create_app

    app = create_app()
    app.router.lifespan_context = _noop_lifespan  # DB is already initialised and seeded by the fixture
    with TestClient(app) as c:
        yield c


from contextlib import asynccontextmanager  # noqa: E402


@asynccontextmanager
async def _noop_lifespan(app):
    yield


def login(c, user):
    c.cookies.clear()
    r = c.post("/api/auth/login", json={"username": user, "password": PW})
    assert r.status_code == 200, r.text
    return r


def test_auth_required_everywhere(client):
    client.cookies.clear()
    for path in ("/api/cases", "/api/cases/CASE-24051", "/api/cases/CASE-24051/graph", "/api/ops/metrics", "/api/rules",
                 "/api/network/rings", "/api/reports/RPT-X"):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "unauthenticated"


def test_bad_login_and_lockout(client):
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": "inv.ravi", "password": "wrong"})
    assert r.status_code == 401 and "Invalid" in r.json()["error"]["message"]
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "lockme", "password": "x"})
    assert client.post("/api/auth/login", json={"username": "lockme", "password": "x"}).status_code == 429


def test_investigator_cannot_see_other_investigators_case(client):
    login(client, "inv.asha")
    ids = {c["id"] for c in client.get("/api/cases").json()["cases"]}
    assert "CASE-24031" not in ids  # owned by inv.ravi
    r = client.get("/api/cases/CASE-24031")
    assert r.status_code == 404  # same answer as a missing case: ids cannot be probed
    assert client.get("/api/cases/CASE-24031/graph").status_code == 404
    assert client.get("/api/cases/CASE-24031/evidence").status_code == 404
    login(client, "sup.meera")
    assert client.get("/api/cases/CASE-24031").status_code == 200


def test_graph_input_validation_and_bounded_expansion(client):
    login(client, "inv.asha")
    assert client.get("/api/cases/CASE-24051/graph?depth=0").status_code == 422
    assert client.get("/api/cases/CASE-24051/graph?direction=sideways").status_code == 422
    assert client.get("/api/cases/CASE-24051/graph?status=bogus").status_code == 422
    r = client.get("/api/cases/CASE-24051/graph?expand=ACC-NOT-ON-TRAIL")
    assert r.status_code == 422 and "trail" in r.json()["error"]["message"]
    g = client.get("/api/cases/CASE-24051/graph?depth=10&max_nodes=2000").json()["graph"]
    assert g["params"]["depth"] <= 5 and g["params"]["max_nodes"] <= 300  # clamped server-side


def test_case_context_has_separate_dimensions(client):
    login(client, "inv.asha")
    ctx = client.get("/api/cases/CASE-24051").json()
    for k in ("rules", "completeness", "consistency", "traceability", "policy", "computed_priority", "graph", "attribution"):
        assert k in ctx
    assert ctx["case"]["is_synthetic"] is True


def test_upload_validation(client):
    login(client, "inv.asha")
    r = client.post("/api/cases/CASE-24051/evidence", files={"file": ("x.exe", io.BytesIO(b"MZ\x90\x00binary"), "application/octet-stream")})
    assert r.status_code == 415
    r = client.post("/api/cases/CASE-24051/evidence", files={"file": ("note.txt", io.BytesIO(b"customer letter"), "text/plain")},
                    data={"checklist_key": "customer_evidence"})
    assert r.status_code == 200 and r.json()["analysis_status"] == "not_analysed"
    ev = r.json()["id"]
    f = client.get(f"/api/cases/CASE-24051/evidence/{ev}/file")
    assert f.status_code == 200 and f.content == b"customer letter"
    a = client.post(f"/api/cases/CASE-24051/evidence/{ev}/analyse").json()
    assert a["status"] == "not_analysed" and "Not analysed" in a["note"]  # LLM disabled in tests


def test_workflow_guards_and_audit_chain(client):
    login(client, "inv.asha")
    cid = "CASE-24033"  # owned by inv.asha, status investigating
    assert client.post(f"/api/cases/{cid}/actions", json={"type": "status", "to": "resolved"}).status_code == 422
    assert client.post(f"/api/cases/{cid}/actions", json={"type": "status", "to": "new"}).status_code == 409
    assert client.post(f"/api/cases/{cid}/actions", json={"type": "status", "to": "escalated", "reason": "x"}).status_code == 422
    assert client.post(f"/api/cases/{cid}/actions", json={"type": "note", "body": "Called customer, awaiting statement."}).status_code == 200
    assert client.post(f"/api/cases/{cid}/actions", json={"type": "status", "to": "ready_for_review"}).status_code == 200
    r = client.post(f"/api/cases/{cid}/actions", json={"type": "decision", "decision": "uphold_claim",
                                                       "rationale": "Merchant confirmed the cancellation was processed late."})
    assert r.status_code == 422 and "report" in r.json()["error"]["message"].lower()
    r = client.post(f"/api/cases/{cid}/actions", json={"type": "decision", "decision": "uphold_claim",
                                                       "rationale": "Merchant confirmed the cancellation was processed late.",
                                                       "override_reason": "Simple merchant case, no AI report needed"})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    # reopening needs a supervisor
    assert client.post(f"/api/cases/{cid}/actions", json={"type": "status", "to": "investigating"}).status_code == 403
    audit = client.get(f"/api/cases/{cid}/audit").json()
    assert audit["verification"]["valid"]
    actions = [e["action"] for e in audit["events"]]
    assert "note_added" in actions and "decision_recorded" in actions


def test_audit_tamper_is_detected(client, db):
    from app import audit as audit_mod
    from app import models as m

    ev = db.query(m.AuditEvent).filter(m.AuditEvent.case_id == "CASE-24051").order_by(m.AuditEvent.id).first()
    original = dict(ev.details)
    ev.details = {**original, "tampered": True}
    db.flush()
    assert audit_mod.verify(db, "CASE-24051")["valid"] is False
    db.rollback()


def test_hold_approval_requires_note_and_bound(client, db):
    from app import models as m

    login(client, "inv.asha")
    h = m.Hold(case_id="CASE-24051", account_id="ACC-100210", amount_minor=1_800_000, currency="INR", basis={}, status="recommended")
    db.add(h)
    db.commit()
    url = "/api/cases/CASE-24051/actions"
    assert client.post(url, json={"type": "hold", "hold_id": h.id, "decision": "request", "note": ""}).status_code == 422
    assert client.post(url, json={"type": "hold", "hold_id": h.id, "decision": "request", "note": "Golden hour",
                                  "amount_minor": 9_999_999}).status_code == 422
    r = client.post(url, json={"type": "hold", "hold_id": h.id, "decision": "request", "note": "Golden hour hold request"})
    assert r.status_code == 200 and r.json()["hold_status"] == "requested"
    assert client.post(url, json={"type": "hold", "hold_id": h.id, "decision": "decline", "note": "again"}).status_code == 409
    db.delete(db.get(m.Hold, h.id))
    db.commit()


def test_rules_edit_is_supervisor_only_and_validated(client):
    login(client, "inv.asha")
    assert client.put("/api/rules/R7", json={"params": {"max_age_days": 10}, "change_note": "tighten"}).status_code == 403
    login(client, "sup.meera")
    assert client.put("/api/rules/R7", json={"params": {"nope": 1}, "change_note": "bad param"}).status_code == 422
    assert client.put("/api/rules/R1", json={"params": {"min_share": 5}, "change_note": "out of range"}).status_code == 422
    r = client.put("/api/rules/R7", json={"params": {"max_age_days": 30}, "change_note": "confirm default"})
    assert r.status_code == 200 and r.json()["version"] >= 2


def test_ai_unavailable_paths_return_not_analysed(client):
    login(client, "inv.asha")
    assert client.post("/api/cases/CASE-24051/ask", json={"question": "Where did the funds go?"}).json()["status"] == "not_analysed"
    assert client.post("/api/cases/CASE-24051/classify").json()["status"] == "not_analysed"
    rep = client.post("/api/cases/CASE-24051/investigate").json()
    assert rep["status"] == "facts_only" and rep["claims_flagged"] == 0
    assert client.get(f"/api/reports/{rep['id']}").status_code == 200


def test_error_shape_never_leaks_internals(client):
    login(client, "inv.asha")
    r = client.post("/api/cases/CASE-24051/actions", json={"type": "teleport"})
    assert r.status_code == 422 and set(r.json()["error"]) >= {"code", "message"}
    r = client.post("/api/cases/CASE-24051/ask", json={"question": ""})
    assert r.status_code == 422 and r.json()["error"]["fields"] == ["question"]


def test_mule_ring_links_cases_through_shared_beneficiary(client):
    login(client, "sup.meera")
    rings = client.get("/api/network/rings").json()["rings"]
    assert rings, "the synthetic mule (S1/S3a/S3b) should surface as a ring"
    top = rings[0]
    assert {"CASE-24051", "CASE-24031", "CASE-24038"} <= set(top["cases"])
    login(client, "inv.asha")
    restricted = client.get("/api/network/rings").json()["rings"][0]["cases"]
    assert "restricted" in restricted  # CASE-24031 belongs to another investigator


def test_investigator_can_claim_unassigned_but_not_steal(client):
    login(client, "inv.asha")
    me = client.get("/api/auth/me").json()["user"]["id"]
    assert client.post("/api/cases/CASE-24047/actions", json={"type": "assign", "user_id": me}).status_code == 200
    login(client, "inv.ravi")
    assert client.get("/api/cases/CASE-24047").status_code == 404  # now owned by inv.asha


def test_evidence_deletion_request_approve_and_tombstone(client):
    login(client, "inv.asha")
    up = client.post("/api/cases/CASE-24051/evidence", files={"file": ("old.txt", io.BytesIO(b"old letter"), "text/plain")}).json()
    ev = up["id"]
    url = "/api/cases/CASE-24051/actions"
    assert client.post(url, json={"type": "evidence_deletion", "evidence_id": ev, "decision": "request", "note": "x"}).status_code == 422
    assert client.post(url, json={"type": "evidence_deletion", "evidence_id": ev, "decision": "request",
                                  "note": "Customer withdrew this document"}).status_code == 200
    assert client.post(url, json={"type": "evidence_deletion", "evidence_id": ev, "decision": "approve",
                                  "note": "Investigator cannot approve"}).status_code == 403
    login(client, "sup.meera")
    r = client.post(url, json={"type": "evidence_deletion", "evidence_id": ev, "decision": "approve", "note": "Approved: customer request"})
    assert r.status_code == 200 and r.json()["retention_status"] == "deleted"
    f = client.get(f"/api/cases/CASE-24051/evidence/{ev}/file")
    assert f.status_code == 410 and f.json()["error"]["code"] == "gone"
    item = next(e for e in client.get("/api/cases/CASE-24051/evidence").json()["evidence"] if e["id"] == ev)
    assert item["retention_status"] == "deleted" and item["sha256"] and item["extracted"] is None
    actions = [e["action"] for e in client.get("/api/cases/CASE-24051/audit").json()["events"]]
    assert "evidence_deletion_requested" in actions and "evidence_deleted" in actions


def test_retention_run_is_admin_only_and_dry_run_by_default(client):
    login(client, "sup.meera")
    assert client.post("/api/admin/retention/run").status_code == 403
    login(client, "admin")
    r = client.post("/api/admin/retention/run").json()
    assert r["dry_run"] is True and r["deleted"] == 0


def test_overview_search_and_outcomes(client):
    login(client, "inv.asha")
    ov = client.get("/api/overview").json()
    assert ov["counts"]["open"] >= 1 and "outcomes" in ov
    m_ = ov["outcomes"]["measurements"]
    assert m_["automated_claim_rejections"]["value"] == 0
    for k in ("median_investigation_hours", "findings_linked_to_sources", "evidence_completeness_at_decision"):
        assert k in m_ and m_[k]["status"] in ("ok", "not_enough_data")
    q = client.get("/api/cases").json()["cases"]
    assert all("age_hours" in c and "next_action" in c for c in q)
    hit = client.get("/api/search", params={"q": "24051"}).json()["results"]
    assert hit and hit[0]["id"] == "CASE-24051"
    # investigators never find other investigators' cases through search
    assert all(r["id"] != "CASE-24031" for r in client.get("/api/search", params={"q": "CASE-240"}).json()["results"])
    assert client.get("/api/search", params={"q": "x"}).status_code == 422
