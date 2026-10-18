"""Quality measurements: reviewer agreement with the AI fact-check, and rule false-positive burden."""
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models as m
from app.services import quality_metrics as qm
from app.services.rules import CATALOGUE

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


def _report(rid: str, claims: list[tuple[str, str, str | None]], status: str = "partial", case_id: str = "CASE-T",
            version: int = 1) -> m.Report:
    """claims: [(claim_id, verdict, investigator mark or None)]."""
    sections = [{"key": "findings", "title": "Findings",
                 "claims": [{"id": cid, "text": f"claim {cid}", "verdict": v, "citations": ["TXN-1"]} for cid, v, _ in claims]}]
    marks = {cid: mark for cid, _, mark in claims if mark}
    return m.Report(id=rid, case_id=case_id, run_id="RUN-T", version=version, status="verified", generator="test-model",
                    sections=sections, snapshot_hash="x" * 64, review_status=status,
                    review={"claims": marks, "note": ""} if status != "pending" else None)


def _hand_example() -> list[m.Report]:
    # 2x2: accept&supported a=6, accept&not b=1, reject&supported c=2, reject&not d=3 (n=12)
    r1 = [("c1", "supported", "accept"), ("c2", "supported", "accept"), ("c3", "partial", "accept"), ("c4", "supported", "accept"),
          ("c5", "unsupported", "accept"), ("c6", "supported", "reject"), ("c7", "unsupported", "reject"),
          ("c8", "unjudged", "accept"), ("c9", "system_generated", "accept"), ("c10", "supported", None)]
    r2 = [("d1", "supported", "accept"), ("d2", "partial", "accept"), ("d3", "partial", "reject"), ("d4", "contradicted", "reject"),
          ("d5", "unsupported", "reject"), ("d6", "unjudged", "reject")]
    pending = [("p1", "supported", "reject"), ("p2", "unsupported", "accept")]  # not reviewed: ignored
    return [_report("RPT-A", r1, case_id="CASE-A"), _report("RPT-B", r2, "accepted", case_id="CASE-B", version=2),
            _report("RPT-P", pending, "pending")]


# ---------------------------------------------------------------------------- agreement math

def test_kappa_and_agreement_on_a_hand_computed_example():
    out = qm.agreement(_hand_example())
    assert out["status"] == "ok"
    assert out["table"] == {"accept": {"supported": 6, "not_supported": 1}, "reject": {"supported": 2, "not_supported": 3}}
    assert out["claims_compared"] == 12 and out["agreed"] == 9
    assert out["agreement_rate"] == 0.75
    # po = 9/12; pe = (7/12)(8/12) + (5/12)(4/12) = 76/144; kappa = (108-76)/(144-76) = 32/68 = 8/17
    assert out["kappa"] == pytest.approx(8 / 17, abs=1e-4)
    assert out["kappa_label"] == "moderate"
    # unjudged and code-written claims are excluded and counted separately; unmarked claims are not compared
    assert out["excluded"]["unjudged"] == 2 and out["excluded"]["system_generated"] == 1
    assert out["claims_not_marked"] == 1
    assert out["reports"] == 2  # the pending report is ignored
    rows = {r["report_id"]: r for r in out["per_report"]}
    assert set(rows) == {"RPT-A", "RPT-B"}
    assert (rows["RPT-A"]["compared"], rows["RPT-A"]["agreed"], rows["RPT-A"]["excluded"]) == (7, 5, 2)
    assert rows["RPT-A"]["agreement"] == pytest.approx(5 / 7, abs=1e-4)
    assert (rows["RPT-B"]["case_id"], rows["RPT-B"]["version"], rows["RPT-B"]["compared"], rows["RPT-B"]["agreed"]) == ("CASE-B", 2, 5, 4)


