"""Case assistant: the chat bubble on every case.

It answers questions about the case (cited, validated like report claims) and can edit the latest AI report on the
investigator's request — clear or restore a section, remove statements. Edits go into a draft that a person saves on
the AI report tab; the assistant never saves.

Safeguards:
- A report edit happens only when the user's own message asks for one (edit words such as "clear", "remove",
  "restore"). An edit suggested by the model for any other message is ignored, so text inside a customer document
  cannot change the report.
- Plain commands ("clear the limitations section", "remove C07", "restore risk indicators") are understood without
  the model, so editing works even when AI is unavailable.
"""
from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.ai import prompts, validator
from app.ai.llm import get_gateway
from app.ai.schemas import SECTION_TITLES, AssistantTurn
from app.ai.snapshot import build_snapshot, referenced_records, snapshot_json
from app.services import report_drafts
from app.services.dlp import redact_for_llm
from app.services.investigation import build_context

EDIT_WORDS = re.compile(r"\b(clear|remove|delete|drop|erase|empty|wipe|get rid of|take out|strike|restore|undo|bring back|put back)\b", re.I)
RESTORE_WORDS = re.compile(r"\b(restore|undo|bring back|put back)\b", re.I)
CLAIM_ID = re.compile(r"\bC\d{2,3}\b", re.I)
MAX_HISTORY = 6


def _latest_report(db: Session, case_id: str) -> m.Report | None:
    return db.scalar(select(m.Report).where(m.Report.case_id == case_id).order_by(m.Report.version.desc()).limit(1))


def parse_command(message: str) -> dict | None:
    """A plain report-edit command, understood without the model. None if the message is not an edit request."""
    if not EDIT_WORDS.search(message):
        return None
    ids = sorted({x.upper() for x in CLAIM_ID.findall(message)})
    if ids and not RESTORE_WORDS.search(message):
        return {"op": "remove_claims", "claim_ids": ids}
    key = report_drafts.section_from_text(message)
    if key:
        return {"op": "restore_section" if RESTORE_WORDS.search(message) else "clear_section", "section_key": key}
    return {"op": "unclear"}


def _outline(report: m.Report, draft: m.ReportDraft | None) -> str:
    sections = draft.sections if draft else report.sections
    lines = []
    for s in sections:
        lines.append(f"[{s['key']}] {s['title']}" + (" (cleared in draft)" if s.get("cleared") else ""))
        for c in s["claims"][:20]:
            lines.append(f"  {c['id']}: {c['text'][:160]}")
    return "\n".join(lines)


def _edit(db: Session, report: m.Report | None, user: m.User, op: str, section_key: str | None, claim_ids: list[str]) -> dict:
    if report is None:
        return {"text": "There is no AI report for this case yet. Open the AI report tab and run the investigation first.",
                "navigate": {"tab": "report"}}
    try:
        r = report_drafts.apply_op(db, report, user, op, section_key=section_key, claim_ids=claim_ids, via="assistant")
    except HTTPException as exc:  # validation (unknown section, older version…): explain instead of failing the chat
        return {"text": f"I couldn't make that change: {exc.detail}."}
    tail = " Nothing is saved yet: open the AI report to review the draft and save it." if r["changed"] else ""
    return {"text": r["summary"] + tail, "action": {"kind": op, "section_key": section_key, "claim_ids": claim_ids, "changed": r["changed"]},
            "draft": r["draft"], "navigate": {"tab": "report", "section": section_key}}


def chat(db: Session, case: m.DisputeCase, user: m.User, message: str, history: list[dict] | None = None) -> dict:
    msg = (message or "").strip()
    if not 2 <= len(msg) <= 1000:
        return {"status": "invalid", "text": "Please write a message of up to 1000 characters."}
    report = _latest_report(db, case.id)
    out: dict = {"status": "ok", "claims": [], "records": {}, "follow_up_questions": []}

    cmd = parse_command(msg)
    if cmd and cmd["op"] != "unclear":
        out.update(_edit(db, report, user, cmd["op"], cmd.get("section_key"), cmd.get("claim_ids") or []))
        audit.record(db, case.id, user.username, user.role, "assistant_message", {"length": len(msg), "handled_by": "command",
                                                                                   "op": cmd["op"]})
        return out

    gw = get_gateway()
    if not gw.available():
        out.update(status="not_analysed", text="I can't answer questions right now because the AI service isn't available here. "
                   "I can still edit the AI report, for example: “clear the Limitations section”.")
        return out
    ctx = build_context(db, case)
    snap = build_snapshot(ctx, referenced_records(db, ctx))
    draft = report_drafts.open_draft(db, report) if report else None
    convo = "\n".join(f"{t.get('role', 'user')}: {str(t.get('text', ''))[:500]}" for t in (history or [])[-MAX_HISTORY:])
    contents = [f"{prompts.ASSISTANT_INSTRUCTIONS}\n\nEVIDENCE SNAPSHOT (JSON):\n{snapshot_json(snap)}\n\n"
                f"REPORT OUTLINE:\n{_outline(report, draft) if report else '(no AI report yet)'}\n\n"
                f"CONVERSATION SO FAR:\n{prompts.fence(redact_for_llm(convo))}\n\n"
                f"USER MESSAGE: {prompts.fence(redact_for_llm(msg))}"]
    res = gw.generate(node="assistant", prompt_version=prompts.ASSISTANT_V, contents=contents, schema=AssistantTurn, tier="fast",
                      system=prompts.GROUND_RULES, case_id=case.id, run_id=None, db=db)
    if not res.ok:
        audit.record(db, case.id, user.username, user.role, "assistant_message", {"length": len(msg), "status": res.status})
        out.update(status="not_analysed", text=f"Sorry, I couldn't answer that just now ({res.not_analysed_reason}). Please try again.")
        return out
    turn: AssistantTurn = res.data
    v = validator.validate({"sections": [{"key": "known_facts", "claims": [c.model_dump(mode="json") for c in turn.claims]}],
                            "recommended_actions": []}, snap["records"])
    cited = sorted({c for cl in v["claims"] for c in cl.get("citations", []) if c in snap["records"]})
    out.update(claims=v["claims"], records={k: snap["records"][k] for k in cited}, insufficient_data=turn.insufficient_data,
               follow_up_questions=turn.follow_up_questions[:3], flagged=v["claims_with_errors"], model=res.model, cost_usd=res.cost_usd)
    act = turn.action
    if act.kind.value in report_drafts.OPS:
        if EDIT_WORDS.search(msg):  # only when the user asked for an edit in their own words
            key = act.section_key.value if act.section_key else None
            out.update(_edit(db, report, user, act.kind.value, key, [c.upper() for c in act.claim_ids]))
        else:
            out["ignored_action"] = act.kind.value
    elif cmd and cmd["op"] == "unclear" and not out.get("text"):
        out["text"] = "Which part of the report should I change? For example: “clear Limitations” or “remove C07”. Sections: " + \
                      ", ".join(SECTION_TITLES.values()) + "."
    if act.kind.value == "open_tab" and act.tab:
        out["navigate"] = {"tab": act.tab.value}
    audit.record(db, case.id, user.username, user.role, "assistant_message",
                 {"length": len(msg), "status": "ok", "action": act.kind.value, "flagged": v["claims_with_errors"]})
    return out
