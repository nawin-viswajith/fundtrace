"""Evaluation against synthetic ground truth.

Deterministic layer: rule statuses, trail endpoints, attribution bounds, consistency, policy.
AI layer (when reports exist): hallucination rate, claim support, citation validity, cost, latency.

Run:  python -m app.eval.harness
"""
from __future__ import annotations

import statistics

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.services.investigation import build_context


def evaluate_deterministic(db: Session, truth: dict | None = None) -> dict:
    if truth is None:
        gt = db.scalar(select(m.EvalRun).where(m.EvalRun.kind == "ground_truth").order_by(m.EvalRun.id.desc()).limit(1))
        truth = gt.details[0] if gt and gt.details else {}
    details, checks, passed = [], 0, 0
    rule_tp = rule_fp = rule_fn = 0
    for scenario, tr in truth.items():
        case = db.get(m.DisputeCase, tr["case"])
        if case is None:
            continue
        ctx = build_context(db, case)
        st = {r["rule_id"]: r["status"] for r in ctx["rules"]}
        nodes = {n["id"]: n for n in ctx["graph"]["nodes"]}
        res = []

        def check(name: str, ok: bool, detail: str = "") -> None:
            res.append({"check": name, "passed": bool(ok), "detail": detail})

        for rid in tr.get("triggered", []):
            ok = st.get(rid) == "triggered"
            rule_tp += ok
            rule_fn += not ok
            check(f"{rid} triggers", ok, st.get(rid, "missing"))
        for rid in tr.get("not_triggered", []):
            ok = st.get(rid) == "not_triggered"
            rule_fp += st.get(rid) == "triggered"
            check(f"{rid} does not trigger", ok, st.get(rid, "missing"))
        for rid in tr.get("not_evaluable", []):
            check(f"{rid} not evaluable (missing data)", st.get(rid) == "not_evaluable", st.get(rid, "missing"))
        for acct, ep in tr.get("endpoints", {}).items():
            got = nodes.get(acct, {}).get("endpoint")
            check(f"endpoint {acct} = {ep}", got == ep, str(got))
        for tid, b in tr.get("attribution", {}).items():
            got = ctx["attribution"]["per_transaction"].get(tid, {})
            check(f"attribution bounds {tid}", got.get("min") == b["min"] and got.get("max") == b["max"],
                  f"min={got.get('min')} max={got.get('max')}")
        for m_ in ("min", "fifo", "pro_rata", "max"):
            b = (ctx["attribution"].get("buckets") or {}).get(m_)
            if b and b.get("unaccounted") is not None:
                check(f"money conserved ({m_})", b["unaccounted"] == 0, str(b["unaccounted"]))
        for acct in tr.get("holdable", []):
            check(f"hold candidate {acct}", any(h["account_id"] == acct for h in ctx["attribution"].get("holdable", [])))
        if tr.get("consistency_contradictory"):
            check("contradiction detected", ctx["consistency"]["contradictory"] > 0)
        if tr.get("source_discrepancy"):
            check("source discrepancy detected", any("Source systems agree on" in c["check"] and c["result"] == "contradictory"
                                                     for c in ctx["consistency"]["checks"]))
        if "policy_overall" in tr:
            check("policy eligibility", ctx["policy"]["overall"] == tr["policy_overall"], ctx["policy"]["overall"])
        checks += len(res)
        passed += sum(1 for r in res if r["passed"])
        details.append({"scenario": scenario, "case_id": case.id, "checks": res,
                        "passed": sum(1 for r in res if r["passed"]), "total": len(res)})
    precision = rule_tp / (rule_tp + rule_fp) if (rule_tp + rule_fp) else None
    recall = rule_tp / (rule_tp + rule_fn) if (rule_tp + rule_fn) else None
    return {"checks": checks, "passed": passed, "pass_rate": round(passed / checks, 4) if checks else None,
            "rule_precision": round(precision, 4) if precision is not None else None,
            "rule_recall": round(recall, 4) if recall is not None else None, "details": details}


