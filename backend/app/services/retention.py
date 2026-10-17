"""Evidence retention and deletion.

Deleting evidence removes the stored file and anything derived from its contents (AI extraction and
reconciliation values). The record itself stays as a tombstone (filename, SHA-256, who/when/why), so
the audit trail still proves what existed. Every step is audited.

- an investigator *requests* deletion; a supervisor/admin *approves* or *cancels* it
- `run_retention` deletes files of resolved cases whose decision is older than EVIDENCE_RETENTION_DAYS
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.config import get_settings
from app.services.storage import StorageError, get_storage


def _purge(db: Session, item: m.EvidenceItem, actor: str, role: str, reason: str) -> None:
    try:
        get_storage().delete(item.storage_uri)
    except (StorageError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not delete the stored file ({type(exc).__name__})")
    item.retention_status = "deleted"
    item.deleted_at = m.utcnow()
    item.retention_note = reason
    item.extracted = None
    item.reconciliation = None
    item.analysis_status = "not_analysed"
    item.analysis_note = "File deleted under the retention policy; metadata and hash kept"
    db.flush()
    audit.record(db, item.case_id, actor, role, "evidence_deleted",
                 {"evidence_id": item.id, "filename": item.filename, "sha256": item.sha256, "reason": reason})


def evidence_deletion(db: Session, case: m.DisputeCase, user: m.User, body: dict) -> dict:
    item = db.get(m.EvidenceItem, body.get("evidence_id"))
    decision = body.get("decision")
    note = (body.get("note") or "").strip()
    if item is None or item.case_id != case.id:
        raise HTTPException(status_code=404, detail="Evidence not found")
    if item.retention_status == "deleted":
        raise HTTPException(status_code=409, detail="This evidence file was already deleted")
    if decision not in ("request", "approve", "cancel"):
        raise HTTPException(status_code=422, detail="decision must be request, approve or cancel")
    if len(note) < 10:
        raise HTTPException(status_code=422, detail="Give a reason of at least 10 characters")
    if decision == "request":
        if item.retention_status == "deletion_requested":
            raise HTTPException(status_code=409, detail="Deletion was already requested")
        item.retention_status = "deletion_requested"
        item.retention_note = note
        audit.record(db, case.id, user.username, user.role, "evidence_deletion_requested", {"evidence_id": item.id, "reason": note})
        return {"ok": True, "retention_status": item.retention_status}
    if user.role not in ("supervisor", "admin"):
        raise HTTPException(status_code=403, detail="Only a supervisor can approve or cancel evidence deletion")
    if decision == "cancel":
        if item.retention_status != "deletion_requested":
            raise HTTPException(status_code=409, detail="No deletion request to cancel")
        item.retention_status = "active"
        item.retention_note = None
        audit.record(db, case.id, user.username, user.role, "evidence_deletion_cancelled", {"evidence_id": item.id, "reason": note})
        return {"ok": True, "retention_status": item.retention_status}
    _purge(db, item, user.username, user.role, note)
    return {"ok": True, "retention_status": item.retention_status}


def run_retention(db: Session, user: m.User, dry_run: bool = True) -> dict:
    days = get_settings().evidence_retention_days
    cutoff = m.utcnow() - timedelta(days=days)
    q = (select(m.EvidenceItem).join(m.DisputeCase, m.DisputeCase.id == m.EvidenceItem.case_id)
         .where(m.DisputeCase.status == "resolved", m.DisputeCase.decided_at.is_not(None), m.DisputeCase.decided_at < cutoff,
                m.EvidenceItem.retention_status != "deleted"))
    items = db.scalars(q).all()
    out = [{"evidence_id": i.id, "case_id": i.case_id, "filename": i.filename} for i in items]
    if not dry_run:
        for i in items:
            _purge(db, i, user.username, user.role, f"Retention policy: case resolved more than {days} days ago")
    audit.record(db, None, user.username, user.role, "retention_run",
                 {"dry_run": dry_run, "retention_days": days, "eligible": len(items)})
    return {"dry_run": dry_run, "retention_days": days, "cutoff": cutoff.isoformat() + "Z", "eligible": out,
            "deleted": 0 if dry_run else len(items)}
