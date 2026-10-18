"""Ledger ingest endpoints: Pub/Sub push (machine-to-machine) and statement upload (admin)."""
import base64
import binascii
import hashlib
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.config import get_settings
from app.db import get_db
from app.security import require_role
from app.services.ingest import event_dict, ingest
from app.services.ledger_sources import FORMATS, FormatError, MAX_BYTES, parse, safe_identifier

router = APIRouter(prefix="/api/ingest", tags=["ingest"])
log = logging.getLogger("fundtrace.ingest")


def verify_pubsub_push(request: Request) -> str:
    """Accept only pushes signed by Google for our subscription's service account (OIDC token)."""
    s = get_settings()
    if not s.pubsub_push_audience:
        raise HTTPException(404, "Not found")
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Missing push token")
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    try:
        claims = id_token.verify_oauth2_token(auth[7:], g_requests.Request(), audience=s.pubsub_push_audience)
    except Exception:
        raise HTTPException(401, "Invalid push token")
    email = claims.get("email")
    if not claims.get("email_verified") or not email or (s.pubsub_push_service_account and email != s.pubsub_push_service_account):
        raise HTTPException(403, "Push token is not from the expected service account")
    return email


@router.post("/pubsub", status_code=204)
async def pubsub_push(request: Request, pusher: str = Depends(verify_pubsub_push), db: Session = Depends(get_db)):
    """Pub/Sub push delivery. 2xx acknowledges; any other status makes Pub/Sub redeliver.

    Malformed messages are recorded as rejected and acknowledged (redelivery would not fix them);
    database errors return 500 so the message is retried.
    """
    try:
        envelope = await request.json()
        msg = envelope["message"]
        message_id = str(msg.get("messageId") or msg.get("message_id"))
        attrs = msg.get("attributes") or {}
    except Exception:
        raise HTTPException(400, "Not a Pub/Sub push envelope")
    if not message_id or message_id == "None":
        raise HTTPException(400, "Message id missing")
    fmt = attrs.get("format", "fundtrace.v1")
    source = safe_identifier(attrs.get("source_system")) or "pubsub"
    try:
        data = base64.b64decode(msg.get("data") or "", validate=True)
        records = parse(fmt, data, source)
    except (binascii.Error, FormatError) as exc:
        ingest(db, [], source_system=source, fmt=fmt, channel="pubsub", message_id=f"pubsub:{message_id}", received_by=pusher,
               error=str(exc))
        db.commit()
        log.warning("pubsub message %s rejected: %s", message_id, type(exc).__name__)
        return Response(status_code=204)
    ingest(db, records, source_system=source, fmt=fmt, channel="pubsub", message_id=f"pubsub:{message_id}", received_by=pusher)
    db.commit()
    return Response(status_code=204)


@router.post("/file")
async def upload_statement(file: UploadFile = File(...), format: str = Form(...), source_system: str = Form("core"),
                           user: m.User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    """Load a statement or record file delivered outside Pub/Sub (e.g. an SFTP drop). Admin only."""
    if format not in FORMATS:
        raise HTTPException(422, f"Unknown format; use one of {', '.join(FORMATS)}")
    source = safe_identifier(source_system)
    if source is None:
        raise HTTPException(422, "source_system must be a short identifier")
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large (max 10 MB)")
    try:
        records = parse(format, data, source)
    except FormatError as exc:
        raise HTTPException(422, str(exc))
    message_id = "upload:" + hashlib.sha256(data).hexdigest()
    ev, again = ingest(db, records, source_system=source, fmt=format, channel="upload", message_id=message_id, received_by=user.username)
    db.commit()
    return {"event": event_dict(ev), "already_processed": again}


@router.get("/events")
def events(limit: int = 50, user: m.User = Depends(require_role("supervisor", "admin")), db: Session = Depends(get_db)):
    rows = db.scalars(select(m.IngestEvent).order_by(m.IngestEvent.id.desc()).limit(max(1, min(limit, 200)))).all()
    s = get_settings()
    return {"events": [event_dict(e) for e in rows], "formats": FORMATS, "pubsub_enabled": bool(s.pubsub_push_audience)}
