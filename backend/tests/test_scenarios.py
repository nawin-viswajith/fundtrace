"""Integration: every synthetic scenario matches its ground truth through the real DB pipeline."""
from app import models as m
from app.eval.harness import evaluate_deterministic
from app.services.investigation import build_context


def test_all_scenarios_match_ground_truth(db, seeded):
    r = evaluate_deterministic(db, seeded["truth"])
    failures = [(d["scenario"], c) for d in r["details"] for c in d["checks"] if not c["passed"]]
    assert not failures, failures
    assert r["rule_precision"] == 1.0 and r["rule_recall"] == 1.0


def test_headline_case_context_is_complete_and_traceable(db, seeded):
    case = db.get(m.DisputeCase, seeded["truth"]["S1"]["case"])
    ctx = build_context(db, case)
    assert ctx["computed_priority"]["priority"] == "P1"
    node_ids = {n["id"] for n in ctx["graph"]["nodes"]}
    for tid in seeded["truth"]["S1"]["trail"]:
        assert tid in node_ids
    # every confirmed edge traces to a real transaction record
    txn_ids = {n["id"] for n in ctx["graph"]["nodes"] if n["type"] == "transaction"}
    for e in ctx["graph"]["edges"]:
        if e["provenance"] == "confirmed":
            assert set(e["source_ids"]) & txn_ids
    # dimensions stay separate
    for k in ("completeness", "consistency", "traceability", "policy", "rules_summary"):
        assert k in ctx
    assert "score" not in ctx


def test_missing_evidence_is_not_a_negative_finding(db, seeded):
    case = db.get(m.DisputeCase, seeded["truth"]["S9"]["case"])
    ctx = build_context(db, case)
    ne = {r["rule_id"] for r in ctx["rules"] if r["status"] == "not_evaluable"}
    assert {"R4", "R5"} <= ne
    for r in ctx["rules"]:
        if r["status"] == "not_evaluable":
            assert "not a negative finding" in r["limitations"][0]


def test_source_provenance_survives_normalisation(db, seeded):
    case = db.get(m.DisputeCase, seeded["truth"]["S1"]["case"])
    t = db.get(m.Transaction, case.disputed_txn_id)
    assert {s["system"] for s in t.sources} == {"core", "upi_switch"}