def evaluate_ai(db: Session) -> dict:
    reports = db.scalars(select(m.Report).where(m.Report.generator != "deterministic")).all()
    calls = db.scalars(select(m.AICall)).all()
    if not reports and not calls:
        return {"reports": 0, "note": "No AI reports generated yet."}
    hr = [r.hallucination_rate for r in reports if r.hallucination_rate is not None]
    conf = [r.confidence for r in reports if r.confidence is not None]
    lat = [c.latency_ms for c in calls if c.status == "ok"]
    return {
        "reports": len(reports),
        "claims_total": sum(r.claims_total for r in reports),
        "claims_supported": sum(r.claims_supported for r in reports),
        "claims_flagged": sum(r.claims_flagged for r in reports),
        "mean_hallucination_rate": round(statistics.mean(hr), 4) if hr else None,
        "mean_confidence": round(statistics.mean(conf), 4) if conf else None,
        "calls": len(calls),
        "call_error_rate": round(sum(1 for c in calls if c.status != "ok") / len(calls), 4) if calls else None,
        "p50_latency_ms": int(statistics.median(lat)) if lat else None,
        "total_cost_usd": round(sum(c.cost_usd for c in calls), 6),
    }


def evaluate_classification(db: Session, gateway=None) -> dict:
    """Gemini category suggestions vs. the labelled category of each synthetic case: accuracy and macro-F1.

    Labels are the categories the synthetic scenarios were written for. Calls that fail are counted as
    not analysed, never as a wrong or right answer.
    """
    from app.ai.copilot import classify_statement

    cases = db.scalars(select(m.DisputeCase).where(m.DisputeCase.is_synthetic.is_(True))).unique().all()
    rows, not_analysed = [], 0
    for c in cases:
        res = classify_statement(db, c, gateway=gateway, node="eval_classify")
        if not res.ok:
            not_analysed += 1
            continue
        rows.append({"case_id": c.id, "label": c.category, "predicted": res.data.category.value})
    if not rows:
        return {"status": "not_analysed", "cases": len(cases), "not_analysed": not_analysed,
                "note": "No classification could be run (AI unavailable)."}
    labels = sorted({r["label"] for r in rows} | {r["predicted"] for r in rows})
    per_class = {}
    for lab in labels:
        tp = sum(1 for r in rows if r["label"] == lab and r["predicted"] == lab)
        fp = sum(1 for r in rows if r["label"] != lab and r["predicted"] == lab)
        fn = sum(1 for r in rows if r["label"] == lab and r["predicted"] != lab)
        p = tp / (tp + fp) if tp + fp else 0.0
        rcl = tp / (tp + fn) if tp + fn else 0.0
        per_class[lab] = {"precision": round(p, 4), "recall": round(rcl, 4), "f1": round(2 * p * rcl / (p + rcl), 4) if p + rcl else 0.0,
                          "support": sum(1 for r in rows if r["label"] == lab)}
    present = [lab for lab in labels if per_class[lab]["support"] > 0]
    return {"status": "ok", "cases": len(cases), "classified": len(rows), "not_analysed": not_analysed,
            "accuracy": round(sum(1 for r in rows if r["label"] == r["predicted"]) / len(rows), 4),
            "macro_f1": round(sum(per_class[lab]["f1"] for lab in present) / len(present), 4) if present else None,
            "per_class": per_class, "rows": rows,
            "note": "Labels are the categories the synthetic scenarios were written for; a small set, so treat as a smoke check."}


def run_and_store(db: Session, include_classification: bool = False, gateway=None) -> m.EvalRun:
    det = evaluate_deterministic(db)
    ai = evaluate_ai(db)
    metrics = {"deterministic": {k: v for k, v in det.items() if k != "details"}, "ai": ai}
    if include_classification:
        cls = evaluate_classification(db, gateway)
        metrics["classification"] = {k: v for k, v in cls.items() if k != "rows"}
    run = m.EvalRun(kind="full", metrics=metrics, details=det["details"])
    db.add(run)
    db.flush()
    return run


if __name__ == "__main__":  # pragma: no cover
    import json

    from app.db import create_all, init_engine, session_scope

    init_engine()
    create_all()
    with session_scope() as s:
        r = run_and_store(s)
        print(json.dumps(r.metrics, indent=2))
