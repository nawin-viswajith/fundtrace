"""AI pipeline: hallucination checks, retry with feedback, LLM-down fallback, evidence reconciliation."""
import json
import re

from sqlalchemy import select

from app import models as m
from app.ai import validator
from app.ai.investigator import run_investigation
from app.ai.llm import FakeGateway
from app.ai.schemas import SECTION_TITLES


def _case(db, seeded, sc="S1"):
    return db.get(m.DisputeCase, seeded["truth"][sc]["case"])


def _good_draft(root: str, payee: str, amount: str) -> dict:
    secs = []
    for key in SECTION_TITLES:
        secs.append({"key": key, "claims": [{"text": f"The disputed transfer {root} of {amount} went to {payee}.",
                                             "citations": [root], "basis": "verified"}]})
    return {"sections": secs, "recommended_actions": [{"action_type": "human_review", "target_id": root, "description": "Review",
                                                       "citations": [root]}]}


class Script:
    def __init__(self, root, payee, amount, ref, first_bad=True):
        self.root, self.payee, self.amount, self.ref = root, payee, amount, ref
        self.drafts = 0
        self.first_bad = first_bad

    def __call__(self, node, contents):
        if node == "explore":
            return {"calls": [{"tool": "linked_cases", "target_id": self.payee, "reason": "beneficiary in other disputes?"},
                              {"tool": "expand_account", "target_id": "ACC-NOT-REAL", "reason": "probe"}],
                    "done": False, "rationale": "check links"}
        if node == "analyse_evidence":
            return {"document_type": "payment receipt", "is_payment_record": True, "amount": "50,000.00", "currency": "INR",
                    "reference": self.ref, "date_text": None, "time_text": None, "payee": "Rahul K", "payer": None, "app_or_bank": "PayFast",
                    "tamper_indicators": [], "embedded_instructions_detected": False, "legibility": "good", "summary": "receipt"}
        if node == "draft_report":
            self.drafts += 1
            d = _good_draft(self.root, self.payee, self.amount)
            if self.first_bad and self.drafts == 1:
                d["sections"][1]["claims"].append({"text": "TXN-9999999 moved ₹99,999 and proves fraud.", "citations": ["TXN-9999999"],
                                                   "basis": "verified"})
            return d
        if node == "judge":
            text = contents[0]
            ids = sorted(set(re.findall(r'"claim_id": "(C\d+)"', text)))
            return {"verdicts": [{"claim_id": i, "verdict": "supported", "reason": "matches record"} for i in ids]}
        raise KeyError(node)


def test_validator_flags_invented_ids_wrong_amounts_and_banned_phrases():
    records = {"TXN-1": {"type": "transaction", "amount": "₹50,000", "time_utc": "01 Oct 2026 10:02 UTC"}}
    bad = {"sections": [{"key": "known_facts", "claims": [
        {"text": "TXN-1 moved ₹45,000 at 11:15.", "citations": ["TXN-1"], "basis": "verified"},
        {"text": "TXN-77 shows the payment.", "citations": ["TXN-77"], "basis": "verified"},
        {"text": "This proves the transfer was fraud and the customer is liable.", "citations": ["TXN-1"], "basis": "derived"},
        {"text": "The ₹50,000 was funded by the stolen money.", "citations": ["TXN-1"], "basis": "verified"},
    ]}], "recommended_actions": []}
    v = validator.validate(bad, records)
    codes = [{i["code"] for i in c["issues"]} for c in v["claims"]]
    assert "number_mismatch" in codes[0] and "time_mismatch" in codes[0]
    assert {"invalid_citation", "invented_id"} <= codes[1]
    assert "banned_phrase" in codes[2]
    assert "basis_upgrade" in codes[3]
    assert v["missing_sections"] and not v["passed"]


def test_llm_down_produces_facts_only_report_and_not_analysed_evidence(db, seeded):
    case = _case(db, seeded)
    rep = run_investigation(db, case, actor="inv.asha", gateway=FakeGateway(lambda n, c: {}, status="disabled"))
    assert rep.status == "facts_only" and rep.generator == "deterministic"
    assert rep.metrics["validation_passed"] and rep.claims_flagged == 0
    assert rep.confidence is None and rep.hallucination_rate is None  # no AI, so no AI confidence
    ev = db.scalars(select(m.EvidenceItem).where(m.EvidenceItem.case_id == case.id, m.EvidenceItem.retention_status != "deleted")).all()
    assert ev and all(e.analysis_status == "not_analysed" for e in ev)
    assert all("Not analysed" in (e.analysis_note or "") for e in ev)
    # case status is never changed by the AI
    assert db.get(m.DisputeCase, case.id).status == case.status
    db.rollback()


