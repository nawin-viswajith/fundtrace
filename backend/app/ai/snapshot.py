"""Evidence snapshot: the closed set of citable records an AI run may use.

Every record has a stable id. The snapshot is hashed and stored with the report, so any report can
be re-checked later against exactly the data it was written from.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from app.ai.prompts import fence
from app.services.trace import fmt_amount


def _t(iso: str | None) -> dict:
    if not iso:
        return {}
    d = datetime.fromisoformat(iso.rstrip("Z"))
    ist = d + timedelta(hours=5, minutes=30)
    return {"time_utc": d.strftime("%d %b %Y %H:%M UTC"), "time_ist": ist.strftime("%d %b %Y %H:%M IST")}


def _amt(minor: int | None, cur: str) -> str | None:
    return None if minor is None else fmt_amount(minor, cur)


def build_snapshot(ctx: dict, extra: dict | None = None) -> dict:
    case = ctx["case"]
    cur = case.get("currency") or "INR"
    recs: dict[str, dict] = {}

    recs[case["id"]] = {
        "type": "case", "category": case["category_label"], "status": case["status"], "priority": ctx["computed_priority"]["priority"],
        "priority_reasons": ctx["computed_priority"]["reasons"], "reported": _t(case["reported_at"]).get("time_utc"),
        "customer_statement": fence(case["allegation"]),
        "statement_translation_ai": fence(case["allegation_translation"]) if case.get("allegation_translation") else None,
    }
    att = ctx["attribution"]
    for n in ctx["graph"]["nodes"]:
        if n["type"] == "transaction":
            dd = n["data"]
            r = {"type": "transaction", "provenance": "confirmed (ledger record)", "amount": _amt(dd["amount_minor"], dd["currency"]),
                 "status": dd["status"], "channel": dd["channel"], "reference": dd["reference"] or "MISSING",
                 "from_account": dd["debit_account_id"], "to_account": dd["credit_account_id"], **_t(dd["occurred_at"]),
                 "role": (n.get("roles") or [n.get("direction")])[0], "source_record": f"{dd['source_system']}:{dd['source_record_id']}"}
            if dd.get("reversal_of_id"):
                r["reversal_of"] = dd["reversal_of_id"]
            if n.get("note"):
                r["note"] = n["note"]
            a = att.get("per_transaction", {}).get(n["id"])
            if a:
                r["attributable_to_disputed_funds"] = {
                    "lower_bound": _amt(a.get("min"), cur), "upper_bound": _amt(a.get("max"), cur),
                    "fifo": _amt(a.get("fifo"), cur), "pro_rata": _amt(a.get("pro_rata"), cur),
                    "basis": "derived by balance arithmetic; does not prove these are the same funds"}
            recs[n["id"]] = r
        elif n["type"] == "account":
            dd = n["data"]
            recs[n["id"]] = {"type": "account", "holder": n["label"], "institution": dd["institution"], "external": dd["external"],
                             "kind": dd["kind"], "opened": (dd.get("opened_at") or "")[:10] or None, "roles": n.get("roles"),
                             "endpoint": n.get("endpoint"), "endpoint_meaning": n.get("endpoint_reason"),
                             "expandable": bool(n.get("expandable"))}
    for acct, info in att.get("per_account", {}).items():
        recs[f"ATTR-{acct}"] = {"type": "attribution_residual", "account": acct, "basis": "derived",
                                "possibly_disputed_funds_remaining": {k: _amt(v, cur) for k, v in info["residual"].items()},
                                "balance_at_window_end": _amt(info["balance_at_window_end"], cur)}
    for h in att.get("holdable", []):
        recs[f"HOLD-{h['account_id']}"] = {"type": "hold_candidate", "account": h["account_id"], "basis": "derived",
                                           "range": f"{_amt(h['min_minor'], cur)} to {_amt(h['max_minor'], cur)}",
                                           "min_minor": h["min_minor"], "max_minor": h["max_minor"],
                                           "note": "Visible account that may still hold disputed funds. A hold needs investigator approval."}
    tr = ctx["traceability"]
    recs["TRACE-SUMMARY"] = {"type": "traceability", "basis": "derived",
                             "coverage_by_method": {k: (None if v is None else f"{round(v * 100)}%") for k, v in (tr["coverage"] or {}).items()},
                             "endpoints": tr["endpoints"], "paths": tr["paths"], "truncated": tr["truncated"],
                             "disputed_amount": _amt(att.get("disputed_amount_minor"), cur), "caveat": att.get("caveat")}
    for r in ctx["rules"]:
        recs[f"FLAG-{r['rule_id']}"] = {"type": "risk_signal", "basis": "derived (deterministic rule)", "rule": r["rule_id"],
                                        "name": r["name"], "status": r["status"], "severity": r["severity"],
                                        "facts": [f["text"] for f in r["facts"]], "source_ids": r["source_ids"],
                                        "thresholds": r["params"], "limitations": r["limitations"], "missing": r["missing_fields"],
                                        "suggested_step": r["suggested_step"]}
    for e in ctx["evidence"]:
        recs[e["id"]] = {"type": "evidence", "filename": e["filename"], "kind": e["kind"], "checklist_item": e["checklist_key"],
                         "analysis_status": e["analysis_status"], "sha256": e["sha256"][:16] + "…",
                         "extracted_by_ai": fence(json.dumps(e["extracted"], ensure_ascii=False)) if e.get("extracted") else None,
                         "reconciliation": (e.get("reconciliation") or {}).get("checks")}
    for i in ctx["completeness"]["items"]:
        recs[f"CHK-{i['key']}"] = {"type": "checklist_item", "label": i["label"], "required": i["required"], "status": i["status"],
                                   "why_it_matters": i["why_it_matters"], "source_ids": i["source_ids"]}
    recs["COMPLETENESS"] = {"type": "completeness", "basis": "derived", "present": ctx["completeness"]["present"],
                            "required": ctx["completeness"]["required"], "note": ctx["completeness"]["note"]}
    for n, c in enumerate(ctx["consistency"]["checks"], 1):
        recs[f"CONS-{n}"] = {"type": "consistency_check", "basis": "derived", "check": c["check"], "result": c["result"],
                             "detail": c["detail"], "source_ids": c["source_ids"]}
    for c in ctx["policy"]["clauses"]:
        recs[c["clause_id"]] = {"type": "policy_clause", "policy": c["policy_id"], "text": c["text"], "status": c["status"],
                                "reasons": c["reasons"], "needs": c["needs"]}
    for mstone in ctx["sla"]["milestones"]:
        recs[f"SLA-{mstone['key']}"] = {"type": "sla", "label": mstone["label"], "due": _t(mstone["due_at"]).get("time_utc"),
                                        "remaining_hours": mstone["remaining_hours"], "breached": mstone["breached"],
                                        "clause": mstone["clause_id"]}
    for h in ctx.get("holds", []):
        recs[f"HOLDREQ-{h['id']}"] = {"type": "hold", "account": h["account_id"], "amount": _amt(h["amount_minor"], h["currency"]),
                                      "status": h["status"]}
    for k, v in (extra or {}).items():
        recs.setdefault(k, v)
    body = json.dumps(recs, sort_keys=True, ensure_ascii=False, default=str)
    return {"case_id": case["id"], "records": recs, "hash": hashlib.sha256(body.encode()).hexdigest(),
            "ruleset_version": ctx.get("ruleset_version")}


def snapshot_json(snap: dict, ids: list[str] | None = None) -> str:
    recs = snap["records"] if ids is None else {i: snap["records"][i] for i in ids if i in snap["records"]}
    return json.dumps(recs, ensure_ascii=False, indent=1, default=str)


def referenced_records(db, ctx: dict) -> dict:
    """Records cited by rules/checks but not already in the graph (auth events, devices, linked cases, accounts).

    Linked cases expose only id, status and category — never another customer's statement.
    """
    from app import models as m

    present = {n["id"] for n in ctx["graph"]["nodes"]} | {e["id"] for e in ctx["evidence"]} | {ctx["case"]["id"]}
    wanted: set[str] = set()
    for r in ctx["rules"]:
        wanted |= set(r["source_ids"])
    for c in ctx["consistency"]["checks"]:
        wanted |= set(c["source_ids"])
    for i in ctx["completeness"]["items"]:
        wanted |= set(i["source_ids"])
    out: dict[str, dict] = {}
    for t in db.query(m.Transaction).filter(m.Transaction.id.in_([w for w in wanted - present if w.startswith("TXN-")])).all():
        wanted |= {t.debit_account_id, t.credit_account_id}
    for rid in sorted(wanted - present):
        if rid.startswith("AUTH-"):
            a = db.get(m.AuthEvent, rid)
            if a:
                out[rid] = {"type": "auth_event", "account": a.account_id, "event": a.event_type, "outcome": a.outcome,
                            "device": a.device_id, **_t(a.occurred_at.isoformat() + "Z"), "source_record": f"{a.source_system}:{a.source_record_id}"}
        elif rid.startswith("DEV-"):
            d = db.get(m.Device, rid)
            if d:
                out[rid] = {"type": "device", "label": d.label, "first_seen_anywhere": _t(d.first_seen_at.isoformat() + "Z").get("time_utc")}
        elif rid.startswith("CASE-"):
            c = db.get(m.DisputeCase, rid)
            if c:
                out[rid] = {"type": "linked_case", "status": c.status, "category": c.category, "disputed_txn": c.disputed_txn_id,
                            "note": "Another dispute on record. Its customer statement is not shared."}
        elif rid.startswith("ACC-"):
            a = db.get(m.Account, rid)
            if a:
                out[rid] = {"type": "account", "holder": a.holder_label, "institution": a.institution.name if a.institution else a.institution_id,
                            "external": bool(a.institution and a.institution.kind == "external"), "kind": a.kind,
                            "opened": a.opened_at.date().isoformat() if a.opened_at else None, "roles": ["referenced"]}
        elif rid.startswith("TXN-"):
            t = db.get(m.Transaction, rid)
            if t:
                out[rid] = {"type": "transaction", "provenance": "confirmed (ledger record)", "amount": _amt(t.amount_minor, t.currency),
                            "status": t.status, "channel": t.channel, "reference": t.reference or "MISSING", "from_account": t.debit_account_id,
                            "to_account": t.credit_account_id, **_t(t.occurred_at.isoformat() + "Z"), "role": "referenced",
                            "source_record": f"{t.source_system}:{t.source_record_id}"}
    return out