def test_kappa_edge_cases():
    assert qm.kappa(5, 0, 0, 0) is None  # one answer only on both sides: chance explains everything
    assert qm.kappa(0, 0, 0, 0) is None
    assert qm.kappa(0, 5, 5, 0) == -1.0
    assert qm.kappa_label(-1.0) == "less than chance"
    assert qm.kappa(4, 0, 0, 4) == 1.0 and qm.kappa_label(1.0) == "almost perfect"
    # all accepted, AI split: agreement rate is meaningful, kappa is not
    out = qm.agreement([_report("RPT-K", [(f"k{i}", "supported" if i < 8 else "unsupported", "accept") for i in range(12)])])
    assert out["agreement_rate"] == pytest.approx(8 / 12, abs=1e-4)
    assert out["kappa"] == 0.0


def test_small_samples_say_not_enough_data():
    claims = [(f"s{i}", "supported", "accept") for i in range(qm.MIN_CLAIMS_COMPARED - 1)] + [("s-u", "unjudged", "accept")]
    out = qm.agreement([_report("RPT-S", claims)])
    assert out["status"] == "not_enough_data" and out["n"] == qm.MIN_CLAIMS_COMPARED - 1
    assert out["agreement_rate"] is None and out["kappa"] is None
    # per-report share is withheld below its own minimum; the counts are still shown
    small = qm.agreement([_report("RPT-T", [("t1", "supported", "accept"), ("t2", "unsupported", "reject")])])
    assert small["per_report"][0]["agreement"] is None and small["per_report"][0]["agreed"] == 2


def test_agreement_reads_saved_reviews_from_the_database(db):
    from app.services.workflow import review_report

    before = qm.compute_agreement(db)
    case = db.scalars(select(m.DisputeCase).order_by(m.DisputeCase.id)).unique().first()
    sup = db.scalar(select(m.User).where(m.User.username == "sup.meera"))
    rpt = _report("RPT-QM-DB", [("q1", "supported", None), ("q2", "unsupported", None), ("q3", "partial", None),
                                ("q4", "unjudged", None)], status="pending", case_id=case.id, version=99)
    db.add(rpt)
    db.flush()
    review_report(db, rpt, sup, {"status": "partial", "claims": {"q1": "accept", "q2": "accept", "q3": "accept", "q4": "reject"}})
    db.flush()
    after = qm.compute_agreement(db)
    assert after["claims_compared"] - before["claims_compared"] == 3
    assert after["agreed"] - before["agreed"] == 2
    assert after["excluded"]["unjudged"] - before["excluded"]["unjudged"] == 1
    assert after["table"]["accept"]["not_supported"] - before["table"]["accept"]["not_supported"] == 1
    row = next(r for r in after["per_report"] if r["report_id"] == "RPT-QM-DB")
    assert (row["case_id"], row["version"], row["compared"], row["agreed"]) == (case.id, 99, 3, 2)
    assert row["agreement"] == pytest.approx(2 / 3, abs=1e-4)


# ---------------------------------------------------------------------------- rule burden

def test_burden_counts_upheld_declined_and_not_evaluable():
    r1, r2, r3 = (rd.rule_id for rd in CATALOGUE[:3])
    decided = [
        ("decline_claim", {r1: "triggered", r2: "triggered", r3: "not_evaluable"}),
        ("decline_claim", {r1: "triggered", r2: "not_triggered", r3: "not_evaluable"}),
        ("decline_claim", {r1: "triggered", r2: "not_triggered"}),
        ("uphold_claim", {r1: "triggered", r2: "triggered"}),
        ("partial", {r1: "triggered", r2: "not_triggered"}),
        ("decline_claim", {r1: "not_triggered", r2: "not_triggered", r3: "not_evaluable"}),
    ]
    out = qm.burden(decided, open_triggered=[0, 2, 4, 1])
    assert len(out["rules"]) == len(CATALOGUE)  # every rule in the live catalogue, however many there are
    rows = {r["rule_id"]: r for r in out["rules"]}
    a = rows[r1]
    assert (a["evaluated"], a["triggered"], a["upheld"], a["declined"], a["not_evaluable"]) == (6, 5, 2, 3, 0)
    assert a["status"] == "ok" and a["declined_share"] == 0.6
    b = rows[r2]
    assert (b["triggered"], b["upheld"], b["declined"]) == (2, 1, 1)
    assert b["status"] == "not_enough_data" and b["declined_share"] is None and b["n"] == 2
    c = rows[r3]
    assert (c["evaluated"], c["triggered"], c["not_evaluable"], c["declined_share"]) == (3, 0, 3, None)
    # sorted: rules with a declined share first, then by how often they were found
    assert out["rules"][0]["rule_id"] == r1 and out["rules"][1]["rule_id"] == r2
    assert out["review_burden"]["value"] == 1.75 and out["review_burden"]["n"] == 4
    assert qm.burden([], [])["review_burden"]["status"] == "not_enough_data"


