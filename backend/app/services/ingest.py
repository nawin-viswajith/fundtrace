"""Ledger ingest: delivered records (Pub/Sub push or an uploaded statement) into the transaction ledger.

Guarantees:
- idempotent: a redelivered message (same message id) is not processed twice, and a source record that is already
  stored (same source system + record id) is counted as a duplicate, never inserted twice
- the same payment reported by another source system is merged into the stored transaction, keeping both
  source records and any disagreement between them (same rule as `ledger.normalise`)
- unknown counterparties become placeholder *external* accounts keyed by a hash of the identifier, so full
  account numbers are not stored and the trail ends there ("visibility ends") instead of failing
- invalid records are rejected with a reason and reported; they never block valid records in the same delivery
- open cases whose trace window covers the new records are re-assessed (priority, holds), so golden-hour
  recommendations update as soon as onward transfers arrive
"""
from __future__ import annotations

import hashlib
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.config import get_settings
from app.services.ledger import MERGE_WINDOW, normalise
from app.services.ledger_sources import safe_identifier

PLACEHOLDER_INSTITUTION = "INST-EXT-UNKNOWN"


def _txn_id(system: str, record_id: str) -> str:
    return "TXN-" + hashlib.sha256(f"{system}:{record_id}".encode()).hexdigest()[:12].upper()


def _resolve_account(db: Session, ident: object, name: str | None, cache: dict, created: list) -> str | None:
    ident = safe_identifier(ident) if ident is not None else None
    if ident is None:
        return None
    if ident in cache:
        return cache[ident]
    if db.get(m.Account, ident) is not None:
        cache[ident] = ident
        return ident
    ext_id = "EXT-" + hashlib.sha256(ident.encode()).hexdigest()[:12].upper()
    if db.get(m.Account, ext_id) is None:
        if db.get(m.Institution, PLACEHOLDER_INSTITUTION) is None:
            db.add(m.Institution(id=PLACEHOLDER_INSTITUTION, name="Unidentified institution (ingested)", kind="external"))
            db.flush()
        digits = "".join(ch for ch in ident if ch.isalnum())
        db.add(m.Account(id=ext_id, customer_id=None, institution_id=PLACEHOLDER_INSTITUTION, kind="external",
                         holder_label=(name or "Unverified counterparty")[:120], masked_number="XXXX" + digits[-4:],
                         opened_at=None, opening_balance_minor=None, currency="INR", is_synthetic=False))
        db.flush()
        created.append(ext_id)
    cache[ident] = ext_id
    return ext_id


