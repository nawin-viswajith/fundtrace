"""Separate assessment dimensions — deliberately *not* blended into one score.

- evidence completeness   required checklist items present / required
- evidence consistency    cross-source checks: consistent / contradictory / unverifiable
- traceability coverage   from attribution (per method) + endpoint breakdown
- priority                P1–P4 with explicit reasons
- SLA                     regulatory clocks from config
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from app.services.graph_store import AccountRec, GraphStore, TxnRec
from app.services.policy import add_working_days, working_days_between
from app.services.rules import TRIGGERED, RuleResult
from app.services.trace import TraceResult, fmt_amount

CATEGORIES = {
    "unauthorised_transfer": "Unauthorised transfer",
    "account_takeover": "Account takeover",
    "app_scam": "Authorised push-payment scam",
    "card_not_present": "Card-not-present fraud",
    "merchant_dispute": "Merchant dispute",
    "processing_error": "Processing error / duplicate debit",
}

# key: (label, why it matters, categories it is required for)
CHECKLIST = [
    ("customer_allegation", "Customer's statement of the dispute", "Defines what is being claimed; without it nothing can be tested.", "*"),
    ("disputed_txn_record", "Ledger record of the disputed transaction", "The authoritative amount, time, parties and reference.", "*"),
    ("auth_logs", "Authentication logs around the transfer", "Shows how the session was authenticated (failed attempts, OTP, device).",
     "unauthorised_transfer,account_takeover,card_not_present"),
    ("device_record", "Device used for the transfer", "Links the transfer to a known or new device.", "unauthorised_transfer,account_takeover"),
    ("customer_evidence", "Customer evidence (receipt, screenshot, statement)", "Lets the customer's account be reconciled with the ledger.", "*"),
    ("cyber_complaint_ack", "National cyber-fraud complaint acknowledgement", "Needed to coordinate holds with other banks.",
     "unauthorised_transfer,account_takeover,app_scam"),
    ("beneficiary_kyc", "Beneficiary account details (KYC, opening date)", "Mule indicators depend on who controls the beneficiary account.",
     "unauthorised_transfer,account_takeover,app_scam"),
    ("receiving_bank_trail", "Trail from the receiving institution", "This bank cannot see beyond an external transfer.", "conditional:exit"),
    ("merchant_response", "Merchant response / proof of delivery", "Required to weigh a merchant dispute.", "merchant_dispute"),
    ("scam_communication", "Communication used in the scam (messages, call log)", "Establishes the deception alleged.", "app_scam"),
]


def _required(cat_spec: str, category: str, has_exit: bool) -> bool:
    if cat_spec == "*":
        return True
    if cat_spec == "conditional:exit":
        return has_exit
    return category in cat_spec.split(",")


def completeness(category: str, allegation: str, root: TxnRec, payer: AccountRec, payee: AccountRec, store: GraphStore,
                 evidence: list[dict], requests: list[dict], attribution: dict) -> dict:
    exits = any((v.get("max") or 0) > 0 for v in (attribution.get("exits") or {}).values())
    auth = store.auth_events(payer.id, root.occurred_at - timedelta(hours=1), root.occurred_at, 1)
    ev_keys: dict[str, list[dict]] = {}
    for e in evidence:
        if e.get("checklist_key"):
            ev_keys.setdefault(e["checklist_key"], []).append(e)
    req_keys = {r["checklist_key"] for r in requests if r.get("status") == "open"}
    items = []
    for key, label, why, spec in CHECKLIST:
        required = _required(spec, category, exits)
        if not required and spec != "*" and key not in ev_keys:
            continue
        status, src = "missing", []
        if key == "customer_allegation":
            status = "present" if allegation.strip() else "missing"
        elif key == "disputed_txn_record":
            status, src = "present", [root.id]
        elif key == "auth_logs":
            status = "present" if auth is not None else "missing"
        elif key == "device_record":
            status, src = ("present", [root.device_id]) if root.device_id and store.get_device(root.device_id) else ("missing", [])
        elif key == "beneficiary_kyc":
            status, src = ("present", [payee.id]) if not payee.external and payee.opened_at else ("missing", [])
        if key in ev_keys:
            items_ev = ev_keys[key]
            src += [e["id"] for e in items_ev]
            analysed = [e for e in items_ev if e.get("analysis_status") == "analysed"]
            status = "present" if analysed or key in ("cyber_complaint_ack", "receiving_bank_trail", "merchant_response") else "received_not_analysed"
        if status == "missing" and key in req_keys:
            status = "requested"
        items.append({"key": key, "label": label, "why_it_matters": why, "required": required, "status": status, "source_ids": src})
    req = [i for i in items if i["required"]]
    present = sum(1 for i in req if i["status"] == "present")
    return {
        "present": present,
        "required": len(req),
        "ratio": round(present / len(req), 3) if req else None,
        "items": items,
        "note": "Missing evidence lowers completeness only. It is not evidence for or against the claim.",
    }


_AMOUNT_RE = re.compile(r"(?:₹|rs\.?|inr)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)


def consistency(allegation: str, root: TxnRec, store: GraphStore, evidence: list[dict]) -> dict:
    checks = []
    # 1) amount stated in the allegation (customer-provided text, parsed deterministically)
    amounts = [float(m.replace(",", "")) for m in _AMOUNT_RE.findall(allegation or "")]
    if amounts:
        ledger = root.amount_minor / 100
        match = any(abs(a - ledger) < 0.5 for a in amounts)
        checks.append({"check": "Allegation amount vs ledger", "result": "consistent" if match else "contradictory",
                       "detail": f"Statement mentions {', '.join(fmt_amount(int(a * 100), root.currency) for a in amounts)}; ledger has "
                                 f"{fmt_amount(root.amount_minor, root.currency)}.", "source_ids": [root.id]})
    else:
        checks.append({"check": "Allegation amount vs ledger", "result": "unverifiable",
                       "detail": "The statement does not state an amount.", "source_ids": [root.id]})
    # 2) evidence reconciliation
    for e in evidence:
        rec = e.get("reconciliation") or {}
        if e.get("analysis_status") != "analysed":
            checks.append({"check": f"Evidence {e['id']} vs ledger", "result": "unverifiable",
                           "detail": "Not analysed — the document has not been read.", "source_ids": [e["id"]]})
            continue
        for c in rec.get("checks", []):
            res = {"matches": "consistent", "contradicts": "contradictory"}.get(c.get("result"), "unverifiable")
            checks.append({"check": f"{e['id']} {c['field']}", "result": res,
                           "detail": f"Document: {c.get('document_value')!r}; ledger: {c.get('ledger_value')!r}.",
                           "source_ids": [e["id"], c.get("ledger_id") or root.id]})
    # 3) the disputed payment as reported by each source system (merged during normalisation)
    sources = list(root.sources or [])
    if len(sources) > 1:
        disc = sources[0].get("discrepancies") or []
        names = ", ".join(f"{s['system']}:{s['record_id']}" for s in sources)
        if disc:
            for d in disc:
                for f, v in d["fields"].items():
                    pv, ov = v["primary"], v["other"]
                    if f == "amount_minor":
                        pv, ov = fmt_amount(pv, root.currency), fmt_amount(ov, root.currency)
                    checks.append({"check": f"Source systems agree on {f.replace('_minor', '')}", "result": "contradictory",
                                   "detail": f"{sources[0]['system']} reports {pv}; {d['source']} reports {ov}.",
                                   "source_ids": [root.id]})
        else:
            checks.append({"check": "Source systems agree", "result": "consistent",
                           "detail": f"{len(sources)} source records agree on amount, currency and status ({names}).",
                           "source_ids": [root.id]})
    else:
        checks.append({"check": "Source systems agree", "result": "unverifiable",
                       "detail": "Only one source system reported this payment.", "source_ids": [root.id]})
    counts = {k: sum(1 for c in checks if c["result"] == k) for k in ("consistent", "contradictory", "unverifiable")}
    return {**counts, "checks": checks}


def traceability(res: TraceResult, attribution: dict) -> dict:
    ends: dict[str, int] = {}
    for n in res.nodes.values():
        if n["type"] == "account" and n.get("endpoint"):
            ends[n["endpoint"]] = ends.get(n["endpoint"], 0) + 1
    cov = attribution.get("coverage") or {}
    return {
        "coverage": cov,
        "coverage_range": [min((v for v in cov.values() if v is not None), default=None),
                           max((v for v in cov.values() if v is not None), default=None)],
        "buckets": attribution.get("buckets"),
        "endpoints": ends,
        "paths": len(res.paths),
        "truncated": res.truncated,
        "note": "Coverage is the share of the disputed amount whose position at window end is accounted for by visible records.",
    }


SLA_POLICIES = {
    "IN-UET": {"currency": "INR", "categories": ["unauthorised_transfer", "account_takeover", "card_not_present"],
               "milestones": [{"key": "shadow_credit", "label": "Shadow credit due", "working_days": 10, "clause": "POL-IN-UET-4.1"},
                              {"key": "resolution", "label": "Resolution due", "days": 90, "clause": "POL-IN-UET-4.2"}]},
    "IN-APP": {"currency": "INR", "categories": ["app_scam"],
               "milestones": [{"key": "hold_request", "label": "Hold request to beneficiary bank", "hours": 24, "clause": "POL-IN-APP-3.1"},
                              {"key": "resolution", "label": "Resolution due", "days": 90, "clause": None}]},
    "DEFAULT": {"currency": "*", "categories": ["*"], "milestones": [{"key": "resolution", "label": "Resolution due", "days": 30, "clause": None}]},
}


def sla(category: str, currency: str, reported_at: datetime, now: datetime) -> dict:
    pol_key = next((k for k, v in SLA_POLICIES.items() if category in v["categories"] and v["currency"] in (currency, "*")), "DEFAULT")
    pol = SLA_POLICIES[pol_key]
    ms = []
    for m in pol["milestones"]:
        if "working_days" in m:
            due = add_working_days(reported_at, m["working_days"])
        elif "hours" in m:
            due = reported_at + timedelta(hours=m["hours"])
        else:
            due = reported_at + timedelta(days=m["days"])
        remaining_h = round((due - now).total_seconds() / 3600, 1)
        ms.append({"key": m["key"], "label": m["label"], "due_at": due.isoformat() + "Z", "remaining_hours": remaining_h,
                   "breached": remaining_h < 0, "clause_id": m["clause"]})
    resolution = next((x for x in ms if x["key"] == "resolution"), ms[-1])
    return {"policy": pol_key, "milestones": ms, "due_at": resolution["due_at"],
            "note": "SLA values come from configuration modelled on public guidance; verify before real use."}


def priority(root: TxnRec, rules: list[RuleResult], attribution: dict, sla_info: dict, reported_at: datetime) -> tuple[str, list[str]]:
    pts, reasons = 0, []
    amt = root.amount_minor
    if amt >= 100000_00:
        pts += 3
        reasons.append(f"High value: {fmt_amount(amt, root.currency)}")
    elif amt >= 25000_00:
        pts += 2
        reasons.append(f"Material value: {fmt_amount(amt, root.currency)}")
    else:
        pts += 1
    trig = [r for r in rules if r.status == TRIGGERED]
    sev = {r.severity for r in trig}
    if "high" in sev:
        pts += 3
        reasons.append("High-severity signals: " + ", ".join(r.name for r in trig if r.severity == "high"))
    elif "medium" in sev:
        pts += 2
        reasons.append("Medium-severity signals: " + ", ".join(r.name for r in trig if r.severity == "medium"))
    hold = attribution.get("holdable") or []
    if hold and (reported_at - root.occurred_at) <= timedelta(hours=48):
        pts += 3
        reasons.append(f"Golden hour: up to {fmt_amount(hold[0]['max_minor'], root.currency)} may still be in visible accounts")
    soon = [m for m in sla_info["milestones"] if m["remaining_hours"] < 48]
    if soon:
        pts += 2
        reasons.append("SLA pressure: " + ", ".join(f"{m['label']} in {m['remaining_hours']} h" for m in soon))
    if any(r.rule_id == "R3" for r in trig):
        pts += 1
        reasons.append("Beneficiary appears in other disputes")
    p = "P1" if pts >= 8 else "P2" if pts >= 6 else "P3" if pts >= 4 else "P4"
    if not reasons:
        reasons.append("Low value, no triggered signals")
    return p, reasons


def report_lag(txn_time: datetime, reported_at: datetime) -> int:
    return working_days_between(txn_time, reported_at)
