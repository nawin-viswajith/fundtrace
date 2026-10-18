"""Quality measurements — computed only from recorded reviews, decisions and rule results.

Two questions, both answered from what actually happened in this deployment:

1. Reviewer agreement: when an investigator marks a report claim accept / reject, how often does that
   match the AI fact-check verdict on the same claim? Reported as a simple agreement rate, a 2x2 table and
   Cohen's kappa (agreement beyond what chance alone would give).
2. Rule false-positive burden: for decided cases, how often was a warning sign found on a claim the bank
   then declined? A declined claim does not prove the sign was wrong — it is a proxy for the review work
   a sign creates, not a measure of rule accuracy.

Like ``outcomes``, nothing is estimated or back-filled: a measurement with too few data points says
"not_enough_data" instead of showing a number.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.services.outcomes import MIN_POINTS
from app.services.rules import CATALOGUE, NOT_EVALUABLE, TRIGGERED

# A rate from a handful of points says more about chance than about quality.
MIN_CLAIMS_COMPARED = 10  # claims compared before an overall agreement rate / kappa is shown
MIN_REPORT_CLAIMS = 3  # claims compared before a single report's agreement share is shown
MIN_RULE_CASES = 5  # decided cases where a rule was triggered before its declined share is shown
MAX_CASES = 200  # bound on cases considered per group (decided / open), most recent first

AI_SUPPORTED = {"supported", "partial"}
AI_NOT_SUPPORTED = {"unsupported", "contradicted"}
UPHELD = {"uphold_claim", "partial"}
DECLINED = {"decline_claim"}
GENERATOR_RATIONALE = "Synthetic decision created by the demo data generator."


def _not_enough(n: int, minimum: int) -> dict:
    return {"status": "not_enough_data", "n": n, "min": minimum}


# ---------------------------------------------------------------------------- reviewer agreement

def kappa(a: int, b: int, c: int, d: int) -> float | None:
    """Cohen's kappa for a 2x2 table.

    a = accept & supported, b = accept & not supported, c = reject & supported, d = reject & not supported.
    Returns None when chance agreement is already 100% (both sides gave one answer only), where kappa is undefined.
    """
    n = a + b + c + d
    if n == 0:
        return None
    po = (a + d) / n
    pe = ((a + b) / n) * ((a + c) / n) + ((c + d) / n) * ((b + d) / n)
    if pe >= 1:
        return None
    return round((po - pe) / (1 - pe), 4)


def kappa_label(k: float | None) -> str | None:
    """Plain-language band (Landis & Koch, 1977)."""
    if k is None:
        return None
    if k < 0:
        return "less than chance"
    if k <= 0.2:
        return "slight"
    if k <= 0.4:
        return "fair"
    if k <= 0.6:
        return "moderate"
    if k <= 0.8:
        return "substantial"
    return "almost perfect"


def agreement(reports: Iterable[m.Report]) -> dict:
    """Investigator accept/reject vs AI fact-check verdict, over every report with a saved review."""
    table = {"accept": {"supported": 0, "not_supported": 0}, "reject": {"supported": 0, "not_supported": 0}}
    excluded: dict[str, int] = defaultdict(int)
    not_marked = 0
    rows = []
    for r in reports:
        marks = (r.review or {}).get("claims") or {}
        if r.review_status == "pending" or not r.review:
            continue
        claims = {cl.get("id"): cl for s in r.sections or [] for cl in s.get("claims", [])}
        not_marked += sum(1 for cid in claims if cid not in marks)
        compared = agreed = skipped = 0
        for cid, mark in marks.items():
            cl = claims.get(cid)
            verdict = (cl or {}).get("verdict") or "unjudged"
            if cl is None or mark not in ("accept", "reject"):
                excluded["missing"] += 1
                skipped += 1
                continue
            if verdict in AI_SUPPORTED:
                ai = "supported"
            elif verdict in AI_NOT_SUPPORTED:
                ai = "not_supported"
            else:  # unjudged, system_generated (written by code) — the AI gave no verdict to agree with
                excluded[verdict if verdict in ("unjudged", "system_generated") else "other"] += 1
                skipped += 1
                continue
            table[mark][ai] += 1
            compared += 1
            agreed += (mark == "accept") == (ai == "supported")
        if compared or skipped:
            rows.append({"report_id": r.id, "case_id": r.case_id, "version": r.version, "review_status": r.review_status,
                         "compared": compared, "agreed": agreed, "excluded": skipped,
                         "agreement": round(agreed / compared, 4) if compared >= MIN_REPORT_CLAIMS else None,
                         "reviewed_at": r.reviewed_at.isoformat() + "Z" if r.reviewed_at else None})
    a, b = table["accept"]["supported"], table["accept"]["not_supported"]
    c, d = table["reject"]["supported"], table["reject"]["not_supported"]
    n = a + b + c + d
    out = {
        "claims_compared": n,
        "agreed": a + d,
        "table": table,
        "excluded": {k: excluded.get(k, 0) for k in ("unjudged", "system_generated", "other", "missing")},
        "claims_not_marked": not_marked,
        "reports": len(rows),
        "per_report": sorted(rows, key=lambda x: (x["reviewed_at"] or "", x["report_id"]), reverse=True),
        "min_claims": MIN_CLAIMS_COMPARED,
        "min_report_claims": MIN_REPORT_CLAIMS,
        "note": ("Compares each claim an investigator marked accept or reject with the AI fact-check verdict on the same "
                 "claim. Agreement means accept + supported/partly supported, or reject + unsupported/contradicted. "
                 "Claims the fact-check did not judge, or that were written by code from records, are left out."),
        "kappa_note": ("Kappa is agreement beyond chance: 0 means no better than if both sides answered at random with "
                       "the same overall mix, 1 means perfect agreement. A high agreement rate can still have a low kappa "
                       "when almost every claim gets the same answer."),
        "does_not_mean": ("Agreement does not show who is right. The investigator's review is the decision that counts; "
                          "a disagreement is a claim worth a second look, not an AI or investigator error."),
    }
    if n < MIN_CLAIMS_COMPARED:
        return {**out, **_not_enough(n, MIN_CLAIMS_COMPARED), "agreement_rate": None, "kappa": None, "kappa_label": None,
                "kappa_undefined_reason": None}
    k = kappa(a, b, c, d)
    return {**out, "status": "ok", "n": n, "min": MIN_CLAIMS_COMPARED, "agreement_rate": round((a + d) / n, 4),
            "kappa": k, "kappa_label": kappa_label(k),
            "kappa_undefined_reason": None if k is not None else
            "Not computable: every claim got the same answer from one side, so chance alone explains the agreement."}


def compute_agreement(db: Session) -> dict:
    reports = db.scalars(select(m.Report).where(m.Report.review_status != "pending").order_by(m.Report.id)).all()
    return agreement(reports)


# ---------------------------------------------------------------------------- rule false-positive burden

def _stored_statuses(db: Session, case_ids: list[str]) -> dict[str, dict[str, str]]:
    """Latest persisted rule evaluation per case: {case_id: {rule_id: status}}."""
    if not case_ids:
        return {}
    flags = db.scalars(select(m.RiskFlag).where(m.RiskFlag.case_id.in_(case_ids))).all()
    latest: dict[str, tuple[datetime, str]] = {}
    for f in flags:
        key = (f.evaluated_at, f.evaluation_id)
        if f.case_id not in latest or key > latest[f.case_id]:
            latest[f.case_id] = key
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for f in flags:
        if latest[f.case_id][1] == f.evaluation_id:
            out[f.case_id][f.rule_id] = f.status
    return dict(out)


def rule_statuses(db: Session, cases: list[m.DisputeCase]) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    """Rule results per case: the stored evaluation when there is one, otherwise evaluated now (not saved)."""
    from app.services.investigation import build_context

    stored = _stored_statuses(db, [c.id for c in cases])
    out: dict[str, dict[str, str]] = {}
    sources = {"stored": 0, "evaluated_now": 0, "failed": 0}
    for c in cases:
        if c.id in stored:
            out[c.id] = stored[c.id]
            sources["stored"] += 1
            continue
        try:
            out[c.id] = {r["rule_id"]: r["status"] for r in build_context(db, c)["rules"]}
            sources["evaluated_now"] += 1
        except Exception:  # a case whose data cannot be traced is counted, never guessed
            sources["failed"] += 1
    return out, sources


def burden(decided: list[tuple[str, dict[str, str]]], open_triggered: list[int]) -> dict:
    """Per-rule counts over decided cases, plus the average number of signals an open case carries.

    ``decided`` is [(decision, {rule_id: status})]; ``open_triggered`` is the triggered-signal count per open case.
    """
    rules = []
    for rd in CATALOGUE:  # rules can be added or removed: always iterate the live catalogue
        evaluated = [(dec, st[rd.rule_id]) for dec, st in decided if rd.rule_id in st]
        trig = [dec for dec, s in evaluated if s == TRIGGERED]
        upheld = sum(1 for dec in trig if dec in UPHELD)
        declined = sum(1 for dec in trig if dec in DECLINED)
        row = {"rule_id": rd.rule_id, "name": rd.name, "severity": rd.default_severity, "evaluated": len(evaluated),
               "triggered": len(trig), "upheld": upheld, "declined": declined,
               "not_evaluable": sum(1 for _, s in evaluated if s == NOT_EVALUABLE)}
        if len(trig) < MIN_RULE_CASES:
            row |= {"declined_share": None, **_not_enough(len(trig), MIN_RULE_CASES)}
        else:
            row |= {"declined_share": round(declined / len(trig), 4), "status": "ok", "n": len(trig), "min": MIN_RULE_CASES}
        rules.append(row)
    # Highest declined share first; rules without enough data follow, most often found first.
    rules.sort(key=lambda r: (r["declined_share"] is None, -(r["declined_share"] or 0), -r["triggered"], r["rule_id"]))
    if len(open_triggered) < MIN_POINTS:
        review = {"value": None, **_not_enough(len(open_triggered), MIN_POINTS)}
    else:
        review = {"value": round(statistics.mean(open_triggered), 2), "median": statistics.median(open_triggered),
                  "status": "ok", "n": len(open_triggered), "min": MIN_POINTS}
    review |= {"unit": "signals",
               "note": "Warning signs found per open case (average). Each one is something an investigator has to check."}
    return {"rules": rules, "review_burden": review}


def compute_rule_burden(db: Session, max_cases: int = MAX_CASES) -> dict:
    cases = db.scalars(select(m.DisputeCase)).unique().all()
    decided_all = [c for c in cases if c.status == "resolved" and c.decision in UPHELD | DECLINED]
    decided = sorted(decided_all, key=lambda c: (c.decided_at or c.reported_at, c.id), reverse=True)[:max_cases]
    open_all = [c for c in cases if c.status != "resolved"]
    open_cases = sorted(open_all, key=lambda c: (c.reported_at, c.id), reverse=True)[:max_cases]

    dec_status, dec_sources = rule_statuses(db, decided)
    open_status, open_sources = rule_statuses(db, open_cases)
    rows = [(c.decision, dec_status[c.id]) for c in decided if c.id in dec_status]
    open_counts = [sum(1 for s in open_status[c.id].values() if s == TRIGGERED) for c in open_cases if c.id in open_status]

    synthetic = sum(1 for c in decided if c.is_synthetic)
    made_up = sum(1 for c in decided if (c.decision_rationale or "").strip() == GENERATOR_RATIONALE)
    caveats = [
        "A declined claim does not prove the warning sign was wrong: a claim can be declined for reasons the sign never "
        "looked at (late reporting, policy, the customer authorised the payment). Read the declined share as review "
        "work that did not change the outcome, not as a rule error rate.",
        "Counts cover decided cases only (claim upheld, partly upheld or declined). Referred cases are not counted.",
        "\"Could not check\" means the data the sign needs was missing. It is never counted as a clear result.",
    ]
    demo = []
    if synthetic:
        demo.append(f"{synthetic} of {len(decided)} decided case(s) are synthetic demo data, so these are demo figures and "
                    "not the bank's real rule performance.")
    if made_up:
        demo.append(f"{made_up} decision(s) were picked at random by the demo data generator; they say nothing about "
                    "whether a sign was useful.")
    return {
        **burden(rows, open_counts),
        "decided_cases": len(rows),
        "decided_cases_total": len(decided_all),
        "open_cases": len(open_counts),
        "open_cases_total": len(open_all),
        "max_cases": max_cases,
        "sources": {"decided": dec_sources, "open": open_sources},
        "source_note": ("Each case uses its latest saved rule check (from its last investigation run) when there is one; "
                        "otherwise the rules are checked now with today's settings and data, without saving. "
                        f"At most {max_cases} of the most recent cases are considered in each group."),
        "synthetic_cases": synthetic,
        "generator_decisions": made_up,
        "min_cases_per_rule": MIN_RULE_CASES,
        "demo_note": " ".join(demo) or None,
        "caveats": caveats,
    }


def compute(db: Session, now: datetime | None = None) -> dict:
    now = now or m.utcnow()
    return {"generated_at": now.isoformat() + "Z", "reviewer_agreement": compute_agreement(db), "rule_burden": compute_rule_burden(db)}
