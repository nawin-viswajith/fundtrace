"""Case lifecycle and investigator actions. Every action is explicit, validated and audited."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.services.scoring import CATEGORIES

STATUSES = ["new", "triage", "investigating", "awaiting_evidence", "ready_for_review", "escalated", "resolved"]
STATUS_LABELS = {"new": "New", "triage": "Triage", "investigating": "Investigating", "awaiting_evidence": "Awaiting evidence",
                 "ready_for_review": "Ready for review", "escalated": "Escalated", "resolved": "Resolved"}
TRANSITIONS = {
    "new": {"triage", "investigating", "escalated"},
    "triage": {"investigating", "awaiting_evidence", "escalated"},
    "investigating": {"awaiting_evidence", "ready_for_review", "escalated"},
    "awaiting_evidence": {"investigating", "ready_for_review", "escalated"},
    "ready_for_review": {"investigating", "escalated"},  # resolving happens only through a recorded decision
    "escalated": {"investigating"},
    "resolved": {"investigating"},
}
SUPERVISOR_ONLY = {("escalated", "investigating"), ("resolved", "investigating")}
DECISIONS = {"uphold_claim": "Uphold claim", "partial": "Partially uphold", "decline_claim": "Decline claim", "refer": "Refer / escalate"}


def _err(code: int, msg: str):
    raise HTTPException(status_code=code, detail=msg)


def apply_action(db: Session, case: m.DisputeCase, user: m.User, body: dict) -> dict:
    kind = body.get("type")
    actor, role = user.username, user.role
    if kind == "note":
        text = (body.get("body") or "").strip()
        if not 2 <= len(text) <= 5000:
            _err(422, "Note must be 2–5000 characters")
        note = m.CaseNote(case_id=case.id, author_id=user.id, body=text)
        db.add(note)
        db.flush()
        audit.record(db, case.id, actor, role, "note_added", {"note_id": note.id, "length": len(text)})
        return {"ok": True, "note_id": note.id}

    if kind == "assign":
        target = body.get("user_id")
        if role == "investigator":
            if target not in (None, user.id) or (case.owner_id not in (None, user.id)):
                _err(403, "Investigators can only claim unassigned cases or release their own")
        new_owner = db.get(m.User, target) if target else None
        if target and (new_owner is None or new_owner.role not in ("investigator", "supervisor")):
            _err(422, "Unknown assignee")
        prev = case.owner_id
        case.owner_id = new_owner.id if new_owner else None
        audit.record(db, case.id, actor, role, "case_assigned", {"from": prev, "to": case.owner_id})
        return {"ok": True}

    if kind == "status":
        to = body.get("to")
        reason = (body.get("reason") or "").strip()
        if to not in STATUSES:
            _err(422, "Unknown status")
        if to == "resolved":
            _err(422, "Resolve a case by recording a decision")
        if to not in TRANSITIONS.get(case.status, set()):
            _err(409, f"Cannot move from {STATUS_LABELS[case.status]} to {STATUS_LABELS[to]}")
        if (case.status, to) in SUPERVISOR_ONLY and role not in ("supervisor", "admin"):
            _err(403, "Only a supervisor can reopen this case")
        if to == "escalated" and len(reason) < 10:
            _err(422, "Escalation needs a reason (at least 10 characters)")
        prev = case.status
        case.status = to
        audit.record(db, case.id, actor, role, "status_changed", {"from": prev, "to": to, "reason": reason})
        return {"ok": True, "status": to}

    if kind == "request_evidence":
        key = body.get("checklist_key")
        frm = (body.get("requested_from") or "customer").strip()[:64]
        if not key:
            _err(422, "checklist_key is required")
        req = m.EvidenceRequest(case_id=case.id, checklist_key=key, requested_from=frm, note=(body.get("note") or "")[:2000], requested_by=user.id)
        db.add(req)
        db.flush()
        audit.record(db, case.id, actor, role, "evidence_requested", {"request_id": req.id, "checklist_key": key, "from": frm})
        return {"ok": True, "request_id": req.id}

    if kind == "hold":
        hold = db.get(m.Hold, body.get("hold_id"))
        decision = body.get("decision")
        note = (body.get("note") or "").strip()
        if hold is None or hold.case_id != case.id:
            _err(404, "Hold recommendation not found")
        if decision not in ("request", "decline"):
            _err(422, "decision must be request or decline")
        if hold.status != "recommended":
            _err(409, "This recommendation was already decided")
        if len(note) < 5:
            _err(422, "Add a short note explaining the decision")
        amount = body.get("amount_minor", hold.amount_minor)
        if decision == "request":
            if not isinstance(amount, int) or amount <= 0 or amount > hold.amount_minor:
                _err(422, "Hold amount must be positive and not exceed the traceable upper bound")
            hold.amount_minor = amount
        hold.status = "requested" if decision == "request" else "declined"
        hold.decided_by, hold.decided_at, hold.decision_note = user.id, m.utcnow(), note
        audit.record(db, case.id, actor, role, "hold_" + hold.status,
                     {"hold_id": hold.id, "account_id": hold.account_id, "amount_minor": hold.amount_minor, "basis": hold.basis, "note": note})
        return {"ok": True, "hold_status": hold.status}

    if kind == "recategorise":
        cat = body.get("category")
        reason = (body.get("reason") or "").strip()
        if cat not in CATEGORIES:
            _err(422, "Unknown category")
        if len(reason) < 5:
            _err(422, "Give a reason")
        prev = case.category
        case.category, case.category_source = cat, "investigator"
        audit.record(db, case.id, actor, role, "category_changed", {"from": prev, "to": cat, "reason": reason,
                                                                     "ai_suggestion_used": bool(body.get("from_ai"))})
        return {"ok": True}

    if kind == "decision":
        decision = body.get("decision")
        rationale = (body.get("rationale") or "").strip()
        override = (body.get("override_reason") or "").strip()
        if decision not in DECISIONS:
            _err(422, "Unknown decision")
        if case.status != "ready_for_review":
            _err(409, "Move the case to Ready for review before recording a decision")
        if len(rationale) < 20:
            _err(422, "Rationale must be at least 20 characters")
        latest = db.scalar(select(m.Report).where(m.Report.case_id == case.id).order_by(m.Report.version.desc()).limit(1))
        if (latest is None or latest.review_status == "pending") and len(override) < 10:
            _err(422, "Review the latest investigation report first, or give an override reason")
        case.decision, case.decision_rationale = decision, rationale
        case.decided_by, case.decided_at = user.id, m.utcnow()
        case.status = "escalated" if decision == "refer" else "resolved"
        audit.record(db, case.id, actor, role, "decision_recorded",
                     {"decision": decision, "rationale": rationale, "override_reason": override or None,
                      "report_id": latest.id if latest else None, "report_review": latest.review_status if latest else None})
        return {"ok": True, "status": case.status}

    _err(422, "Unknown action type")
    return {}


def review_report(db: Session, report: m.Report, user: m.User, body: dict) -> dict:
    status = body.get("status")
    if status not in ("accepted", "rejected", "partial"):
        _err(422, "status must be accepted, rejected or partial")
    claim_reviews = body.get("claims") or {}
    valid_ids = {c["id"] for s in report.sections for c in s["claims"]}
    bad = [k for k in claim_reviews if k not in valid_ids or claim_reviews[k] not in ("accept", "reject")]
    if bad:
        _err(422, f"Invalid claim reviews: {bad[:5]}")
    note = (body.get("note") or "").strip()[:2000]
    report.review_status = status
    report.review = {"claims": claim_reviews, "note": note}
    report.reviewed_by, report.reviewed_at = user.id, m.utcnow()
    audit.record(db, report.case_id, user.username, user.role, "report_reviewed",
                 {"report_id": report.id, "status": status, "claims_rejected": sum(1 for v in claim_reviews.values() if v == "reject"),
                  "note": note})
    return {"ok": True}
