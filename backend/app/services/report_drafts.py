"""Report drafts: unsaved edits to an AI report, made by an investigator directly or through the case assistant.

A saved report version never changes. Edits collect in one open draft per report (shared by everyone working the
case, with who/what/how recorded per change). Nothing reaches the report until a person saves the draft on the
AI report tab, which creates the next version, keeps the verdicts of the claims that remain and recomputes the
counts. Edits only remove or restore content, so a saved draft never contains text that was not checked.
"""
from __future__ import annotations

import re
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.ai.schemas import SECTION_TITLES

OPS = ("clear_section", "restore_section", "remove_claims")
# words people use for a section, mapped to its key
SECTION_WORDS = {
    "case_overview": ["case overview", "overview", "summary"],
    "known_facts": ["known facts", "facts"],
    "transaction_trail": ["transaction trail", "trail", "money trail", "transactions"],
    "risk_indicators": ["risk indicators", "risk signals", "risks", "risk", "red flags"],
    "supporting_evidence": ["supporting evidence", "evidence supporting", "supporting"],
    "contradicting_evidence": ["contradicting evidence", "evidence that contradicts", "contradicting", "contradictory evidence"],
    "missing_information": ["missing information", "missing info", "missing"],
    "next_actions": ["recommended next actions", "next actions", "next steps", "recommendations", "recommended actions"],
    "limitations": ["limitations and uncertainty", "limitations", "uncertainty", "caveats"],
}


def section_from_text(text: str) -> str | None:
    """The section a phrase refers to (longest matching name wins), or None."""
    t = text.lower()
    best: tuple[int, str] | None = None
    for key, words in SECTION_WORDS.items():
        for w in words + [SECTION_TITLES[key].lower(), key.replace("_", " ")]:
            if re.search(r"\b" + re.escape(w) + r"\b", t) and (best is None or len(w) > best[0]):
                best = (len(w), key)
    return best[1] if best else None


def open_draft(db: Session, report: m.Report) -> m.ReportDraft | None:
    return db.scalar(select(m.ReportDraft).where(m.ReportDraft.report_id == report.id, m.ReportDraft.status == "open")
                     .order_by(m.ReportDraft.id.desc()).limit(1))


def _sections_of(draft: m.ReportDraft | None, report: m.Report) -> list[dict]:
    return [dict(s) for s in (draft.sections if draft else report.sections)]


def apply_op(db: Session, report: m.Report, user: m.User, op: str, section_key: str | None = None,
             claim_ids: list[str] | None = None, via: str = "manual") -> dict:
    """Apply one edit to the report's open draft (creating it). Returns {"draft", "summary"}."""
    if op not in OPS:
        raise HTTPException(422, f"op must be one of {', '.join(OPS)}")
    latest = db.scalar(select(func.max(m.Report.version)).where(m.Report.case_id == report.case_id))
    if report.version != latest:
        raise HTTPException(409, f"Only the latest report (v{latest}) can be edited")
    draft = open_draft(db, report)
    sections = _sections_of(draft, report)
    by_key = {s["key"]: s for s in sections}
    original = {s["key"]: s for s in report.sections}
    if op in ("clear_section", "restore_section"):
        if section_key not in by_key:
            raise HTTPException(422, "Unknown report section")
        title = by_key[section_key]["title"]
        if op == "clear_section":
            if not by_key[section_key]["claims"] and by_key[section_key].get("cleared"):
                return {"draft": draft_dict(draft, report) if draft else None, "summary": f"“{title}” is already cleared in the draft.",
                        "changed": False}
            removed = [c["id"] for c in by_key[section_key]["claims"]]
            by_key[section_key] = {**by_key[section_key], "claims": [], "cleared": True}
            summary = f"Cleared “{title}” ({len(removed)} statement{'s' if len(removed) != 1 else ''}) in the draft."
            claim_ids = removed
        else:
            by_key[section_key] = {**original[section_key], "cleared": False}
            summary = f"Restored “{title}” in the draft."
    else:
        ids = set(claim_ids or [])
        known = {c["id"] for s in sections for c in s["claims"]}
        if not ids or not ids <= known:
            raise HTTPException(422, "Unknown statement ids")
        for k, s in by_key.items():
            by_key[k] = {**s, "claims": [c for c in s["claims"] if c["id"] not in ids]}
        summary = f"Removed {len(ids)} statement{'s' if len(ids) != 1 else ''} ({', '.join(sorted(ids))}) in the draft."
    new_sections = [by_key[s["key"]] for s in sections]
    change = {"op": op, "section_key": section_key, "claim_ids": sorted(claim_ids or []), "by": user.username, "via": via,
              "at": m.utcnow().isoformat() + "Z"}
    if draft is None:
        draft = m.ReportDraft(report_id=report.id, case_id=report.case_id, sections=new_sections, changes=[change],
                              status="open", created_by=user.username)
        db.add(draft)
    else:
        draft.sections, draft.changes = new_sections, list(draft.changes or []) + [change]
    db.flush()
    audit.record(db, report.case_id, user.username, user.role, "report_draft_edited",
                 {"report_id": report.id, "op": op, "section_key": section_key, "claim_ids": change["claim_ids"], "via": via})
    return {"draft": draft_dict(draft, report), "summary": summary, "changed": True}


