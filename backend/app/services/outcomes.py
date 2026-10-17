"""Outcome measurements — computed only from recorded case activity.

These answer "is the investigation process getting better?", separately from AI quality (AI Ops).
Nothing here is estimated or back-filled: a measurement with too few data points says so instead of
showing a number. Targets from the proposal are illustrative and are never shown as achieved results.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m

MIN_POINTS = 1  # show a value as soon as one real data point exists, always with its n
SYSTEM_ACTORS = {"system"}
PASSIVE_ACTIONS = {"case_created", "case_viewed", "evidence_received", "login", "rules_evaluated", "graph_expanded"}


def _hours(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds() / 3600, 2)


def _stat(values: list[float], unit: str, note: str) -> dict:
    if len(values) < MIN_POINTS:
        return {"value": None, "n": len(values), "unit": unit, "note": note, "status": "not_enough_data"}
    return {"value": round(statistics.median(values), 2), "n": len(values), "unit": unit, "note": note, "status": "ok"}


def _ratio(num: int, den: int, note: str) -> dict:
    if den < MIN_POINTS:
        return {"value": None, "n": den, "unit": "ratio", "note": note, "status": "not_enough_data"}
    return {"value": round(num / den, 4), "n": den, "unit": "ratio", "note": note, "status": "ok"}


def compute(db: Session, now: datetime | None = None) -> dict:
    now = now or m.utcnow()
    cases = db.scalars(select(m.DisputeCase)).unique().all()
    events = db.scalars(select(m.AuditEvent).where(m.AuditEvent.case_id.is_not(None)).order_by(m.AuditEvent.id)).all()
    by_case: dict[str, list[m.AuditEvent]] = defaultdict(list)
    for e in events:
        by_case[e.case_id].append(e)

    decided = [c for c in cases if c.decided_at]
    investigation_h = [_hours(c.reported_at, c.decided_at) for c in decided]

    first_action_h = []
    for c in cases:
        first = next((e for e in by_case[c.id] if e.actor not in SYSTEM_ACTORS and e.action not in PASSIVE_ACTIONS), None)
        if first:
            first_action_h.append(_hours(c.reported_at, first.created_at))

    escalation_h = []
    for c in cases:
        esc = next((e for e in by_case[c.id] if e.action == "status_changed" and (e.details or {}).get("to") == "escalated"), None)
        if esc:
            escalation_h.append(_hours(c.reported_at, esc.created_at))

    within_sla = [c for c in decided if c.due_at and c.decided_at <= c.due_at]
    open_cases = [c for c in cases if c.status != "resolved"]
    breached_open = [c for c in open_cases if c.due_at and c.due_at < now]

    completeness_at_decision = []
    for c in decided:
        dec = next((e for e in reversed(by_case[c.id]) if e.action == "decision_recorded"), None)
        r = (dec.details or {}).get("completeness_ratio") if dec else None
        if isinstance(r, (int, float)):
            completeness_at_decision.append(float(r))

    actions_per_case = [sum(1 for e in by_case[c.id] if e.actor not in SYSTEM_ACTORS and e.action not in PASSIVE_ACTIONS)
                        for c in decided]

    reports = db.scalars(select(m.Report)).all()
    factual = total_claims = 0
    for r in reports:
        for s in r.sections or []:
            for cl in s.get("claims", []):
                total_claims += 1
                if cl.get("citations") and not any(i.get("code") in ("invalid_citation", "invented_id") for i in cl.get("issues", [])):
                    factual += 1
    accepted = [r for r in reports if r.review_status == "accepted"]
    unsupported_in_accepted = sum(
        1 for r in accepted for s in r.sections or [] for cl in s.get("claims", [])
        if cl.get("flagged") and (r.review or {}).get("claims", {}).get(cl.get("id")) != "reject"
    )
    automated_rejections = sum(1 for c in decided if c.decision == "decline_claim" and c.decided_by is None)

    return {
        "generated_at": now.isoformat() + "Z",
        "cases": {"total": len(cases), "open": len(open_cases), "decided": len(decided)},
        "measurements": {
            "median_investigation_hours": _stat(investigation_h, "hours", "Reported → decision recorded, decided cases only"),
            "median_hours_to_first_action": _stat(first_action_h, "hours", "Reported → first investigator action"),
            "median_hours_to_escalation": _stat(escalation_h, "hours", "Reported → escalation, escalated cases only"),
            "decided_within_sla": _ratio(len(within_sla), len(decided), "Decisions recorded before the resolution due date"),
            "open_cases_past_sla": {"value": len(breached_open), "n": len(open_cases), "unit": "count",
                                    "note": "Open cases already past their resolution due date", "status": "ok"},
            "evidence_completeness_at_decision": _stat(completeness_at_decision, "ratio",
                                                       "Required evidence present when the decision was recorded (median)"),
            "findings_linked_to_sources": _ratio(factual, total_claims, "Report claims with valid source citations"),
            "unsupported_claims_in_accepted_reports": {"value": unsupported_in_accepted, "n": len(accepted), "unit": "count",
                                                      "note": "Flagged claims an investigator accepted (target 0)", "status": "ok"},
            "automated_claim_rejections": {"value": automated_rejections, "n": len(decided), "unit": "count",
                                           "note": "Claims declined without a human decision (structurally impossible; target 0)",
                                           "status": "ok"},
            "investigator_actions_per_decided_case": _stat([float(x) for x in actions_per_case], "actions",
                                                            "Recorded investigator actions per decided case (median)"),
        },
        "note": ("Measured from this deployment's case activity only. There is no historical baseline in a synthetic demo, so "
                 "improvement percentages are not claimed."),
    }
