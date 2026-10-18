"""Guided dispute chat for bank customers: a conversation with fixed answers.

Every question is answered by choosing a predefined option (the payment from the customer's own list, one of
the fixed reasons, OTP shared yes/no/not sure, when noticed, contact preference). The only free text is the
customer's description and, optionally, a cyber-crime complaint number. That keeps every chat-raised dispute
mapped exactly like a form-raised one, and the chat behaves the same with or without AI.

The server is stateless: the client sends the state back with each answer. Nothing is filed until the customer
confirms the summary and the client calls the normal submission endpoint.

"Tell us in your own words" (turn_from_story): Gemini reads the customer's free-text story and suggests fixed
answers (the payment, what happened, OTP shared, when noticed) plus the description itself. Integrity is kept
because every suggestion is only a pre-fill: the customer must confirm each one with Yes / No buttons before it
becomes a real answer ("confirm_<field>" steps below); "No" drops back to the normal, fully manual question for
that field. If AI can't read the story, the chat says so and continues step by step as usual.
"""
from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as m
from app.services import dlp, intake

PAGE = 6
SLOTS = ("txn_id", "reason", "otp_shared", "noticed", "cyber_complaint_ref", "description", "contact_preference")
# Extra state carried only while a story's suggestions are being confirmed.
STORY_SLOTS = ("suggest", "declined_suggest", "payment_candidate", "payment_declined")
CONFIRM_FIELDS = ("reason", "otp_shared", "noticed", "contact_preference")
CONFIRM_PROMPTS = {
    "reason": lambda v: f"It sounds like what happened was: “{intake.REASONS[v][0]}” — is that right?",
    "otp_shared": lambda v: f"It sounds like, about this payment: “{intake.OTP_OPTIONS[v]}” — is that right?",
    "noticed": lambda v: f"It sounds like you noticed this payment: {intake.NOTICED_OPTIONS[v]} — is that right?",
    "contact_preference": lambda v: f"It sounds like you'd like us to contact you by {intake.CONTACT_OPTIONS[v]} — is that right?",
}


def _first_name(user: m.User, db: Session) -> str:
    return intake.profile(db, user)["name"].split(" ")[0]


def _pending_confirm(st: dict) -> str | None:
    """The next AI-suggested field still waiting for the customer's Yes/No, or None once they're all settled."""
    suggest = st.get("suggest") or {}
    declined = st.get("declined_suggest") or []
    reason_val = st.get("reason") or suggest.get("reason")
    fraud = reason_val in intake.FRAUD_REASONS
    for key in CONFIRM_FIELDS:
        if key in declined or st.get(key):
            continue
        if key == "otp_shared" and not fraud:
            continue
        if key in suggest:
            return key
    return None


def _next_step(st: dict) -> str:
    if st.get("payment_candidate") and not st.get("txn_id") and not st.get("payment_declined"):
        return "confirm_payment"
    if not st.get("txn_id"):
        return "payment"
    pending = _pending_confirm(st)
    if pending:
        return f"confirm_{pending}"
    fraud = st.get("reason") in intake.FRAUD_REASONS
    if not st.get("reason"):
        return "reason"
    if fraud and not st.get("otp_shared"):
        return "otp"
    if not st.get("noticed"):
        return "noticed"
    if fraud and st.get("cyber_complaint_ref") is None:
        return "cyber_ref" if st.get("cyber_pending") else "cyber"
    if not st.get("description"):
        return "description"
    if not st.get("contact_preference"):
        return "contact"
    return "summary"


def _summary(db: Session, user: m.User, st: dict) -> dict:
    t = intake.own_transaction(db, user, st["txn_id"])
    fraud = st["reason"] in intake.FRAUD_REASONS
    return {
        "payment": intake._txn_card(db, t, {}),
        "reason": intake.REASONS[st["reason"]][0],
        "otp_shared": intake.OTP_OPTIONS.get(st.get("otp_shared")) if fraud else None,
        "noticed": intake.NOTICED_OPTIONS[st["noticed"]],
        "cyber_complaint": (st.get("cyber_complaint_ref") or "Not reported yet") if fraud else None,
        "description": st["description"],
        "contact_preference": intake.CONTACT_OPTIONS[st["contact_preference"]],
    }