def save_draft(db: Session, report: m.Report, user: m.User) -> m.Report:
    """Turn the open draft into the next report version (review starts again)."""
    from app.ai.investigator import report_status

    draft = open_draft(db, report)
    if draft is None:
        raise HTTPException(409, "There are no unsaved changes")
    claims = [c for s in draft.sections for c in s["claims"]]
    n = len(claims)
    flagged = sum(1 for c in claims if c.get("flagged"))
    supported = sum(1 for c in claims if not c.get("flagged") and c.get("verdict") in ("supported", "system_generated"))
    partial = sum(1 for c in claims if not c.get("flagged") and c.get("verdict") == "partial")
    hallucinated = sum(1 for c in claims if c.get("hallucination"))
    unjudged = sum(1 for c in claims if c.get("verdict") == "unjudged")
    ai = report.generator != "deterministic"
    base = report.metrics or {}
    judge_status = "ok" if ai and not unjudged else base.get("judge_status")
    metrics = {**base, "claims_total": n, "claims_supported": supported, "claims_partial": partial, "claims_flagged": flagged,
               "claims_unjudged": unjudged, "hallucinated_claims": hallucinated, "judge_status": judge_status,
               "hallucination_rate": round(hallucinated / n, 4) if ai and n else (0.0 if ai else None),
               "confidence": round((supported + 0.5 * partial) / n, 4) if ai and n else (0.0 if ai else None),
               "edited_from": {"report_id": report.id, "version": report.version}, "edits": draft.changes,
               "cost_usd": 0.0, "ai_calls": 0}
    version = (db.scalar(select(func.max(m.Report.version)).where(m.Report.case_id == report.case_id)) or 0) + 1
    rep = m.Report(id="RPT-" + uuid.uuid4().hex[:8].upper(), case_id=report.case_id, run_id=report.run_id, version=version,
                   status=report_status(report.generator, flagged, n, judge_status), generator=report.generator,
                   sections=draft.sections, recommended_actions=report.recommended_actions, metrics=metrics, claims_total=n,
                   claims_supported=supported, claims_flagged=flagged, hallucination_rate=metrics["hallucination_rate"],
                   confidence=metrics["confidence"], snapshot_hash=report.snapshot_hash, trace_id=report.trace_id)
    db.add(rep)
    draft.status, draft.saved_report_id = "saved", rep.id
    db.flush()
    audit.record(db, report.case_id, user.username, user.role, "report_draft_saved",
                 {"from_report_id": report.id, "report_id": rep.id, "version": version, "changes": len(draft.changes or []),
                  "claims": n})
    return rep


def discard_draft(db: Session, report: m.Report, user: m.User) -> None:
    draft = open_draft(db, report)
    if draft is None:
        raise HTTPException(409, "There are no unsaved changes")
    draft.status = "discarded"
    db.flush()
    audit.record(db, report.case_id, user.username, user.role, "report_draft_discarded",
                 {"report_id": report.id, "changes": len(draft.changes or [])})


def draft_dict(draft: m.ReportDraft | None, report: m.Report) -> dict | None:
    if draft is None:
        return None
    before = sum(len(s["claims"]) for s in report.sections)
    after = sum(len(s["claims"]) for s in draft.sections)
    return {"id": draft.id, "report_id": report.id, "base_version": report.version, "sections": draft.sections,
            "changes": draft.changes or [], "claims_before": before, "claims_after": after,
            "created_by": draft.created_by, "updated_at": draft.updated_at.isoformat() + "Z" if draft.updated_at else None}
