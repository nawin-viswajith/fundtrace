"""Fixed, bounded investigation tools the agent may call.

The model only chooses a tool and a target id that already exists in the snapshot. The tool runs
deterministic, limited queries and returns new citable records. No free-form queries exist.
"""
from __future__ import annotations

import time
from datetime import timedelta

from sqlalchemy.orm import Session

from app import models as m
from app.ai.schemas import ToolCall
from app.ai.snapshot import _amt, _t
from app.services.graph_store import SqlGraphStore
from app.services.investigation import default_params
from app.services.trace import trace

MAX_NEW_RECORDS = 40
ALLOWED_TARGET = {
    "expand_account": "account",
    "trace_backward": "account",
    "linked_cases": "account",
    "account_activity": "account",
    "device_links": "device",
}


def _txn_rec(t, role: str) -> dict:
    return {"type": "transaction", "provenance": "confirmed (ledger record)", "amount": _amt(t.amount_minor, t.currency),
            "status": t.status, "channel": t.channel, "reference": t.reference or "MISSING", "from_account": t.debit_account_id,
            "to_account": t.credit_account_id, **_t(t.occurred_at.isoformat() + "Z"), "role": role,
            "source_record": f"{t.source_system}:{t.source_record_id}"}


def _acct_rec(a: m.Account | None, role: str) -> dict | None:
    if a is None:
        return None
    return {"type": "account", "holder": a.holder_label, "institution": a.institution.name if a.institution else a.institution_id,
            "external": bool(a.institution and a.institution.kind == "external"), "kind": a.kind,
            "opened": a.opened_at.date().isoformat() if a.opened_at else None, "roles": [role]}


def run(db: Session, case: m.DisputeCase, call: ToolCall, records: dict) -> tuple[dict, dict]:
    t0 = time.perf_counter()
    tool, target = call.tool.value, call.target_id.strip()
    log = {"tool": tool, "target_id": target, "reason": call.reason[:300], "status": "ok", "new_records": 0}
    want = ALLOWED_TARGET[tool]
    rec = records.get(target)
    if rec is None or rec.get("type") != want:
        log.update(status="rejected", detail=f"target must be a {want} id present in the snapshot")
        return {}, log
    store = SqlGraphStore(db)
    root = store.get_transaction(case.disputed_txn_id)
    new: dict[str, dict] = {}
    try:
        if tool == "expand_account":
            if rec.get("external"):
                log.update(status="rejected", detail="external account: this bank has no records beyond it")
                return {}, log
            p = default_params(expand_accounts=(target,))
            p.depth = min(p.depth + 1, 5)
            res = trace(store, case.disputed_txn_id, p)
            for tid, t in res.txns.items():
                if tid not in records:
                    new[tid] = _txn_rec(t, "expanded")
            for aid in res.accounts:
                if aid not in records:
                    new[aid] = _acct_rec(db.get(m.Account, aid), "expanded")
        elif tool == "trace_backward":
            if target != root.debit_account_id:
                log.update(status="rejected", detail="trace_backward is limited to the payer account")
                return {}, log
            res = trace(store, case.disputed_txn_id, default_params(direction="backward"))
            for tid, t in res.txns.items():
                if tid not in records:
                    new[tid] = _txn_rec(t, "upstream")
            for aid in res.accounts:
                if aid not in records:
                    new[aid] = _acct_rec(db.get(m.Account, aid), "upstream")
        elif tool == "linked_cases":
            for link in store.cases_with_beneficiaries([target]):
                if link.case_id != case.id:
                    c = db.get(m.DisputeCase, link.case_id)
                    new[link.case_id] = {"type": "linked_case", "status": c.status, "category": c.category,
                                         "disputed_txn": link.disputed_txn_id, "beneficiary": target,
                                         "note": "Another dispute on record. Its customer statement is not shared."}
        elif tool == "account_activity":
            if rec.get("external"):
                log.update(status="rejected", detail="external account: activity not visible")
                return {}, log
            start, end = root.occurred_at - timedelta(days=7), root.occurred_at + timedelta(hours=72)
            rows = [t for t in store.activity(target, start, end, 500) if t.moved_money]
            ins = [t for t in rows if t.credit_account_id == target]
            outs = [t for t in rows if t.debit_account_id == target]
            new[f"ACTV-{target}"] = {
                "type": "account_activity", "basis": "derived", "account": target,
                "window": f"{_t(start.isoformat() + 'Z')['time_utc']} to {_t(end.isoformat() + 'Z')['time_utc']}",
                "incoming_count": len(ins), "incoming_total": _amt(sum(t.amount_minor for t in ins), root.currency),
                "outgoing_count": len(outs), "outgoing_total": _amt(sum(t.amount_minor for t in outs), root.currency),
                "distinct_counterparties": len({t.debit_account_id for t in ins} | {t.credit_account_id for t in outs}),
                "truncated": len(rows) >= 500}
        elif tool == "device_links":
            accts = [a for a in store.accounts_using_device(target, 20)]
            new[f"LINK-{target}"] = {"type": "device_links", "basis": "derived", "device": target, "accounts": accts,
                                     "note": "Accounts that used this device in login or payment records."}
            for a in accts:
                if a not in records:
                    r = _acct_rec(db.get(m.Account, a), "device-linked")
                    if r:
                        new[a] = r
    except Exception as exc:
        log.update(status="error", detail=type(exc).__name__)
        return {}, log
    new = {k: v for k, v in list(new.items())[:MAX_NEW_RECORDS] if v}
    log.update(new_records=len(new), record_ids=list(new)[:20], ms=int((time.perf_counter() - t0) * 1000))
    return new, log