def _prompt(db: Session, user: m.User, st: dict) -> dict:
    """The question for the current step: text, the options to choose from, and whether free text is allowed."""
    step = _next_step(st)
    st["step"] = step
    out: dict = {"step": step, "options": [], "payments": None, "input": None, "summary": None, "ready": False}
    if step == "confirm_payment":
        t = intake.own_transaction(db, user, st["payment_candidate"])
        out["text"] = "From what you told us, we think this might be the payment — is that right?"
        out["payments"] = [intake._txn_card(db, t, {})]
        out["options"] = [{"value": "confirmyes:payment", "label": "Yes, that's the one"},
                          {"value": "confirmno:payment", "label": "No, let me choose"}]
    elif step.startswith("confirm_") and step[len("confirm_"):] in CONFIRM_FIELDS:
        field = step[len("confirm_"):]
        out["text"] = CONFIRM_PROMPTS[field]((st.get("suggest") or {})[field])
        out["options"] = [{"value": f"confirmyes:{field}", "label": "Yes, that's right"},
                          {"value": f"confirmno:{field}", "label": "No, let me choose"}]
    elif step == "payment":
        page = int(st.get("page") or 0)
        cards = [c for c in intake.transactions(db, user, limit=200) if not c["dispute_case_id"]]
        shown = cards[page * PAGE:(page + 1) * PAGE]
        out["text"] = "Which payment is this about? Here are your recent payments — choose one." if page == 0 else "Here are some older payments."
        out["payments"] = shown
        if len(cards) > (page + 1) * PAGE:
            out["options"].append({"value": "more", "label": "Show older payments"})
        if page > 0:
            out["options"].append({"value": "newer", "label": "Back to recent payments"})
        if page == 0 and not st.get("story_tried"):
            out["options"].append({"value": "story", "label": "Tell us in your own words instead"})
        if not cards:
            out["text"] = "I couldn't find any recent payments from your accounts that you can dispute here. Please contact your branch."
    elif step == "reason":
        out["text"] = "What happened with this payment?"
        out["options"] = [{"value": f"reason:{k}", "label": v[0], "help": v[1]} for k, v in intake.REASONS.items()]
    elif step == "otp":
        out["text"] = "Did you share an OTP, PIN or password with anyone around the time of this payment?"
        out["options"] = [{"value": f"otp:{k}", "label": v} for k, v in intake.OTP_OPTIONS.items()]
    elif step == "noticed":
        out["text"] = "When did you first notice this payment?"
        out["options"] = [{"value": f"noticed:{k}", "label": v} for k, v in intake.NOTICED_OPTIONS.items()]
    elif step == "cyber":
        out["text"] = ("Have you reported this to the national cyber-crime helpline (call 1930, or report at cybercrime.gov.in)? "
                       "It helps us ask other banks to hold the money.")
        out["options"] = [{"value": "cyber:yes", "label": "Yes, I have a complaint number"}, {"value": "cyber:not_yet", "label": "Not yet"}]
    elif step == "cyber_ref":
        out["text"] = "Please type the complaint (acknowledgement) number."
        out["input"] = {"kind": "complaint_ref", "placeholder": "e.g. 31810250012345", "min": 4, "max": 40}
        out["options"] = [{"value": "cyber:not_yet", "label": "I don't have it to hand"}]
    elif step == "description":
        out["text"] = ("In a few sentences, tell us what happened, in your own words. Please don't include OTPs, PINs, passwords "
                       "or full card numbers.")
        out["input"] = {"kind": "description", "placeholder": "e.g. I got a call from someone saying they were from the bank…", "min": 20, "max": 2000}
    elif step == "contact":
        out["text"] = "How should we contact you about this dispute?"
        out["options"] = [{"value": f"contact:{k}", "label": v} for k, v in intake.CONTACT_OPTIONS.items()]
    else:
        out["text"] = "Please check the details. If everything is right, confirm the declaration and submit."
        out["summary"] = _summary(db, user, st)
        out["ready"] = True
        out["options"] = [{"value": "change:txn_id", "label": "Change the payment"}, {"value": "change:reason", "label": "Change what happened"},
                          {"value": "change:description", "label": "Change the description"},
                          {"value": "change:contact_preference", "label": "Change how we contact you"}]
    return out


