"""Customer dispute intake (customer portal): the customer's payments, raising a dispute, following it.

What a customer sees is deliberately limited: their own accounts and payments, their own disputes, the
status in plain words, deadlines, what the bank has asked them for, and what they uploaded. Never internal
risk signals, other people's accounts, staff notes, AI reports or decision rationales.
"""
from __future__ import annotations

import re
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.services import dlp
from app.services.trace import fmt_amount

LIST_DAYS = 120
FRAUD_REASONS = {"unauthorised", "account_access", "scam", "card_online"}
# Fixed answers shared by the form and the chat, so every dispute maps cleanly into the bank's case file.
OTP_OPTIONS = {"yes": "Yes, I shared one", "no": "No, I didn't share any", "not_sure": "I'm not sure"}
NOTICED_OPTIONS = {"today": "Today", "yesterday": "Yesterday", "2_7_days": "2–7 days ago", "over_week": "More than a week ago"}
CONTACT_OPTIONS = {"sms": "SMS", "email": "Email", "phone": "Phone call"}

# key -> (what the customer sees, a short help line, internal category)
REASONS: dict[str, tuple[str, str, str]] = {
    "unauthorised": ("I didn't make or allow this payment", "Money left your account and you did not make or approve the payment.",
                     "unauthorised_transfer"),
    "account_access": ("Someone got into my account or banking app", "Someone else signed in to your banking and moved money.",
                       "account_takeover"),
    "scam": ("I was tricked into making this payment", "You made the payment yourself, but someone deceived you (fake job, KYC call, "
             "investment, seller).", "app_scam"),
    "card_online": ("My card was used online without my permission", "Your card was charged for an online purchase you did not make.",
                    "card_not_present"),
    "not_received": ("I paid but didn't get what I paid for", "Goods or a service you paid for never arrived, or were not as described.",
                     "merchant_dispute"),
    "charged_wrong": ("I was charged twice or the wrong amount", "A duplicate or wrong debit, or a failed payment where money was still taken.",
                      "processing_error"),
}

STATUS_PLAIN = {
    "new": ("Received", 1, "We have your dispute and will start looking into it shortly."),
    "triage": ("Received", 1, "We have your dispute and will start looking into it shortly."),
    "investigating": ("Being investigated", 2, "Our team is checking the payment and where the money went."),
    "awaiting_evidence": ("We need something from you", 2, "Please send the items listed below so we can continue."),
    "ready_for_review": ("Final review", 3, "The investigation is complete and a decision is being made."),
    "escalated": ("With a senior team", 3, "A senior team is reviewing your dispute."),
    "resolved": ("Decided", 4, "A decision has been made on your dispute."),
}
STEPS = ["Received", "Being investigated", "Final review", "Decided"]
DECISION_PLAIN = {
    "uphold_claim": "Your claim was accepted.",
    "partial": "Your claim was partly accepted.",
    "decline_claim": "Your claim was not accepted. If you disagree, you can ask us to review the decision.",
    "refer": "Your dispute has been passed to a senior team.",
}
REQUEST_PLAIN = {
    "customer_evidence": "A receipt, screenshot or bank SMS of the payment",
    "cyber_complaint_ack": "Your cyber-crime complaint acknowledgement (from 1930 or cybercrime.gov.in)",
    "communication_trail": "Messages or call details from the person who contacted you",
    "merchant_response": "Your order details or messages with the seller",
}
MILESTONE_PLAIN = {"shadow_credit": "Temporary credit to your account (if eligible)", "resolution": "Decision on your dispute",
                   "hold_request": "Our request to the receiving bank to hold the money"}


def _name(label: str | None) -> str:
    return re.sub(r"\s*\(synthetic\)\s*$", "", label or "").strip() or "Unknown"


def customer_of(user: m.User) -> str:
    if user.role != "customer" or not user.customer_id:
        raise HTTPException(403, "This page is for bank customers")
    return user.customer_id


