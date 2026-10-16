"""Append-only, hash-chained audit trail.

Each case has its own chain: hash = sha256(prev_hash + canonical JSON of the event). Editing or
deleting any past event breaks every later hash, which `verify` detects.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.telemetry import current_trace_id

GENESIS = "0" * 64


def _canonical(case_id, actor, actor_role, action, details, created_at, prev_hash) -> str:
    return json.dumps(
        {"case_id": case_id, "actor": actor, "actor_role": actor_role, "action": action, "details": details,
         "created_at": created_at.isoformat(), "prev_hash": prev_hash},
        sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False,
    )


def record(db: Session, case_id: str | None, actor: str, actor_role: str, action: str, details: dict | None = None) -> m.AuditEvent:
    details = json.loads(json.dumps(details or {}, default=str))
    last = db.scalar(
        select(m.AuditEvent).where(m.AuditEvent.case_id == case_id if case_id else m.AuditEvent.case_id.is_(None))
        .order_by(m.AuditEvent.id.desc()).limit(1)
    )
    prev = last.hash if last else GENESIS
    created = m.utcnow().replace(microsecond=0)
    h = hashlib.sha256((prev + _canonical(case_id, actor, actor_role, action, details, created, prev)).encode()).hexdigest()
    ev = m.AuditEvent(case_id=case_id, actor=actor, actor_role=actor_role, action=action, details=details,
                      trace_id=current_trace_id(), created_at=created, prev_hash=prev, hash=h)
    db.add(ev)
    db.flush()
    return ev


def verify(db: Session, case_id: str) -> dict:
    rows = db.scalars(select(m.AuditEvent).where(m.AuditEvent.case_id == case_id).order_by(m.AuditEvent.id)).all()
    prev = GENESIS
    for r in rows:
        expect = hashlib.sha256((prev + _canonical(r.case_id, r.actor, r.actor_role, r.action, r.details,
                                                   r.created_at.replace(microsecond=0), prev)).encode()).hexdigest()
        if r.prev_hash != prev or r.hash != expect:
            return {"valid": False, "events": len(rows), "broken_at": r.id}
        prev = r.hash
    return {"valid": True, "events": len(rows), "head": prev}


def to_dict(e: m.AuditEvent) -> dict:
    return {"id": e.id, "case_id": e.case_id, "actor": e.actor, "actor_role": e.actor_role, "action": e.action,
            "details": e.details, "trace_id": e.trace_id, "created_at": e.created_at.isoformat() + "Z", "hash": e.hash,
            "prev_hash": e.prev_hash}
