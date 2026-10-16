"""Deterministic report validator — the first line of hallucination defence.

For each claim it checks that:
- factual claims cite at least one record, and every citation exists in the snapshot
- record ids mentioned in the text exist in the snapshot (no invented ids)
- every currency amount and clock time in the text appears in a cited record
- a "verified" basis is backed by a directly observed record (not only derived/system records)
- flow-through language ("funded by", "the stolen money") is never presented as verified
- banned conclusions (proof of fraud, customer liability, rejection) are absent
and that all required sections are present.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from app.ai.schemas import SECTION_TITLES

ID_RE = re.compile(r"\b(?:TXN|ACC|EV|CASE|DEV|AUTH|FLAG|CHK|CONS|ATTR|HOLD|HOLDREQ|SLA|ACTV|LINK|POL-[A-Z]+)-[A-Za-z0-9.\-]*[A-Za-z0-9]")
AMOUNT_RE = re.compile(r"(?:₹|rs\.?|inr)\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
BANNED = [
    (re.compile(r"\bprov(?:es|en|ing)\b.{0,40}\bfraud", re.I), "claims proof of fraud"),
    (re.compile(r"\b(?:is|was|are) (?:definitely |clearly )?fraudulent\b", re.I), "asserts fraud as fact"),
    (re.compile(r"\bconfirmed (?:fraud|scam|mule)\b", re.I), "asserts fraud as fact"),
    (re.compile(r"\b(?:customer|claimant|payer) (?:is|was|should be held) (?:fully |partly )?liable\b", re.I), "assigns customer liability"),
    (re.compile(r"\b(?:reject|decline|deny) (?:the|this) (?:claim|dispute)\b", re.I), "recommends rejecting the claim"),
    (re.compile(r"\b(?:definitely|certainly|undoubtedly|beyond doubt)\b", re.I), "overstates certainty"),
    (re.compile(r"\bclaim is (?:verified|genuine|valid)\b", re.I), "declares the claim verified (possible injected instruction)"),
    (re.compile(r"\b(?:guilty|criminal(?:ly)?)\b", re.I), "legal conclusion"),
]
FLOW_RE = re.compile(r"\b(?:funded by|came from the disputed|were the disputed funds|same (?:money|funds)|stolen (?:money|funds)|proceeds of)\b", re.I)
OBSERVED_TYPES = {"transaction", "account", "auth_event", "device", "evidence", "case", "policy_clause", "hold"}
UNCITED_OK_SECTIONS = {"limitations"}


def _amounts(text: str) -> list[Decimal]:
    out = []
    for raw in AMOUNT_RE.findall(text):
        try:
            out.append(Decimal(raw.replace(",", "")))
        except InvalidOperation:
            pass
    return out


def _record_amounts(rec: dict) -> set[Decimal]:
    s = json.dumps(rec, ensure_ascii=False, default=str)
    vals = set(_amounts(s))
    for k, v in _walk(rec):
        if k.endswith("_minor") and isinstance(v, int):
            vals.add(Decimal(v) / 100)
    return vals


def _record_times(rec: dict) -> set[str]:
    s = json.dumps(rec, ensure_ascii=False, default=str)
    return {f"{int(h):02d}:{mm}" for h, mm in TIME_RE.findall(s)}


def _walk(obj, key=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)
    else:
        yield key, obj


def check_claim(claim: dict, section: str, records: dict) -> list[dict]:
    issues: list[dict] = []
    text = claim.get("text", "")
    cites = [c.strip() for c in claim.get("citations", []) if c and c.strip()]
    basis = claim.get("basis", "unknown")
    known = [c for c in cites if c in records]
    for c in cites:
        if c not in records:
            issues.append({"code": "invalid_citation", "detail": f"cites {c}, which is not in the evidence snapshot", "severity": "error"})
    if not cites and section not in UNCITED_OK_SECTIONS and basis != "unknown":
        issues.append({"code": "missing_citation", "detail": "factual claim without a source record", "severity": "error"})
    for mid in {m.rstrip(".") for m in ID_RE.findall(text)}:
        if mid not in records:
            issues.append({"code": "invented_id", "detail": f"mentions {mid}, which does not exist in the snapshot", "severity": "error"})
    if known:
        allowed_amounts: set[Decimal] = set()
        allowed_times: set[str] = set()
        for c in known:
            allowed_amounts |= _record_amounts(records[c])
            allowed_times |= _record_times(records[c])
            for sid in records[c].get("source_ids") or []:  # flags/checks may reference records by id
                if sid in records:
                    allowed_amounts |= _record_amounts(records[sid])
                    allowed_times |= _record_times(records[sid])
        for a in _amounts(text):
            if not any(abs(a - x) <= Decimal("0.5") for x in allowed_amounts):
                issues.append({"code": "number_mismatch", "detail": f"amount ₹{a:,} does not appear in the cited records", "severity": "error"})
        for h, mm in TIME_RE.findall(text):
            t = f"{int(h):02d}:{mm}"
            if allowed_times and t not in allowed_times:
                issues.append({"code": "time_mismatch", "detail": f"time {t} does not appear in the cited records", "severity": "error"})
        if basis == "verified" and not any(records[c].get("type") in OBSERVED_TYPES for c in known):
            issues.append({"code": "basis_upgrade", "detail": "marked verified but cites only derived/system records", "severity": "warning"})
    if basis == "verified" and FLOW_RE.search(text):
        issues.append({"code": "basis_upgrade", "detail": "flow-through of the disputed funds is inferred, not verified", "severity": "error"})
    for rx, why in BANNED:
        if rx.search(text):
            issues.append({"code": "banned_phrase", "detail": why, "severity": "error"})
    return issues


def validate(draft: dict, records: dict) -> dict:
    sections = {s["key"]: s for s in draft.get("sections", [])}
    missing = [k for k in SECTION_TITLES if k not in sections or not sections[k].get("claims")]
    claims_out, errors = [], 0
    n = 0
    for key in SECTION_TITLES:
        for c in (sections.get(key) or {}).get("claims", []):
            n += 1
            cid = f"C{n:02d}"
            issues = check_claim(c, key, records)
            err = any(i["severity"] == "error" for i in issues)
            errors += err
            claims_out.append({**c, "id": cid, "section": key, "issues": issues, "valid": not err})
    action_issues = []
    for a in draft.get("recommended_actions", []):
        for c in a.get("citations", []):
            if c not in records:
                action_issues.append({"action": a.get("action_type"), "code": "invalid_citation", "detail": c})
        for rx, why in BANNED:
            if rx.search(a.get("description", "")):
                action_issues.append({"action": a.get("action_type"), "code": "banned_phrase", "detail": why})
    return {
        "claims": claims_out,
        "missing_sections": missing,
        "claims_total": len(claims_out),
        "claims_with_errors": errors,
        "action_issues": action_issues,
        "passed": errors == 0 and not missing and not action_issues,
    }


def feedback(result: dict) -> str:
    lines = []
    for c in result["claims"]:
        for i in c["issues"]:
            if i["severity"] == "error":
                lines.append(f"- {c['id']} ({c['section']}): {i['detail']}. Claim: \"{c['text'][:160]}\"")
    for s in result["missing_sections"]:
        lines.append(f"- section {s} is missing or empty")
    for a in result["action_issues"]:
        lines.append(f"- recommended action {a['action']}: {a['code']} {a['detail']}")
    return "\n".join(lines[:40])
