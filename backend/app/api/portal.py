"""Customer portal API: a bank customer raises disputes (form or guided chat) and follows them.

Only logins with role "customer" (linked to a customer record) can use these routes, and every route works on
that customer's own accounts, payments and disputes. Customer logins cannot reach any staff route
(see security.current_user).
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import models as m
from app.ai import customer_assistant
from app.db import get_db
from app.security import require_role
from app.services import intake, intake_chat
from app.services.evidence_store import read_upload, store_evidence

router = APIRouter(prefix="/api/portal", tags=["customer portal"])
customer = require_role("customer")


@router.get("/me")
def me(user: m.User = Depends(customer), db: Session = Depends(get_db)):
    return intake.profile(db, user)


@router.get("/transactions")
def transactions(q: str | None = None, user: m.User = Depends(customer), db: Session = Depends(get_db)):
    if q is not None and len(q) > 64:
        raise HTTPException(422, "Search is too long")
    return {"transactions": intake.transactions(db, user, q=q)}


class DisputeIn(BaseModel):
    txn_id: str = Field(max_length=32)
    reason: str = Field(max_length=32)
    description: str = Field(max_length=2000)
    otp_shared: str | None = Field(default=None, max_length=16)
    noticed: str = Field(max_length=16)
    cyber_complaint_ref: str | None = Field(default=None, max_length=40)
    contact_preference: str = Field(max_length=8)
    language: str | None = Field(default="en", max_length=4)
    declaration: bool = False
    channel: str = Field(default="portal_form", pattern="^(portal_form|portal_chat)$")


@router.post("/disputes")
def raise_dispute(body: DisputeIn, user: m.User = Depends(customer), db: Session = Depends(get_db)):
    out = intake.create_dispute(db, user, body.model_dump(), channel=body.channel)
    db.commit()
    return out


@router.get("/disputes")
def my_disputes(user: m.User = Depends(customer), db: Session = Depends(get_db)):
    return {"disputes": intake.list_disputes(db, user)}


@router.get("/disputes/{case_id}")
def my_dispute(case_id: str, user: m.User = Depends(customer), db: Session = Depends(get_db)):
    return intake.dispute_view(db, user, intake.own_case(db, user, case_id))


@router.post("/disputes/{case_id}/evidence")
async def add_evidence(case_id: str, file: UploadFile = File(...), checklist_key: str | None = Form(None),
                       user: m.User = Depends(customer), db: Session = Depends(get_db)):
    case = intake.own_case(db, user, case_id)
    if case.status == "resolved":
        raise HTTPException(409, "This dispute has been decided; contact us to add more")
    if checklist_key not in (None, *intake.REQUEST_PLAIN):
        raise HTTPException(422, "Unknown item")
    data = await read_upload(file)
    store_evidence(db, case, data, file.filename, file.content_type, kind="customer_upload",
                   checklist_key=checklist_key or "customer_evidence", actor=user.username, actor_role="customer")
    db.commit()
    return intake.dispute_view(db, user, case)


class ChatIn(BaseModel):
    state: dict | None = None
    choice: str | None = Field(default=None, max_length=64)
    text: str | None = Field(default=None, max_length=2000)


@router.post("/chat")
def chat(body: ChatIn, user: m.User = Depends(customer), db: Session = Depends(get_db)):
    """One step of the guided dispute chat (fixed options; free text only for the description and complaint number)."""
    return intake_chat.turn(db, user, body.state, choice=body.choice, text=body.text)


class StoryIn(BaseModel):
    story: str = Field(min_length=1, max_length=2000)


@router.post("/chat/story")
def chat_story(body: StoryIn, user: m.User = Depends(customer), db: Session = Depends(get_db)):
    """Start the guided chat from a free-text story: Gemini extracts fixed-option suggestions and payment hints for
    the customer to confirm. The chat itself is unchanged; this only pre-fills the first answers."""
    return intake_chat.turn_from_story(db, user, body.story)


class HelpIn(BaseModel):
    message: str = Field(max_length=1000)
    history: list[dict] | None = None


@router.get("/help")
def help_index(user: m.User = Depends(customer)):
    """The help articles index and suggested questions, for the help page to show before the first message."""
    return customer_assistant.help_index()


@router.post("/help/ask")
def help_ask(body: HelpIn, user: m.User = Depends(customer), db: Session = Depends(get_db)):
    """One turn of "Ask Demo Bank": banking/payments FAQ, fraud safety, and the customer's own dispute status."""
    return customer_assistant.ask(db, user, body.message, history=body.history)


@router.get("/safety-check")
def safety_check(user: m.User = Depends(customer), db: Session = Depends(get_db)):
    """Deterministic safety insights computed from the customer's own account (new payees, unusual payment size,
    failed sign-ins, new devices) plus a rotating scam-awareness tip."""
    return customer_assistant.safety_check(db, user)
