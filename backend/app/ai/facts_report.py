"""Deterministic, facts-only report built straight from the snapshot.

Used when Gemini is unavailable (down, disabled, over budget, or failed validation twice). Every
sentence is generated from a record, so it is always fully cited — but it has no AI synthesis, and
the UI labels it as such.
"""
from __future__ import annotations


def _c(text: str, cites: list[str], basis: str) -> dict:
    return {"text": text, "citations": [c for c in cites if c], "basis": basis}


def build(snap: dict) -> dict:
    R = snap["records"]
    case_id = snap["case_id"]
    case = R[case_id]
    root_id = next(k for k, v in R.items() if v.get("type") == "transaction" and v.get("role") == "disputed")
    root = R[root_id]
    S: dict[str, list[dict]] = {k: [] for k in ("case_overview", "known_facts", "transaction_trail", "risk_indicators",
                                                 "supporting_evidence", "contradicting_evidence", "missing_information",
                                                 "next_actions", "limitations")}
    S["case_overview"].append(_c(f"The customer reports a {case['category'].lower()} concerning {root_id}.", [case_id, root_id], "verified"))
    S["case_overview"].append(_c(f"{root_id} moved {root['amount']} from {root['from_account']} to {root['to_account']} on "
                                 f"{root.get('time_utc')} via {root['channel']}, reference {root['reference']}.", [root_id], "verified"))
    S["case_overview"].append(_c(f"The case is {case['status'].replace('_', ' ')} with priority {case['priority']}.", [case_id], "derived"))

    payer, payee = R.get(root["from_account"], {}), R.get(root["to_account"], {})
    if payee:
        opened = f", opened {payee['opened']}" if payee.get("opened") else ""
        S["known_facts"].append(_c(f"The beneficiary {root['to_account']} is a {payee['kind']} account at {payee['institution']}{opened}.",
                                   [root["to_account"]], "verified"))
    for fid in ("FLAG-R4", "FLAG-R5", "FLAG-R10"):
        f = R.get(fid)
        if f and f["status"] == "triggered":
            for fact in f["facts"][:2]:
                S["known_facts"].append(_c(fact, [fid] + f["source_ids"][:4], "derived"))

    for tid, t in R.items():
        if t.get("type") != "transaction" or t.get("role") in ("disputed",) or t.get("role") == "backward":
            continue
        S["transaction_trail"].append(_c(f"{tid} moved {t['amount']} from {t['from_account']} to {t['to_account']} at {t.get('time_utc')}"
                                         f" (status {t['status']}).", [tid], "verified"))
        a = t.get("attributable_to_disputed_funds")
        if a:
            S["transaction_trail"].append(_c(f"Between {a['lower_bound']} and {a['upper_bound']} of {tid} can be attributed to the disputed "
                                             f"funds by balance arithmetic.", [tid], "derived"))
    for aid, acc in R.items():
        if acc.get("type") == "account" and acc.get("endpoint") == "visibility_ends":
            S["transaction_trail"].append(_c(f"Visibility ends at {aid} ({acc['institution']}); the trail beyond it is unknown.", [aid], "unknown"))
    S["transaction_trail"].append(_c("Recorded hops show where money moved, not that it was the same money as the disputed payment.",
                                     ["TRACE-SUMMARY"], "inferred"))

    for fid, f in R.items():
        if f.get("type") == "risk_signal" and f["status"] == "triggered":
            S["risk_indicators"].append(_c(f"{f['rule']} {f['name']} ({f['severity']}): {f['facts'][-1] if f['facts'] else ''}",
                                           [fid] + f["source_ids"][:4], "derived"))
    ne = [f for f in R.values() if f.get("type") == "risk_signal" and f["status"] == "not_evaluable"]
    if ne:
        S["risk_indicators"].append(_c(f"{len(ne)} rule(s) could not be evaluated because data is missing; this is not a negative finding.",
                                       [f"FLAG-{f['rule']}" for f in ne], "derived"))

    cons = {k: v for k, v in R.items() if v.get("type") == "consistency_check"}
    for k, v in cons.items():
        if v["result"] == "consistent":
            S["supporting_evidence"].append(_c(f"{v['check']}: {v['detail']}", [k] + v["source_ids"], "derived"))
        elif v["result"] == "contradictory":
            S["contradicting_evidence"].append(_c(f"{v['check']}: {v['detail']}", [k] + v["source_ids"], "derived"))
    for eid, e in R.items():
        if e.get("type") == "evidence" and e["analysis_status"] != "analysed":
            S["supporting_evidence"].append(_c(f"{eid} ({e['filename']}) has not been analysed, so it neither supports nor contradicts the claim.",
                                               [eid], "unknown"))
    if not S["contradicting_evidence"]:
        S["contradicting_evidence"].append(_c(f"None of the {len(cons)} consistency checks found a contradiction.", list(cons)[:3], "derived"))
    if not S["supporting_evidence"]:
        S["supporting_evidence"].append(_c("No analysed evidence corroborates the customer's account yet.", ["COMPLETENESS"], "unknown"))

    for k, v in R.items():
        if v.get("type") == "checklist_item" and v["required"] and v["status"] != "present":
            S["missing_information"].append(_c(f"{v['label']} is {v['status'].replace('_', ' ')}: {v['why_it_matters']}", [k], "unknown"))
    if not S["missing_information"]:
        S["missing_information"].append(_c("All required checklist items are present.", ["COMPLETENESS"], "derived"))

    actions = []
    for hid, h in R.items():
        if h.get("type") == "hold_candidate":
            S["next_actions"].append(_c(f"Consider a hold on {h['account']}, which may still hold {h['range']} of the disputed funds.",
                                        [hid, h["account"]], "derived"))
            actions.append({"action_type": "hold_request", "target_id": h["account"], "description": f"Review a hold on {h['account']}",
                            "citations": [hid]})
    for aid, acc in R.items():
        if acc.get("type") == "account" and acc.get("endpoint") == "visibility_ends" and acc.get("kind") != "cash":
            S["next_actions"].append(_c(f"Request the onward trail for {aid} from {acc['institution']}.", [aid], "derived"))
            actions.append({"action_type": "contact_receiving_bank", "target_id": aid, "description": f"Trail request for {aid}",
                            "citations": [aid]})
    for k, v in R.items():
        if v.get("type") == "checklist_item" and v["required"] and v["status"] == "missing":
            actions.append({"action_type": "request_evidence", "target_id": k, "description": f"Request: {v['label']}", "citations": [k]})
    S["next_actions"].append(_c("An investigator reviews these findings and records the decision; the system does not decide liability.",
                                [case_id], "derived"))
    actions.append({"action_type": "human_review", "target_id": case_id, "description": "Investigator review", "citations": [case_id]})

    tr = R.get("TRACE-SUMMARY", {})
    S["limitations"].append(_c(tr.get("caveat") or "Attribution is balance arithmetic, not proof.", ["TRACE-SUMMARY"], "derived"))
    S["limitations"].append(_c("Only this bank's records are visible; activity at other institutions is unknown.", ["TRACE-SUMMARY"], "unknown"))
    S["limitations"].append(_c("This is a facts-only report generated without AI synthesis.", [], "unknown"))
    return {"sections": [{"key": k, "claims": v} for k, v in S.items()], "recommended_actions": actions}