def test_hallucinated_draft_is_caught_retried_and_judged(db, seeded):
    case = _case(db, seeded)
    root = db.get(m.Transaction, case.disputed_txn_id)
    script = Script(root.id, root.credit_account_id, "₹50,000", root.reference)
    gw = FakeGateway(script)
    rep = run_investigation(db, case, actor="inv.asha", gateway=gw)
    assert script.drafts == 2, "validator feedback should trigger exactly one redraft"
    second_draft_prompt = [c for c in gw.calls if c["node"] == "draft_report"][1]["contents"]
    assert any("TXN-9999999" in str(x) for x in second_draft_prompt), "feedback must name the invented id"
    assert rep.status == "verified" and rep.claims_flagged == 0 and rep.hallucination_rate == 0
    assert rep.confidence == 1.0
    run = db.get(m.AIRun, rep.run_id)
    assert run.status == "awaiting_review" and run.snapshot_hash == rep.snapshot_hash
    tools = {t["tool"]: t["status"] for t in run.tool_log}
    assert tools["linked_cases"] == "ok" and tools["expand_account"] == "rejected"  # unknown id refused
    ev = db.scalars(select(m.EvidenceItem).where(m.EvidenceItem.case_id == case.id, m.EvidenceItem.retention_status != "deleted")).all()
    assert ev[0].analysis_status == "analysed"
    checks = {c["field"]: c["result"] for c in ev[0].reconciliation["checks"]}
    assert checks["amount"] == "matches" and checks["reference"] == "matches"
    holds = db.scalars(select(m.Hold).where(m.Hold.case_id == case.id)).all()
    assert holds and all(h.status == "recommended" for h in holds)
    calls = db.scalars(select(m.AICall).where(m.AICall.run_id == rep.run_id)).all()
    assert {c.node for c in calls} >= {"explore", "analyse_evidence", "draft_report", "judge"}
    assert rep.metrics["cost_usd"] > 0
    db.rollback()


def test_persistent_hallucination_is_kept_visible_not_hidden(db, seeded):
    case = _case(db, seeded, "S2")
    root = db.get(m.Transaction, case.disputed_txn_id)

    def always_bad(node, contents):
        s = Script(root.id, root.credit_account_id, "₹40,000", root.reference, first_bad=True)
        s.drafts = 0
        return s(node, contents)

    rep = run_investigation(db, case, actor="inv.asha", gateway=FakeGateway(always_bad))
    assert rep.status in ("partially_verified", "unverified")
    flagged = [c for s in rep.sections for c in s["claims"] if c["flagged"]]
    assert flagged and flagged[0]["hallucination"]
    db.rollback()


def test_evidence_contradiction_and_injection(db, seeded):
    case = _case(db, seeded, "S7")
    root = db.get(m.Transaction, case.disputed_txn_id)

    def resp(node, contents):
        if node == "analyse_evidence":
            return {"document_type": "payment receipt", "is_payment_record": True, "amount": "45,000.00", "currency": "INR",
                    "reference": "628977001234", "date_text": None, "time_text": None, "payee": None, "payer": None, "app_or_bank": None,
                    "tamper_indicators": [], "embedded_instructions_detected": True, "legibility": "good", "summary": "receipt"}
        return Script(root.id, root.credit_account_id, "₹50,000", root.reference, first_bad=False)(node, contents)

    run_investigation(db, case, actor="inv.asha", gateway=FakeGateway(resp))
    ev = db.scalars(select(m.EvidenceItem).where(m.EvidenceItem.case_id == case.id)).first()
    checks = {c["field"]: c["result"] for c in ev.reconciliation["checks"]}
    assert checks["amount"] == "contradicts" and checks["reference"] == "contradicts"
    assert ev.reconciliation["embedded_instructions_detected"]
    from app.services.investigation import build_context

    ctx = build_context(db, case)
    assert {r["rule_id"]: r["status"] for r in ctx["rules"]}["R9"] == "triggered"
    assert any(e["type"] == "contradicts" and e["provenance"] == "contradictory" for e in ctx["graph"]["edges"])
    db.rollback()


def test_untrusted_text_is_fenced_in_prompts(db, seeded):
    case = _case(db, seeded)
    root = db.get(m.Transaction, case.disputed_txn_id)
    gw = FakeGateway(Script(root.id, root.credit_account_id, "₹50,000", root.reference, first_bad=False))
    run_investigation(db, case, actor="inv.asha", gateway=gw)
    prompt = str([c for c in gw.calls if c["node"] == "draft_report"][0]["contents"])
    assert "<untrusted>I did not make this payment" in prompt
    assert all("Text inside <untrusted>" in (c["system"] or "") for c in gw.calls)
    db.rollback()


def test_classification_eval_macro_f1_with_fake_gemini(db, seeded):
    from app.eval.harness import evaluate_classification

    cases = {c.id: c.category for c in db.query(m.DisputeCase).all()}
    wrong = sorted(cases)[0]

    def resp(node, contents):
        text = str(contents)
        cid = next(c for c in cases if db.get(m.DisputeCase, c).allegation[:30] in text)
        cat = "merchant_dispute" if cid == wrong and cases[cid] != "merchant_dispute" else cases[cid]
        return {"category": cat, "rationale": "x", "english_translation": None, "detected_language": "en"}

    r = evaluate_classification(db, FakeGateway(resp))
    assert r["status"] == "ok" and r["classified"] == len(cases)
    assert r["accuracy"] == round((len(cases) - 1) / len(cases), 4)
    assert 0 < r["macro_f1"] < 1
    down = evaluate_classification(db, FakeGateway(lambda n, c: {}, status="disabled"))
    assert down["status"] == "not_analysed" and down["not_analysed"] == len(cases)
    db.rollback()
