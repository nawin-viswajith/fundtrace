"""Case assistant, report drafts, batched fact-check and judge-only re-runs."""
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models as m
from app.ai.assistant import parse_command
from app.ai.investigator import JUDGE_BATCH, rejudge_report, run_investigation
from app.ai.llm import FakeGateway, set_gateway
from app.services.report_drafts import section_from_text
from tests.test_investigator import Script

PW = "Investigate@2026"
CASE = "CASE-24033"  # ordinary subscription dispute: not used by the investigator tests


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


@pytest.fixture()
def gateway():
    yield
    set_gateway(None)


def login(c, user="sup.meera"):
    c.cookies.clear()
    assert c.post("/api/auth/login", json={"username": user, "password": PW}).status_code == 200


# ---------------------------------------------------------------------------- fact-check in batches, re-run alone

def test_judge_runs_in_batches_and_a_failed_batch_can_be_rerun_alone(db, seeded):
    case = db.get(m.DisputeCase, seeded["truth"]["S6"]["case"])
    root = db.get(m.Transaction, case.disputed_txn_id)
    script = Script(root.id, root.credit_account_id, f"₹{root.amount_minor // 100:,}", root.reference, first_bad=False)

    def flaky(node, contents):
        if node == "judge" and '"claim_id": "C01"' in contents[0]:
            raise ValueError("simulated timeout")  # the first batch fails; the others answer
        return script(node, contents)

    gw = FakeGateway(flaky)
    rep = run_investigation(db, case, actor="inv.asha", gateway=gw)
    judge_calls = [c for c in gw.calls if c["node"] == "judge"]
    assert rep.claims_total > JUDGE_BATCH and len(judge_calls) == -(-rep.claims_total // JUDGE_BATCH)
    claims = [c for s in rep.sections for c in s["claims"]]
    unjudged = [c for c in claims if c["verdict"] == "unjudged"]
    assert len(unjudged) == JUDGE_BATCH and all("timed out" in c["verdict_reason"] or "unreadable" in c["verdict_reason"] for c in unjudged)
    assert rep.metrics["judge_status"] == "partial" and rep.status == "partially_verified" and 0 < rep.confidence < 1
    run = db.get(m.AIRun, rep.run_id)
    assert len([c for c in db.scalars(select(m.AICall).where(m.AICall.run_id == run.id, m.AICall.node == "judge"))]) == len(judge_calls)

    good = FakeGateway(script)
    out = rejudge_report(db, rep, "inv.asha", "investigator", gateway=good)
    rejudge_calls = [c for c in good.calls if c["node"] == "judge"]
    assert out["ok"] and out["judged"] == JUDGE_BATCH and len(rejudge_calls) == 1  # only the unjudged claims are sent
    assert rep.status == "verified" and rep.confidence == 1.0 and rep.metrics["judge_status"] == "ok"
    assert rep.metrics["judge_runs"][-1]["judged"] == JUDGE_BATCH
    again = rejudge_report(db, rep, "inv.asha", "investigator", gateway=good)
    assert again["judged"] == 0 and "already" in again["message"]
    db.rollback()


# ---------------------------------------------------------------------------- assistant commands and drafts

def test_command_parsing_understands_plain_requests():
    assert parse_command("please clear the limitations section") == {"op": "clear_section", "section_key": "limitations"}
    assert parse_command("Get rid of the next steps") == {"op": "clear_section", "section_key": "next_actions"}
    assert parse_command("bring back risk indicators") == {"op": "restore_section", "section_key": "risk_indicators"}
    assert parse_command("remove c07 and C12") == {"op": "remove_claims", "claim_ids": ["C07", "C12"]}
    assert parse_command("remove that please") == {"op": "unclear"}
    assert parse_command("which accounts still hold the money?") is None
    assert section_from_text("the evidence that contradicts the claim") == "contradicting_evidence"


def test_assistant_edits_a_draft_that_a_person_saves(client):
    login(client)
    rep = client.post(f"/api/cases/{CASE}/investigate").json()  # LLM disabled in tests: facts-only report
    before = rep["claims_total"]
    lim = next(s for s in rep["sections"] if s["key"] == "limitations")
    assert lim["claims"], "the facts-only report has a limitations section"

    r = client.post(f"/api/cases/{CASE}/assistant", json={"message": "Please clear the limitations section"}).json()
    assert r["action"]["kind"] == "clear_section" and r["navigate"] == {"tab": "report", "section": "limitations"}
    assert "Nothing is saved yet" in r["text"]
    d = client.get(f"/api/reports/{rep['id']}/draft").json()["draft"]
    assert d["claims_after"] == before - len(lim["claims"]) and d["changes"][0]["via"] == "assistant"
    assert client.get(f"/api/reports/{rep['id']}").json()["claims_total"] == before  # the saved report is unchanged

    r = client.post(f"/api/cases/{CASE}/assistant", json={"message": "undo, bring back limitations"}).json()
    assert r["action"]["kind"] == "restore_section"
    first = next(s for s in rep["sections"] if s["claims"])["claims"][0]["id"]
    r = client.post(f"/api/cases/{CASE}/assistant", json={"message": f"remove {first}"}).json()
    assert r["action"]["claim_ids"] == [first]
    r = client.post(f"/api/reports/{rep['id']}/draft/ops", json={"op": "clear_section", "section_key": "no_such"})
    assert r.status_code == 422

    saved = client.post(f"/api/reports/{rep['id']}/draft/save").json()
    assert saved["version"] == rep["version"] + 1 and saved["claims_total"] == before - 1 and saved["review_status"] == "pending"
    assert saved["metrics"]["edited_from"]["report_id"] == rep["id"] and len(saved["metrics"]["edits"]) == 3
    assert client.get(f"/api/reports/{rep['id']}/draft").json()["draft"] is None
    old = client.post(f"/api/reports/{rep['id']}/draft/ops", json={"op": "clear_section", "section_key": "limitations"})
    assert old.status_code == 409  # only the latest version can be edited
    client.post(f"/api/reports/{saved['id']}/draft/ops", json={"op": "clear_section", "section_key": "limitations"})
    assert client.post(f"/api/reports/{saved['id']}/draft/discard").json()["ok"]
    assert client.post(f"/api/reports/{saved['id']}/draft/save").status_code == 409
    events = [e["action"] for e in client.get(f"/api/cases/{CASE}/audit").json()["events"]]
    assert {"report_draft_edited", "report_draft_saved", "report_draft_discarded", "assistant_message"} <= set(events)
    assert client.post(f"/api/reports/{saved['id']}/judge").status_code == 409  # facts-only: nothing to fact-check


def test_assistant_answers_and_ignores_edits_the_user_did_not_ask_for(client, gateway):
    login(client)
    r = client.post(f"/api/cases/{CASE}/assistant", json={"message": "Who received the money?"}).json()
    assert r["status"] == "not_analysed" and "isn't available" in r["text"]  # no AI configured in tests

    case_root = client.get(f"/api/cases/{CASE}").json()["disputed_transaction"]["id"]

    def responder(node, contents):
        assert "USER MESSAGE" in contents[0]
        return {"claims": [{"text": f"The disputed payment is {case_root}.", "citations": [case_root], "basis": "verified"}],
                "insufficient_data": False, "follow_up_questions": ["What evidence is missing?"],
                "action": {"kind": "clear_section", "section_key": "risk_indicators", "claim_ids": []}}

    set_gateway(FakeGateway(responder))
    r = client.post(f"/api/cases/{CASE}/assistant", json={"message": "Who received the money?",
                                                          "history": [{"role": "user", "text": "hi"}]}).json()
    assert r["status"] == "ok" and r["claims"][0]["citations"] == [case_root] and r["follow_up_questions"]
    assert r.get("ignored_action") == "clear_section" and "action" not in r  # no edit words in the user's message

    r = client.post(f"/api/cases/{CASE}/assistant", json={"message": "remove that part you just mentioned"}).json()
    assert r["action"]["kind"] == "clear_section" and r["action"]["section_key"] == "risk_indicators"
    rep = client.get(f"/api/cases/{CASE}/reports").json()["reports"][0]
    client.post(f"/api/reports/{rep['id']}/draft/discard")


def test_a_timed_out_batch_is_split_and_retried_once(db, seeded):
    from app.ai.investigator import judge_claims
    from app.ai.llm import LLMResult

    claims = [{"id": f"C{i:02d}", "text": f"claim {i}", "basis": "verified", "citations": []} for i in range(1, 9)]

    class SlowOnBigBatches(FakeGateway):
        def generate(self, **kw):
            n = kw["contents"][0].count('"claim_id"')
            if n > 4:  # the full batch of 8 is "too slow"; halves of 4 answer
                self.calls.append({"node": "judge", "contents": kw["contents"]})
                return LLMResult(ok=False, status="timeout", model="fake", error="504 DEADLINE_EXCEEDED")
            return super().generate(**kw)

    import re

    gw = SlowOnBigBatches(lambda node, contents: {"verdicts": [{"claim_id": i, "verdict": "supported", "reason": "ok"}
                                                               for i in re.findall(r'"claim_id": "(C\d+)"', contents[0])]})
    verdicts, status, detail = judge_claims(db, gw, "CASE-24051", None, claims, {"records": {}})
    assert status == "ok" and len(verdicts) == 8 and detail["split_after_timeout"] == 1 and len(gw.calls) == 3
    db.rollback()
