"""Loads the synthetic dataset into the database (through the real normalisation pipeline)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.config import get_settings
from app.security import hash_password
from app.seed import evidence_files
from app.seed.synthetic import build
from app.services.ledger import normalise
from app.services.policy import load_policies
from app.services.storage import get_storage, sha256

log = logging.getLogger("fundtrace.seed")

USERS = [
    ("inv.asha", "Asha Raman (synthetic)", "investigator"),
    ("inv.ravi", "Ravi Kumar (synthetic)", "investigator"),
    ("sup.meera", "Meera Iyer (synthetic)", "supervisor"),
    ("admin", "Platform Admin (synthetic)", "admin"),
]

_TABLES_IN_DELETE_ORDER = [m.AuditEvent, m.Report, m.AICall, m.AIRun, m.RiskFlag, m.Hold, m.EvidenceRequest, m.EvidenceItem,
                           m.CaseNote, m.DisputeCase, m.AuthEvent, m.Transaction, m.Device, m.Account, m.Customer,
                           m.Institution, m.Policy, m.EvalRun]


def is_seeded(db: Session) -> bool:
    return bool(db.scalar(select(func.count()).select_from(m.DisputeCase)))


def ensure_users(db: Session) -> None:
    pw = hash_password(get_settings().demo_password)
    for username, name, role in USERS:
        if not db.scalar(select(m.User).where(m.User.username == username)):
            db.add(m.User(username=username, full_name=name, role=role, password_hash=pw))
    db.flush()


def wipe(db: Session) -> None:
    for t in _TABLES_IN_DELETE_ORDER:
        db.execute(delete(t))
    db.flush()


def seed(db: Session, anchor: datetime | None = None) -> dict:
    anchor = anchor or m.utcnow()
    ds = build(anchor)
    ensure_users(db)
    users = {u.username: u for u in db.scalars(select(m.User)).all()}

    for i in ds.institutions:
        db.add(m.Institution(**i))
    for c in ds.customers:
        db.add(m.Customer(**c, is_synthetic=True))
    db.flush()
    for a in ds.accounts:
        db.add(m.Account(**a, is_synthetic=True))
    for dv in ds.devices:
        db.add(m.Device(**dv))
    db.flush()
    for e in ds.auth_events:
        db.add(m.AuthEvent(**e))
    txns, report = normalise(ds.raw_transactions)
    for t in txns:
        db.add(m.Transaction(**t, is_synthetic=True))
    db.flush()

    for p in load_policies():
        db.add(m.Policy(id=p["id"], version=p["version"], title=p["title"], categories=p["categories"], jurisdiction=p["jurisdiction"],
                        effective_from=p["effective_from"], clauses=p["clauses"], is_synthetic=True))

    for c in ds.cases:
        owner = users.get(c["owner"]) if c["owner"] else None
        db.add(m.DisputeCase(id=c["id"], disputed_txn_id=c["disputed_txn_id"], customer_id=c["customer_id"], category=c["category"],
                             allegation=c["allegation"], allegation_language=c["allegation_language"], status=c["status"],
                             owner_id=owner.id if owner else None, reported_at=c["reported_at"], created_at=c["reported_at"],
                             scenario=c["scenario"], is_synthetic=True))
    db.flush()
    for c in ds.cases:
        audit.record(db, c["id"], "system", "system", "case_created",
                     {"source": "synthetic seed", "scenario": c["scenario"], "disputed_txn_id": c["disputed_txn_id"]})

    storage = get_storage()
    for ev in ds.evidence:
        data, mime = _evidence_bytes(db, ev)
        uri = storage.put(data, ev["case_id"], mime)
        eid = "EV-" + uuid.uuid4().hex[:8].upper()
        db.add(m.EvidenceItem(id=eid, case_id=ev["case_id"], kind=ev["kind"], checklist_key=ev["checklist_key"], filename=ev["filename"],
                              mime=mime, sha256=sha256(data), storage_uri=uri, size=len(data), uploaded_by="customer (synthetic)",
                              uploaded_at=_case_reported(ds, ev["case_id"]), analysis_status="not_analysed", is_synthetic=True))
        db.flush()
        audit.record(db, ev["case_id"], "system", "system", "evidence_received", {"evidence_id": eid, "filename": ev["filename"], "sha256": sha256(data)})
    db.flush()

    db.add(m.EvalRun(kind="ground_truth", metrics={"anchor": ds.anchor.isoformat() + "Z"}, details=[ds.truth]))
    refresh_case_assessments(db)
    log.info("Seeded synthetic data: %s transactions (%s merged, %s rejected), %s cases", report.transactions,
             len(report.merged), len(report.rejected), len(ds.cases))
    return {"anchor": ds.anchor.isoformat() + "Z", "transactions": report.transactions, "merged": len(report.merged),
            "rejected": len(report.rejected), "cases": len(ds.cases), "accounts": len(ds.accounts), "auth_events": len(ds.auth_events),
            "truth": ds.truth}


def _case_reported(ds, case_id: str) -> datetime:
    return next(c["reported_at"] for c in ds.cases if c["id"] == case_id)


def _evidence_bytes(db: Session, ev: dict) -> tuple[bytes, str]:
    if ev["template"] == "receipt":
        utr = ev.get("utr") or db.get(m.Transaction, ev["txn"]).reference
        return evidence_files.receipt_png(ev["amount"], utr, ev["payee"], ev["time"], ev.get("injection", False)), "image/png"
    if ev["template"] == "chat":
        return evidence_files.chat_txt(), "text/plain"
    if ev["template"] == "order":
        t = db.get(m.Transaction, ev["txn"])
        return evidence_files.order_txt(t.reference, t.occurred_at), "text/plain"
    return evidence_files.complaint_ack_txt(ev["case_id"]), "text/plain"


def refresh_case_assessments(db: Session, case_ids: list[str] | None = None) -> None:
    """Recompute priority/SLA from deterministic services and store them on the case rows."""
    from app.services.investigation import build_context, sync_hold_recommendations

    q = select(m.DisputeCase)
    if case_ids:
        q = q.where(m.DisputeCase.id.in_(case_ids))
    for case in db.scalars(q).unique().all():
        ctx = build_context(db, case)
        if case.status != "resolved" and sync_hold_recommendations(db, case, ctx["attribution"]):
            ctx["holds"] = []
        cp = ctx["computed_priority"]
        case.priority, case.priority_reasons = cp["priority"], cp["reasons"]
        case.sla_policy = ctx["sla"]["policy"]
        case.due_at = datetime.fromisoformat(ctx["sla"]["due_at"].rstrip("Z"))
    db.flush()


def reset_demo(db: Session) -> dict:
    wipe(db)
    return seed(db)