def ingest(db: Session, records: list[dict], *, source_system: str, fmt: str, channel: str, message_id: str,
           received_by: str, error: str | None = None) -> tuple[m.IngestEvent, bool]:
    """Store delivered records. Returns (event, already_processed). `error` records an unreadable delivery."""
    prior = db.scalar(select(m.IngestEvent).where(m.IngestEvent.message_id == message_id))
    if prior is not None:
        return prior, True
    s = get_settings()
    ev = m.IngestEvent(message_id=message_id, channel=channel, source_system=source_system[:32], format=fmt[:32], status="processed",
                       records_in=len(records), rejected=[], cases_refreshed=[], received_by=received_by[:128])
    if error:
        ev.status, ev.error = "rejected", error[:255]
        return _finish(db, ev), False
    if len(records) > s.ingest_max_records:
        ev.status, ev.error = "rejected", f"too many records in one delivery ({len(records)} > {s.ingest_max_records})"
        return _finish(db, ev), False

    cache: dict[str, str] = {}
    placeholders: list[str] = []
    prepared, rejected = [], []
    for r in records:
        system = str(r.get("source_system") or source_system)[:32]
        rid = safe_identifier(r.get("source_record_id"))
        if rid is None:
            rejected.append({"source": f"{system}:?", "reason": "missing or invalid source_record_id"})
            continue
        if len(str(r.get("reference") or "")) > 64:  # the column limit; MySQL would fail the whole delivery
            rejected.append({"source": f"{system}:{rid}", "reason": "reference longer than 64 characters"})
            continue
        r = {**r, "source_system": system, "source_record_id": rid, "id": _txn_id(system, rid),
             "narrative": str(r.get("narrative") or "")[:255]}
        r["debit_account_id"] = _resolve_account(db, r.get("debit_account_id"), r.pop("debit_account_name", None), cache, placeholders)
        r["credit_account_id"] = _resolve_account(db, r.get("credit_account_id"), r.pop("credit_account_name", None), cache, placeholders)
        for fk, model in (("reversal_of_id", m.Transaction), ("device_id", m.Device)):
            if r.get(fk) and db.get(model, r[fk]) is None:
                r[fk] = None  # unknown references are dropped, not invented
        prepared.append(r)

    txns, rep = normalise(prepared)
    rejected += rep.rejected
    duplicates = len(rep.dropped_duplicates)
    created = merged = 0
    touched = []
    for t in txns:
        if db.scalar(select(m.Transaction.id).where(m.Transaction.source_system == t["source_system"],
                                                    m.Transaction.source_record_id == t["source_record_id"])):
            duplicates += 1
            continue
        same = None
        if t["reference"]:
            same = db.scalar(select(m.Transaction).where(
                m.Transaction.reference == t["reference"], m.Transaction.debit_account_id == t["debit_account_id"],
                m.Transaction.credit_account_id == t["credit_account_id"], m.Transaction.source_system != t["source_system"],
                m.Transaction.occurred_at.between(t["occurred_at"] - MERGE_WINDOW, t["occurred_at"] + MERGE_WINDOW)))
        if same is not None:
            entries = list(t["sources"])
            if any(x["system"] == e["system"] and x["record_id"] == e["record_id"] for x in same.sources or [] for e in entries):
                duplicates += 1
                continue
            diffs = {f: {"primary": getattr(same, f), "other": t[f]} for f in ("amount_minor", "currency", "status") if getattr(same, f) != t[f]}
            sources = list(same.sources or [])
            if diffs:
                first = dict(sources[0]) if sources else {}
                first["discrepancies"] = list(first.get("discrepancies") or []) + [{"source": t["source_system"], "fields": diffs}]
                sources = [first] + sources[1:]
            same.sources = sources + entries  # reassign so the JSON change is persisted
            merged += 1
            touched.append(same.occurred_at)
            continue
        db.add(m.Transaction(**t, is_synthetic=False))
        created += 1
        touched.append(t["occurred_at"])
    db.flush()

    ev.created, ev.merged, ev.duplicates, ev.rejected = created, merged, duplicates, rejected[:200]
    ev.placeholder_accounts = len(placeholders)
    if rejected and not (created or merged or duplicates):
        ev.status = "rejected"
    elif rejected:
        ev.status = "partial"
    if touched:
        ev.cases_refreshed = _refresh_cases(db, min(touched), max(touched))
    return _finish(db, ev), False


def _refresh_cases(db: Session, first, last) -> list[str]:
    """Re-assess open cases whose disputed payment is old enough for these records to be on its trail."""
    from app.seed.loader import refresh_case_assessments

    window = timedelta(hours=get_settings().trace_max_window_hours)
    ids = list(db.scalars(select(m.DisputeCase.id).join(m.Transaction, m.DisputeCase.disputed_txn_id == m.Transaction.id).where(
        m.DisputeCase.status != "resolved", m.Transaction.occurred_at.between(first - window, last))))
    if ids:
        refresh_case_assessments(db, ids)
    return ids


def _finish(db: Session, ev: m.IngestEvent) -> m.IngestEvent:
    db.add(ev)
    db.flush()
    # audit actors are at most 64 characters: a push service account is recorded by its account name
    actor = ev.received_by if len(ev.received_by) <= 64 else ev.received_by.split("@")[0][:64]
    audit.record(db, None, actor, "system", "ledger_ingested",
                 {"ingest_event_id": ev.id, "received_by": ev.received_by, "message_id": ev.message_id, "channel": ev.channel, "format": ev.format, "status": ev.status,
                  "records_in": ev.records_in, "created": ev.created, "merged": ev.merged, "duplicates": ev.duplicates,
                  "rejected": len(ev.rejected or []), "placeholder_accounts": ev.placeholder_accounts, "cases_refreshed": ev.cases_refreshed})
    return ev


def event_dict(ev: m.IngestEvent) -> dict:
    return {"id": ev.id, "message_id": ev.message_id, "channel": ev.channel, "source_system": ev.source_system, "format": ev.format,
            "status": ev.status, "records_in": ev.records_in, "created": ev.created, "merged": ev.merged, "duplicates": ev.duplicates,
            "rejected": ev.rejected or [], "placeholder_accounts": ev.placeholder_accounts, "cases_refreshed": ev.cases_refreshed or [],
            "error": ev.error, "received_by": ev.received_by, "received_at": ev.received_at.isoformat() + "Z" if ev.received_at else None}
