"""Evidence reading: Gemini extracts what a document shows; code reconciles it with the ledger.

Gemini never decides whether evidence "matches". It only transcribes printed values; the comparison
with the ledger record is deterministic. If Gemini is unavailable the item stays `not_analysed`.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.ai import prompts
from app.ai.llm import Gateway
from app.ai.schemas import EvidenceExtraction
from app.services.ledger import NormalisationError, to_minor
from app.services.storage import get_storage
from app.services.trace import fmt_amount
from app.telemetry import span


def analyse_item(db: Session, item: m.EvidenceItem, gateway: Gateway, actor: str = "system", run_id: str | None = None) -> dict:
    from google.genai import types  # lightweight import; only builds request parts

    case = db.get(m.DisputeCase, item.case_id)
    txn = db.get(m.Transaction, case.disputed_txn_id)
    with span("evidence.analyse", evidence_id=item.id, case_id=item.case_id):
        try:
            data = get_storage().get(item.storage_uri)
        except Exception as exc:
            item.analysis_status, item.analysis_note = "failed", f"file unavailable: {type(exc).__name__}"
            db.flush()
            return {"status": item.analysis_status, "note": item.analysis_note}
        contents = [
            types.Part.from_bytes(data=data, mime_type=item.mime),
            types.Part.from_text(text=f"{prompts.EVIDENCE_INSTRUCTIONS}\nFilename: {prompts.fence(item.filename)}"),
        ]
        res = gateway.generate(node="analyse_evidence", prompt_version=prompts.EVIDENCE_V, contents=contents, schema=EvidenceExtraction, db=db,
                               tier="fast", system=prompts.GROUND_RULES, case_id=item.case_id, run_id=run_id, temperature=0.0)
        if not res.ok:
            item.analysis_status = "not_analysed"
            item.analysis_note = f"Not analysed — {res.not_analysed_reason}"
            db.flush()
            return {"status": item.analysis_status, "note": item.analysis_note}
        ext: EvidenceExtraction = res.data
        item.extracted = {**ext.model_dump(mode="json"), "model": res.model, "prompt_version": prompts.EVIDENCE_V}
        item.reconciliation = reconcile(ext, txn, db)
        item.analysis_status = "analysed"
        item.analysis_note = f"Read by {res.model}; compared with {txn.id} by code"
        db.flush()
        audit.record(db, item.case_id, actor, "system" if actor == "system" else "investigator", "evidence_analysed",
                     {"evidence_id": item.id, "model": res.model, "summary": item.reconciliation["summary"],
                      "embedded_instructions_detected": ext.embedded_instructions_detected})
        return {"status": "analysed", "reconciliation": item.reconciliation}


def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _parse_dt(date_text: str | None, time_text: str | None) -> datetime | None:
    if not date_text:
        return None
    dt_raw = f"{date_text} {time_text or ''}".strip()
    ist = "IST" in dt_raw.upper() or "+05:30" in dt_raw
    clean = re.sub(r"\b(IST|UTC|GMT)\b|\+05:30", "", dt_raw, flags=re.I).strip().replace(",", "")
    for fmt in ("%d %b %Y %I:%M %p", "%d %b %Y %H:%M", "%d %B %Y %I:%M %p", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M",
                "%d %b %Y", "%d/%m/%Y"):
        try:
            d = datetime.strptime(clean, fmt)
            return d - timedelta(hours=5, minutes=30) if ist else d
        except ValueError:
            continue
    return None


def reconcile(ext: EvidenceExtraction, txn: m.Transaction, db: Session) -> dict:
    checks = []
    if ext.amount:
        try:
            doc_minor = to_minor(ext.amount.replace(",", "").strip(), (ext.currency or txn.currency).upper().replace("RS", "INR").replace("₹", "INR")[:3] or txn.currency)
            checks.append({"field": "amount", "result": "matches" if doc_minor == txn.amount_minor else "contradicts",
                           "document_value": fmt_amount(doc_minor, txn.currency), "ledger_value": fmt_amount(txn.amount_minor, txn.currency),
                           "ledger_id": txn.id})
        except NormalisationError:
            checks.append({"field": "amount", "result": "unverifiable", "document_value": ext.amount, "ledger_value": None, "ledger_id": txn.id})
    else:
        checks.append({"field": "amount", "result": "unverifiable", "document_value": None, "ledger_value": None, "ledger_id": txn.id})
    if ext.reference:
        same = _digits(ext.reference) == _digits(txn.reference) and _digits(ext.reference)
        checks.append({"field": "reference", "result": "matches" if same else ("contradicts" if txn.reference else "unverifiable"),
                       "document_value": ext.reference, "ledger_value": txn.reference, "ledger_id": txn.id})
    when = _parse_dt(ext.date_text, ext.time_text)
    if when:
        has_time = bool(ext.time_text)
        delta = abs((when - txn.occurred_at).total_seconds())
        tol = 15 * 60 if has_time else 36 * 3600
        checks.append({"field": "date_time", "result": "matches" if delta <= tol else "contradicts",
                       "document_value": f"{ext.date_text} {ext.time_text or ''}".strip(),
                       "ledger_value": txn.occurred_at.strftime("%d %b %Y %H:%M UTC"), "ledger_id": txn.id})
    if ext.payee:
        acct = db.get(m.Account, txn.credit_account_id)
        label = (acct.holder_label if acct else "").lower().replace("(synthetic)", "")
        overlap = {w for w in re.findall(r"[a-z]{3,}", ext.payee.lower())} & set(re.findall(r"[a-z]{3,}", label))
        checks.append({"field": "payee", "result": "matches" if overlap else "unverifiable", "document_value": ext.payee,
                       "ledger_value": acct.holder_label if acct else None, "ledger_id": txn.credit_account_id})
    n_c = sum(1 for c in checks if c["result"] == "contradicts")
    n_m = sum(1 for c in checks if c["result"] == "matches")
    summary = (f"{n_c} field(s) contradict the ledger" if n_c else f"{n_m} field(s) match the ledger" if n_m else "no comparable fields")
    if ext.embedded_instructions_detected:
        summary += "; document contains text addressed to an AI/reviewer (ignored)"
    return {"checks": checks, "matched_txn_id": txn.id, "summary": summary, "contradictions": n_c, "matches": n_m,
            "embedded_instructions_detected": ext.embedded_instructions_detected, "tamper_indicators": ext.tamper_indicators,
            "compared_by": "deterministic code"}
