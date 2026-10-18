"""Overview dashboard, global case search and per-case next actions."""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import models as m
from app.db import get_db
from app.security import can_access_case, current_user
from app.services import outcomes
from app.services.scoring import CATEGORIES
from app.services.trace import fmt_amount

router = APIRouter(prefix="/api", tags=["overview"])


def accessible_cases(db: Session, user: m.User) -> list[m.DisputeCase]:
    q = select(m.DisputeCase)
    if user.role == "investigator":
        q = q.where(or_(m.DisputeCase.owner_id.is_(None), m.DisputeCase.owner_id == user.id))
    return db.scalars(q).unique().all()


def next_actions(db: Session, cases: list[m.DisputeCase]) -> dict[str, dict | None]:
    """Deterministic 'what should the investigator do next' per case, from recorded state only."""
    ids = [c.id for c in cases]
    if not ids:
        return {}
    holds = Counter(h.case_id for h in db.scalars(select(m.Hold).where(m.Hold.case_id.in_(ids), m.Hold.status == "recommended")).all())
    open_reqs = Counter(r.case_id for r in db.scalars(select(m.EvidenceRequest).where(m.EvidenceRequest.case_id.in_(ids),
                                                                                       m.EvidenceRequest.status == "open")).all())
    latest: dict[str, m.Report] = {}
    for r in db.scalars(select(m.Report).where(m.Report.case_id.in_(ids)).order_by(m.Report.version)).all():
        latest[r.case_id] = r
    out: dict[str, dict | None] = {}
    for c in cases:
        rep = latest.get(c.id)
        if c.status == "resolved":
            out[c.id] = None
        elif c.status == "escalated":
            out[c.id] = {"label": "A supervisor needs to review the escalation", "tab": "audit"}
        elif c.status == "new":
            out[c.id] = {"label": "Check the money trail and take the case", "tab": "graph"}
        elif holds[c.id]:
            out[c.id] = {"label": f"Decide on {holds[c.id]} suggested hold{'s' if holds[c.id] > 1 else ''}", "tab": "overview"}
        elif c.status == "ready_for_review":
            out[c.id] = {"label": "Record the decision", "tab": "audit"}
        elif rep is None:
            out[c.id] = {"label": "Run the AI investigation", "tab": "report"}
        elif rep.review_status == "pending":
            out[c.id] = {"label": "Review the AI report", "tab": "report"}
        elif open_reqs[c.id]:
            out[c.id] = {"label": f"Follow up on {open_reqs[c.id]} evidence request{'s' if open_reqs[c.id] > 1 else ''}", "tab": "evidence"}
        else:
            out[c.id] = {"label": "Mark the case ready for review", "tab": "overview"}
    return out


@router.get("/overview")
def overview(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    now = m.utcnow()
    cases = accessible_cases(db, user)
    open_cases = [c for c in cases if c.status != "resolved"]
    actions = next_actions(db, open_cases)
    case_ids = [c.id for c in cases]
    holds = db.scalars(select(m.Hold).where(m.Hold.case_id.in_(case_ids), m.Hold.status == "recommended")).all() if case_ids else []
    golden = sorted({h.case_id for h in holds})
    from app.services.scoring import sla as sla_clock

    # Every SLA milestone counts (e.g. shadow credit, hold request), not only final resolution.
    next_ms: dict[str, float] = {}
    any_breach: set[str] = set()
    for c in open_cases:
        ms = sla_clock(c.category, c.disputed_txn.currency, c.reported_at, now)["milestones"]
        if any(x["breached"] for x in ms):
            any_breach.add(c.id)
        open_ms = [x["remaining_hours"] for x in ms if not x["breached"]]
        if open_ms:
            next_ms[c.id] = min(open_ms)
    at_risk = sorted([c for c in open_cases if c.id in next_ms and next_ms[c.id] < 72], key=lambda c: next_ms[c.id])
    breached = [c for c in open_cases if c.id in any_breach]
    order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    focus = sorted(open_cases, key=lambda c: (order.get(c.priority, 9), c.due_at or c.reported_at))[:6]
    recent = db.scalars(select(m.AuditEvent).where(m.AuditEvent.case_id.in_(case_ids), m.AuditEvent.action != "case_viewed",
                                                   m.AuditEvent.actor != "system")
                        .order_by(m.AuditEvent.id.desc()).limit(12)).all() if case_ids else []

    def brief(c: m.DisputeCase) -> dict:
        return {"id": c.id, "category_label": CATEGORIES.get(c.category, c.category), "priority": c.priority, "status": c.status,
                "amount_label": fmt_amount(c.disputed_txn.amount_minor, c.disputed_txn.currency),
                "due_at": c.due_at.isoformat() + "Z" if c.due_at else None,
                "sla_remaining_hours": round((c.due_at - now).total_seconds() / 3600, 1) if c.due_at else None,
                "priority_reasons": c.priority_reasons, "next_action": actions.get(c.id)}

    return {
        "counts": {
            "open": len(open_cases),
            "by_priority": {p: sum(1 for c in open_cases if c.priority == p) for p in ("P1", "P2", "P3", "P4")},
            "by_status": dict(Counter(c.status for c in cases)),
            "unassigned": sum(1 for c in open_cases if c.owner_id is None),
            "mine": sum(1 for c in open_cases if c.owner_id == user.id),
            "golden_hour": len(golden),
            "sla_at_risk_72h": len(at_risk),
            "sla_breached": len(breached),
            "disputed_open_amount_label": fmt_amount(sum(c.disputed_txn.amount_minor for c in open_cases), "INR"),
        },
        "focus": [brief(c) for c in focus],
        "golden_hour": [brief(c) for c in cases if c.id in golden],
        "at_risk": [brief(c) for c in at_risk[:6]],
        "recent_activity": [{"id": e.id, "case_id": e.case_id, "actor": e.actor, "action": e.action,
                             "created_at": e.created_at.isoformat() + "Z"} for e in recent],
        "outcomes": outcomes.compute(db, now),
    }


@router.get("/outcomes")
def outcome_measurements(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return outcomes.compute(db)


@router.get("/search")
def search(q: str = Query(..., min_length=2, max_length=64), user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    """Find cases by case id, disputed transaction id, payment reference, account or customer id."""
    term = q.strip()
    like = f"%{term}%"
    stmt = (select(m.DisputeCase).join(m.Transaction, m.Transaction.id == m.DisputeCase.disputed_txn_id)
            .where(or_(m.DisputeCase.id.like(like), m.DisputeCase.disputed_txn_id.like(like), m.DisputeCase.customer_id.like(like),
                       m.Transaction.reference.like(like), m.Transaction.debit_account_id.like(like),
                       m.Transaction.credit_account_id.like(like)))
            .limit(25))
    rows = [c for c in db.scalars(stmt).unique().all() if can_access_case(user, c)][:10]
    results = []
    for c in rows:
        t = c.disputed_txn
        matched = ("case" if term.upper() in c.id.upper() else "transaction" if term.upper() in t.id.upper()
                   else "reference" if t.reference and term in t.reference else "customer" if term.upper() in c.customer_id.upper()
                   else "account")
        results.append({"id": c.id, "category_label": CATEGORIES.get(c.category, c.category), "status": c.status, "priority": c.priority,
                        "amount_label": fmt_amount(t.amount_minor, t.currency), "matched_on": matched, "disputed_txn_id": t.id})
    return {"query": term, "results": results}