def own_account_ids(db: Session, customer_id: str) -> list[str]:
    return list(db.scalars(select(m.Account.id).where(m.Account.customer_id == customer_id)))


def profile(db: Session, user: m.User) -> dict:
    cid = customer_of(user)
    cust = db.get(m.Customer, cid)
    accounts = db.scalars(select(m.Account).where(m.Account.customer_id == cid)).all()
    return {"customer_id": cid, "name": _name(cust.display_name if cust else user.full_name), "is_synthetic": bool(cust and cust.is_synthetic),
            "accounts": [{"id": a.id, "label": _name(a.holder_label), "masked_number": a.masked_number, "kind": a.kind} for a in accounts],
            "reasons": [{"key": k, "label": v[0], "help": v[1], "asks_otp": k in FRAUD_REASONS} for k, v in REASONS.items()],
            "options": {"otp_shared": OTP_OPTIONS, "noticed": NOTICED_OPTIONS, "contact_preference": CONTACT_OPTIONS}}


def _txn_card(db: Session, t: m.Transaction, disputed: dict[str, str]) -> dict:
    payee = db.get(m.Account, t.credit_account_id)
    return {"id": t.id, "amount_minor": t.amount_minor, "currency": t.currency, "amount": fmt_amount(t.amount_minor, t.currency),
            "paid_to": _name(payee.holder_label) if payee else "Unknown", "paid_to_bank": payee.institution.name if payee and payee.institution else None,
            "channel": t.channel, "reference": t.reference, "status": t.status, "occurred_at": t.occurred_at.isoformat() + "Z",
            "from_account": t.debit_account_id, "dispute_case_id": disputed.get(t.id)}


