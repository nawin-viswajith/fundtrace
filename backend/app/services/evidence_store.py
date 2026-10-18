"""Storing an uploaded evidence file — the same checks whether staff or the customer uploads it.

Type-sniffed against an allow-list, size-capped, SHA-256 hashed, written once to storage, scanned for
sensitive data (types and counts only) and audited. An open evidence request for the same checklist item is
marked received.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.config import get_settings
from app.services import dlp
from app.services.storage import StorageError, get_storage, sha256, sniff_mime

KINDS = ("customer_upload", "bank_record", "merchant_response", "complaint_ack")


async def read_upload(file: UploadFile) -> bytes:
    s = get_settings()
    data = await file.read(s.max_upload_bytes + 1)
    if len(data) > s.max_upload_bytes:
        raise HTTPException(413, f"File too large (max {s.max_upload_bytes // (1024 * 1024)} MB)")
    if not data:
        raise HTTPException(422, "Empty file")
    return data


def store_evidence(db: Session, case: m.DisputeCase, data: bytes, filename: str | None, content_type: str | None, *,
                   kind: str, checklist_key: str | None, actor: str, actor_role: str) -> m.EvidenceItem:
    if kind not in KINDS:
        raise HTTPException(422, "Unknown evidence kind")
    try:
        mime = sniff_mime(data, content_type, filename or "")
    except StorageError as exc:
        raise HTTPException(415, str(exc))
    uri = get_storage().put(data, case.id, mime)
    eid = "EV-" + uuid.uuid4().hex[:8].upper()
    name = (filename or "upload").replace("/", "_").replace("\\", "_")[:200]
    scan = dlp.scan_file(data, mime)
    digest = sha256(data)
    item = m.EvidenceItem(id=eid, case_id=case.id, kind=kind, checklist_key=checklist_key, filename=name, mime=mime, sha256=digest,
                          storage_uri=uri, size=len(data), uploaded_by=actor, analysis_status="not_analysed", is_synthetic=False, dlp=scan)
    db.add(item)
    if checklist_key:
        for req in db.scalars(select(m.EvidenceRequest).where(m.EvidenceRequest.case_id == case.id, m.EvidenceRequest.status == "open",
                                                              m.EvidenceRequest.checklist_key == checklist_key)).all():
            req.status = "received"
    db.flush()
    audit.record(db, case.id, actor, actor_role, "evidence_uploaded",
                 {"evidence_id": eid, "filename": name, "sha256": digest, "size": len(data), "mime": mime, "dlp_status": scan["status"],
                  "dlp_findings": [{"type": f["type"], "count": f["count"]} for f in scan["findings"]]})
    return item