def turn(db: Session, user: m.User, state: dict | None, choice: str | None = None, text: str | None = None) -> dict:
    """Apply one answer (a chosen option, or text where the step allows it) and return the next question."""
    st = {k: v for k, v in (state or {}).items() if k in SLOTS + STORY_SLOTS + ("page", "cyber_pending", "step", "story_tried")}
    said: list[str] = []
    masked: list[dict] = []
    step = _next_step(st)
    if not state:
        said.append(f"Hello {_first_name(user, db)}. I'll help you raise a dispute about a payment from your account. "
                    "It takes about two minutes, and nothing is sent until you confirm at the end.")
    elif choice:
        kind, _, val = choice.partition(":")
        if choice == "story" and step == "payment":
            st["story_tried"] = True  # the client switches to the free-text box and calls turn_from_story instead
        elif kind == "confirmyes" and step == f"confirm_{val}" and val == "payment":
            st["txn_id"] = st.pop("payment_candidate")
        elif kind == "confirmno" and step == f"confirm_{val}" and val == "payment":
            st["payment_declined"] = True
            said.append("No problem, pick it from the list below.")
        elif kind == "confirmyes" and step == f"confirm_{val}" and val in CONFIRM_FIELDS:
            st[val] = (st.get("suggest") or {}).pop(val)
            if val == "reason" and st[val] not in intake.FRAUD_REASONS:
                st.pop("otp_shared", None)
                (st.get("suggest") or {}).pop("otp_shared", None)
        elif kind == "confirmno" and step == f"confirm_{val}" and val in CONFIRM_FIELDS:
            (st.get("suggest") or {}).pop(val, None)
            st["declined_suggest"] = list({*st.get("declined_suggest", []), val})
        elif choice == "more" and step == "payment":
            st["page"] = int(st.get("page") or 0) + 1
        elif choice == "newer" and step == "payment":
            st["page"] = 0
        elif kind == "txn" and step == "payment":
            t = intake.own_transaction(db, user, val)  # 404 if it is not the customer's payment
            existing = intake.transactions(db, user, limit=500)
            dup = next((c["dispute_case_id"] for c in existing if c["id"] == t.id and c["dispute_case_id"]), None)
            if dup:
                said.append(f"You already raised a dispute for that payment ({dup}). You can follow it under My disputes.")
            else:
                st["txn_id"] = t.id
        elif kind == "reason" and step == "reason" and val in intake.REASONS:
            st["reason"] = val
            if val not in intake.FRAUD_REASONS:
                st.pop("otp_shared", None)
                st.pop("cyber_complaint_ref", None)
                st.pop("cyber_pending", None)
        elif kind == "otp" and step == "otp" and val in intake.OTP_OPTIONS:
            st["otp_shared"] = val
            if val == "yes":
                said.append("Thank you for telling us. Sharing an OTP doesn't stop you raising a dispute — we look at everything.")
        elif kind == "noticed" and step == "noticed" and val in intake.NOTICED_OPTIONS:
            st["noticed"] = val
        elif kind == "cyber" and step in ("cyber", "cyber_ref"):
            if val == "yes":
                st["cyber_pending"] = True
            else:
                st["cyber_complaint_ref"] = ""
                st.pop("cyber_pending", None)
                said.append("Please call 1930 or report at cybercrime.gov.in as soon as you can — you can add the number to your dispute later.")
        elif kind == "contact" and step == "contact" and val in intake.CONTACT_OPTIONS:
            st["contact_preference"] = val
        elif kind == "change" and step == "summary" and val in SLOTS:
            st.pop(val, None)
            if val == "reason":  # the follow-up questions depend on the reason
                for k in ("otp_shared", "cyber_complaint_ref", "cyber_pending"):
                    st.pop(k, None)
            if val == "txn_id":
                st["page"] = 0
        else:
            said.append("Please choose one of the options below.")
    elif text is not None:
        t = text.strip()
        if step == "description":
            if len(t) < 20:
                said.append("Please write a little more — at least 20 characters — so our team understands what happened.")
            else:
                t, masked = dlp.mask(t[:2000])
                st["description"] = t
                if masked:
                    said.append("For your safety I've hidden what looked like an OTP, PIN or card number. "
                                "Never share these with anyone, including the bank.")
        elif step == "cyber_ref":
            if re.fullmatch(r"[A-Za-z0-9/\-_. ]{4,40}", t):
                st["cyber_complaint_ref"] = t
                st.pop("cyber_pending", None)
            else:
                said.append("That doesn't look like a complaint number. Use only letters, numbers and - / . (4 to 40 characters).")
        else:
            said.append("Please choose one of the options below.")
    else:
        raise HTTPException(422, "Send a choice or text")
    nxt = _prompt(db, user, st)
    return {"state": st, "messages": said + [nxt.pop("text")], "masked": masked, **nxt}


def turn_from_story(db: Session, user: m.User, story: str) -> dict:
    """Start (or restart) the chat from a free-text story. The story is DLP-masked and becomes the description
    outright; Gemini only suggests the fixed-option answers and which payment it might be, and every suggestion
    still needs the customer's Yes/No before it counts (see module docstring). If AI can't read the story, this
    behaves like starting the guided chat normally, with a note that free text isn't available right now."""
    from app.ai import customer_assistant

    masked, found = dlp.mask(story.strip()[:2000])
    st: dict = {"story_tried": True}
    said = [f"Hello {_first_name(user, db)}, thanks for telling me in your own words."]
    if found:
        said.append("For your safety I've hidden what looked like an OTP, PIN or card number. Never share these with anyone, "
                    "including the bank.")
    if len(masked) < 20:
        said.append("Please tell me a little more — at least a sentence or two — and I'll pre-fill what I can; otherwise we'll go "
                    "through it step by step.")
        nxt = _prompt(db, user, st)
        return {"state": st, "messages": said + [nxt.pop("text")], "masked": found, **nxt}
    st["description"] = masked
    extracted = customer_assistant.extract_story(db, user, masked)
    if extracted is None:
        said.append("I can't use AI to read your story right now, so let's go through it step by step instead.")
    else:
        if extracted["suggest"]:
            st["suggest"] = extracted["suggest"]
        hints = extracted["hints"]
        if hints:
            cards = [c for c in intake.transactions(db, user, limit=200) if not c["dispute_case_id"]]
            ranked, matched = customer_assistant.rank_payments(cards, hints)
            if matched:
                st["payment_candidate"] = matched[0]
        if st.get("suggest") or st.get("payment_candidate"):
            said.append("I've guessed a few answers from what you told us — please confirm each one, or tell me I got it wrong.")
        else:
            said.append("I couldn't tell enough from that to guess any answers, so let's go through it step by step.")
    nxt = _prompt(db, user, st)
    return {"state": st, "messages": said + [nxt.pop("text")], "masked": found, **nxt}