def transactions(db: Session, user: m.User, q: str | None = None, limit: int = 60) -> list[dict]:
    """The customer's recent outgoing payments (newest first), with any dispute already raised on each."""
    cid = customer_of(user)
    accts = own_account_ids(db, cid)
    if not accts:
        return []
    since = m.utcnow() - timedelta(days=LIST_DAYS)
    rows = db.scalars(select(m.Transaction).where(m.Transaction.debit_account_id.in_(accts), m.Transaction.occurred_at >= since)
                      .order_by(m.Transaction.occurred_at.desc()).limit(500)).all()
    disputed = dict(db.execute(select(m.DisputeCase.disputed_txn_id, m.DisputeCase.id).where(m.DisputeCase.customer_id == cid)).all())
    cards = [_txn_card(db, t, disputed) for t in rows]
    if q:
        ql = q.strip().lower()
        digits = re.sub(r"[^\d]", "", ql)
        cards = [c for c in cards if ql in c["paid_to"].lower() or (c["reference"] and ql in c["reference"].lower())
                 or (digits and digits in str(c["amount_minor"] // 100))]
    return cards[:limit]


def own_transaction(db: Session, user: m.User, txn_id: str) -> m.Transaction:
    t = db.get(m.Transaction, txn_id)
    if t is None or t.debit_account_id not in own_account_ids(db, customer_of(user)):
        raise HTTPException(404, "Payment not found in your accounts")
    return t


def _next_case_id(db: Session) -> str:
    nums = [int(x[5:]) for x in db.scalars(select(m.DisputeCase.id)) if re.fullmatch(r"CASE-\d+", x)]
    return f"CASE-{max(nums, default=24000) + 1}"


def create_dispute(db: Session, user: m.User, body: dict, channel: str) -> dict:
    """Raise a dispute from the customer portal (form or chat). The customer confirms before this is called."""
    from app.seed.loader import refresh_case_assessments

    cid = customer_of(user)
    t = own_transaction(db, user, body.get("txn_id") or "")
    reason = body.get("reason")
    if reason not in REASONS:
        raise HTTPException(422, "Choose what happened")
    description = (body.get("description") or "").strip()
    if not 20 <= len(description) <= 2000:
        raise HTTPException(422, "Please describe what happened in at least 20 characters")
    if not body.get("declaration"):
        raise HTTPException(422, "Please confirm the declaration")
    existing = db.scalar(select(m.DisputeCase.id).where(m.DisputeCase.disputed_txn_id == t.id, m.DisputeCase.customer_id == cid))
    if existing:
        raise HTTPException(409, f"You have already raised a dispute for this payment: {existing}")
    otp = body.get("otp_shared")
    if reason in FRAUD_REASONS and otp not in OTP_OPTIONS:
        raise HTTPException(422, "Tell us whether you shared an OTP, PIN or password")
    if reason not in FRAUD_REASONS:
        otp = None
    cyber = (body.get("cyber_complaint_ref") or "").strip()[:40] or None
    if cyber and not re.fullmatch(r"[A-Za-z0-9/\-_. ]{4,40}", cyber):
        raise HTTPException(422, "The complaint number can only contain letters, numbers and - / .")
    contact = body.get("contact_preference")
    if contact not in CONTACT_OPTIONS:
        raise HTTPException(422, "Choose how we should contact you")
    noticed = body.get("noticed")
    if noticed not in NOTICED_OPTIONS:
        raise HTTPException(422, "Choose when you noticed the payment")
    if reason not in FRAUD_REASONS:
        cyber = None
    language = body.get("language") if body.get("language") in ("en", "hi") else "en"

    masked_text, masked = dlp.mask(description)  # OTPs, PINs and card numbers never reach the case file
    category = REASONS[reason][2]
    now = m.utcnow()
    case = None
    for _ in range(3):  # two submissions at once could pick the same number
        case_id = _next_case_id(db)
        if db.get(m.DisputeCase, case_id) is None:
            case = m.DisputeCase(id=case_id, disputed_txn_id=t.id, customer_id=cid, category=category, category_source="customer",
                                 allegation=masked_text, allegation_language=language, status="new", priority="P3", reported_at=now,
                                 is_synthetic=t.is_synthetic, channel=channel,
                                 intake={"reason": reason, "otp_shared": otp, "noticed": noticed, "cyber_complaint_ref": cyber,
                                         "contact_preference": contact, "declaration": True, "submitted_at": now.isoformat() + "Z"})
            db.add(case)
            db.flush()
            break
    if case is None:
        raise HTTPException(409, "Please try again")
    audit.record(db, case.id, user.username, "customer", "case_created",
                 {"source": "customer portal", "channel": channel, "disputed_txn_id": t.id, "reason": reason,
                  "dlp_masked": [{"type": f["type"], "count": f["count"]} for f in masked]})
    refresh_case_assessments(db, [case.id])
    return {**dispute_view(db, user, case), "masked": masked}


def _visible_events(db: Session, case: m.DisputeCase, user: m.User) -> list[dict]:
    rows = db.scalars(select(m.AuditEvent).where(m.AuditEvent.case_id == case.id).order_by(m.AuditEvent.id)).all()
    out = []
    for e in rows:
        d = e.details or {}
        if e.action in ("case_created", "evidence_received") and not out:
            out.append({"at": e.created_at, "text": "You raised this dispute." if e.actor == user.username else "Your dispute was received."})
        elif e.action == "evidence_uploaded" and e.actor == user.username:
            out.append({"at": e.created_at, "text": f"You sent “{d.get('filename', 'a file')}”."})
        elif e.action == "evidence_requested" and d.get("from", "customer") == "customer":
            out.append({"at": e.created_at, "text": f"We asked you for: {REQUEST_PLAIN.get(d.get('checklist_key'), 'more information')}."})
        elif e.action == "status_changed" and d.get("to") in STATUS_PLAIN:
            out.append({"at": e.created_at, "text": f"Status: {STATUS_PLAIN[d['to']][0]}."})
        elif e.action == "hold_requested":
            out.append({"at": e.created_at, "text": "We asked for money to be held while we investigate."})
        elif e.action == "decision_recorded":
            out.append({"at": e.created_at, "text": DECISION_PLAIN.get(d.get("decision"), "A decision was recorded.")})
    return [{"at": x["at"].isoformat() + "Z", "text": x["text"]} for x in out]


def dispute_view(db: Session, user: m.User, case: m.DisputeCase) -> dict:
    from app.services.scoring import sla

    t = case.disputed_txn
    status, step, explain = STATUS_PLAIN.get(case.status, (case.status, 1, ""))
    if case.status == "resolved" and case.decision:
        explain = DECISION_PLAIN.get(case.decision, explain)
    intake = case.intake or {}
    reqs = db.scalars(select(m.EvidenceRequest).where(m.EvidenceRequest.case_id == case.id, m.EvidenceRequest.status == "open")).all()
    asks = [{"id": r.id, "checklist_key": r.checklist_key, "label": REQUEST_PLAIN.get(r.checklist_key, "More information about the payment"),
             "requested_at": r.created_at.isoformat() + "Z"} for r in reqs if (r.requested_from or "customer").lower() == "customer"]
    files = db.scalars(select(m.EvidenceItem).where(m.EvidenceItem.case_id == case.id, m.EvidenceItem.uploaded_by == user.username)
                       .order_by(m.EvidenceItem.uploaded_at)).all()
    deadlines = []
    if case.status != "resolved":
        for ms in sla(case.category, t.currency, case.reported_at, m.utcnow())["milestones"]:
            deadlines.append({"label": MILESTONE_PLAIN.get(ms["key"], ms["label"]), "due_at": ms["due_at"]})
    return {
        "case_id": case.id, "status": status, "status_key": case.status, "step": step, "steps": STEPS, "explain": explain,
        "reason": _reason_label(case), "description": case.allegation,
        "payment": _txn_card(db, t, {t.id: case.id}), "raised_at": case.reported_at.isoformat() + "Z", "channel": case.channel or "bank",
        "answers": {"otp_shared": OTP_OPTIONS.get(intake.get("otp_shared")), "noticed": NOTICED_OPTIONS.get(intake.get("noticed")),
                    "cyber_complaint_ref": intake.get("cyber_complaint_ref"),
                    "contact_preference": CONTACT_OPTIONS.get(intake.get("contact_preference"))},
        "requests": asks, "files": [{"id": f.id, "filename": f.filename, "uploaded_at": f.uploaded_at.isoformat() + "Z"} for f in files],
        "deadlines": deadlines, "timeline": _visible_events(db, case, user),
        "decision": DECISION_PLAIN.get(case.decision) if case.status == "resolved" and case.decision else None,
    }


def _reason_label(case: m.DisputeCase) -> str:
    from app.services.scoring import CATEGORIES

    key = (case.intake or {}).get("reason")
    return REASONS[key][0] if key in REASONS else CATEGORIES.get(case.category, case.category)


def own_case(db: Session, user: m.User, case_id: str) -> m.DisputeCase:
    case = db.get(m.DisputeCase, case_id)
    if case is None or case.customer_id != customer_of(user):
        raise HTTPException(404, "Dispute not found")
    return case


def list_disputes(db: Session, user: m.User) -> list[dict]:
    cid = customer_of(user)
    rows = db.scalars(select(m.DisputeCase).where(m.DisputeCase.customer_id == cid).order_by(m.DisputeCase.reported_at.desc())).all()
    open_reqs = dict(db.execute(select(m.EvidenceRequest.case_id, func.count()).where(
        m.EvidenceRequest.case_id.in_([c.id for c in rows]), m.EvidenceRequest.status == "open",
        func.lower(m.EvidenceRequest.requested_from) == "customer").group_by(m.EvidenceRequest.case_id)).all()) if rows else {}
    out = []
    for c in rows:
        status, step, _ = STATUS_PLAIN.get(c.status, (c.status, 1, ""))
        out.append({"case_id": c.id, "status": status, "step": step, "raised_at": c.reported_at.isoformat() + "Z",
                    "reason": _reason_label(c),
                    "payment": _txn_card(db, c.disputed_txn, {c.disputed_txn_id: c.id}), "needs_action": int(open_reqs.get(c.id, 0))})
    return out