def test_rule_burden_uses_stored_flags_for_a_known_set_of_decided_cases(db):
    rule = CATALOGUE[0].rule_id
    other = CATALOGUE[1].rule_id
    flagged = set(db.scalars(select(m.RiskFlag.case_id)).all())  # cases another test has already investigated
    open_cases = [c for c in db.scalars(select(m.DisputeCase).order_by(m.DisputeCase.id)).unique().all()
                  if c.status not in ("resolved", "escalated")]
    live = next(c for c in reversed(open_cases) if c.id not in flagged)  # decided with no stored check: evaluated now
    open_cases.remove(live)
    assert len(open_cases) >= 6
    before = qm.compute_rule_burden(db)
    decisions = ["decline_claim", "decline_claim", "decline_claim", "decline_claim", "uphold_claim", "partial"]
    later = m.utcnow() + timedelta(days=1)  # newer than any evaluation another test may have saved
    for i, (c, dec) in enumerate(zip(open_cases, decisions)):
        c.status, c.decision, c.decided_at = "resolved", dec, m.utcnow()
        c.decision_rationale = "Decided in the quality-metrics test."
        for rid, st in ((rule, "triggered"), (other, "not_evaluable" if i < 2 else "not_triggered")):
            db.add(m.RiskFlag(id=f"FLAG-QM-{i}-{rid}", case_id=c.id, evaluation_id=f"EVAL-QM-{i}", rule_id=rid, rule_version=1,
                              name=rid, severity="high", status=st, evaluated_at=later))
    live.status, live.decision, live.decided_at = "resolved", "decline_claim", m.utcnow()
    db.flush()

    after = qm.compute_rule_burden(db)
    b, a = {r["rule_id"]: r for r in before["rules"]}, {r["rule_id"]: r for r in after["rules"]}
    assert a[rule]["triggered"] - b[rule]["triggered"] >= 6  # 6 stored, plus the live case if it triggers
    assert a[rule]["upheld"] - b[rule]["upheld"] == 2
    assert a[rule]["declined"] - b[rule]["declined"] in (4, 5)
    assert a[rule]["status"] == "ok" and a[rule]["declined_share"] == pytest.approx(a[rule]["declined"] / a[rule]["triggered"], abs=1e-4)
    assert a[other]["not_evaluable"] - b[other]["not_evaluable"] >= 2
    assert after["decided_cases"] - before["decided_cases"] == 7
    assert after["sources"]["decided"]["stored"] - before["sources"]["decided"]["stored"] == 6
    assert after["sources"]["decided"]["evaluated_now"] - before["sources"]["decided"]["evaluated_now"] == 1
    assert after["open_cases"] == before["open_cases"] - 7
    assert after["synthetic_cases"] >= 7
    assert "does not prove" in " ".join(after["caveats"])
    assert "synthetic demo data" in after["demo_note"]


# ---------------------------------------------------------------------------- API

def test_quality_endpoint_is_for_supervisors_and_admins(client):
    client.cookies.clear()
    assert client.get("/api/ops/quality").status_code == 401
    login(client, "inv.asha")
    assert client.get("/api/ops/quality").status_code == 403
    for user in ("sup.meera", "admin"):
        login(client, user)
        r = client.get("/api/ops/quality")
        assert r.status_code == 200, r.text
        body = r.json()
        ra, rb = body["reviewer_agreement"], body["rule_burden"]
        assert ra["status"] in ("ok", "not_enough_data") and "table" in ra and "per_report" in ra
        assert {row["rule_id"] for row in rb["rules"]} == {rd.rule_id for rd in CATALOGUE}
        assert rb["review_burden"]["unit"] == "signals" and rb["caveats"]
