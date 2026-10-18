"""Evidence strength: one score per evidence item, with a sub-score per category.

Gemini only *labels* what it read (relevance, origin, legibility, signs of editing, embedded instructions);
the ledger comparison is deterministic code (`ai/evidence.reconcile`). This module turns both into numbers
with fixed, documented weights, so the same inputs always give the same score.

The score measures how much an item can be relied on *as evidence about the disputed payment*. It is not a
measure of the customer's honesty and not a fraud probability: a genuine but blurry screenshot scores low on
legibility, and a perfectly clear receipt for a different payment scores low on ledger match.
"""
from __future__ import annotations

VERSION = "evidence-score-v1"

# category -> (label, weight, what it measures)
CATEGORIES: dict[str, tuple[str, int, str]] = {
    "ledger_match": ("Ledger match", 30, "Printed amount, reference, time and payee compared with the bank's record by code"),
    "integrity": ("Integrity", 25, "No signs of editing and no hidden instructions addressed to an AI or reviewer"),
    "relevance": ("Relevance", 15, "Whether the document records a payment, or only surrounding events"),
    "provenance": ("Provenance", 10, "Who produced the document: a bank or app, a third party, or the customer"),
    "completeness": ("Completeness", 10, "How many of the key payment fields are printed on it"),
    "legibility": ("Legibility", 10, "How clearly the values can be read"),
}
FIELD_WEIGHTS = {"amount": 40, "reference": 30, "date_time": 20, "payee": 10}
RESULT_VALUE = {"matches": 1.0, "unverifiable": 0.5, "contradicts": 0.0}
KEY_FIELDS = ("amount", "reference", "date_text", "time_text", "payee", "payer", "app_or_bank")
RELEVANCE = {"direct": 100, "related": 60, "unrelated": 10}
PROVENANCE = {"system_generated": 100, "third_party": 80, "customer_authored": 50, "unknown": 40}
LEGIBILITY = {"good": 100, "partial": 60, "poor": 20}
CAP_CONTRADICTION, CAP_INSTRUCTIONS = 40, 50


def _band(score: int) -> str:
    return "strong" if score >= 75 else "moderate" if score >= 50 else "weak" if score >= 25 else "very_weak"


def _cat(key: str, score: int | None, basis: str, reasons: list[str]) -> dict:
    label, weight, about = CATEGORIES[key]
    return {"key": key, "label": label, "weight": weight, "score": score, "basis": basis, "about": about, "reasons": reasons}


def _ledger_match(rec: dict) -> dict:
    checks = [c for c in rec.get("checks") or [] if c.get("field") in FIELD_WEIGHTS]
    if not checks:
        return _cat("ledger_match", None, "code", ["No amount, reference, time or payee could be compared with the ledger."])
    total = sum(FIELD_WEIGHTS[c["field"]] for c in checks)
    got = sum(FIELD_WEIGHTS[c["field"]] * RESULT_VALUE.get(c["result"], 0.5) for c in checks)
    names = {"amount": "Amount", "reference": "Reference", "date_time": "Date/time", "payee": "Payee"}
    reasons = []
    for c in checks:
        doc, led = c.get("document_value"), c.get("ledger_value")
        if c["result"] == "matches":
            reasons.append(f"{names[c['field']]} matches the ledger ({doc}).")
        elif c["result"] == "contradicts":
            reasons.append(f"{names[c['field']]} contradicts the ledger: document {doc}, ledger {led}.")
        else:
            reasons.append(f"{names[c['field']]} could not be verified{f' ({doc})' if doc else ''}.")
    return _cat("ledger_match", round(100 * got / total), "code", reasons)


def _integrity(ext: dict) -> dict:
    tamper = [t for t in ext.get("tamper_indicators") or [] if t]
    score, reasons = 100, []
    if tamper:
        score -= min(75, 30 * len(tamper))
        reasons += [f"Possible editing: {t}" for t in tamper[:4]]
    if ext.get("embedded_instructions_detected"):
        score -= 50
        reasons.append("The document contains text addressed to an AI or reviewer (ignored).")
    if not reasons:
        reasons.append("No signs of editing and no embedded instructions were noticed.")
    return _cat("integrity", max(0, score), "AI observations, scored by code", reasons)


def _labelled(key: str, table: dict[str, int], value: str | None, reason: str | None, describe: dict[str, str]) -> dict:
    if value not in table:
        return _cat(key, None, "AI label, scored by code", ["Not assessed (read with an earlier version of the evidence reader)."])
    reasons = [describe[value]] + ([reason] if reason else [])
    return _cat(key, table[value], "AI label, scored by code", reasons)


def _completeness(ext: dict) -> dict:
    present = [f for f in KEY_FIELDS if ext.get(f)]
    names = {"amount": "amount", "reference": "reference", "date_text": "date", "time_text": "time", "payee": "payee",
             "payer": "payer", "app_or_bank": "app/bank"}
    missing = [names[f] for f in KEY_FIELDS if f not in present]
    reasons = [f"{len(present)} of {len(KEY_FIELDS)} key fields printed."]
    if missing:
        reasons.append("Not shown: " + ", ".join(missing) + ".")
    if not ext.get("is_payment_record"):
        reasons.append("Not a payment record, so fewer payment fields are expected.")
    return _cat("completeness", round(100 * len(present) / len(KEY_FIELDS)), "code", reasons)


def score(item: dict) -> dict | None:
    """Score an analysed evidence item (as returned by `evidence_to_dict`). None if it was not analysed."""
    ext, rec = item.get("extracted"), item.get("reconciliation") or {}
    if item.get("analysis_status") != "analysed" or not ext:
        return None
    cats = [
        _ledger_match(rec),
        _integrity(ext),
        _labelled("relevance", RELEVANCE, ext.get("relevance"), ext.get("relevance_reason"),
                  {"direct": "The document is a record of a payment.", "related": "The document describes surrounding events, not the payment itself.",
                   "unrelated": "The document does not appear to relate to a payment dispute."}),
        _labelled("provenance", PROVENANCE, ext.get("origin"), None,
                  {"system_generated": "Generated by a bank or payment app.", "third_party": "Produced by a third party (merchant, platform).",
                   "customer_authored": "Written or compiled by the customer.", "unknown": "Origin could not be determined."}),
        _completeness(ext),
        _labelled("legibility", LEGIBILITY, ext.get("legibility"), None,
                  {"good": "Values are clearly readable.", "partial": "Some values are hard to read.", "poor": "Most values are hard to read."}),
    ]
    scored = [c for c in cats if c["score"] is not None]
    weight = sum(c["weight"] for c in scored)
    overall = round(sum(c["score"] * c["weight"] for c in scored) / weight) if weight else 0
    caps = []
    if rec.get("contradictions"):
        caps.append({"cap": CAP_CONTRADICTION, "reason": "At least one printed value contradicts the ledger"})
    if ext.get("embedded_instructions_detected"):
        caps.append({"cap": CAP_INSTRUCTIONS, "reason": "The document contains instructions addressed to an AI or reviewer"})
    capped = min([overall] + [c["cap"] for c in caps])
    return {"version": VERSION, "overall": capped, "uncapped": overall, "band": _band(capped), "caps": caps, "categories": cats,
            "note": "Evidence strength, not customer credibility or fraud likelihood. AI labels are scored by fixed rules in code."}
