"""Deterministic policy library and eligibility evaluation.

Gemini may *retrieve and explain* clauses, but whether a clause's conditions hold is computed here,
and only clause ids from this library are valid citations.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

import yaml

POLICY_FILE = Path(__file__).resolve().parent.parent / "data" / "policies.yaml"


@lru_cache
def load_policies() -> list[dict]:
    with open(POLICY_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def clause_index() -> dict[str, dict]:
    out = {}
    for p in load_policies():
        for c in p["clauses"]:
            out[c["id"]] = {**c, "policy_id": p["id"], "policy_title": p["title"], "version": p["version"]}
    return out


def policies_for(category: str) -> list[dict]:
    return [p for p in load_policies() if category in p["categories"]]


def working_days_between(start: datetime, end: datetime) -> int:
    """Whole working days (Mon–Fri) after `start` up to and including `end`'s date."""
    if end <= start:
        return 0
    days, d = 0, start.date()
    while d < end.date():
        d += timedelta(days=1)
        if d.weekday() < 5:
            days += 1
    return days


def add_working_days(start: datetime, n: int) -> datetime:
    d = start
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def evaluate_eligibility(category: str, txn_time: datetime, reported_at: datetime) -> dict:
    lag = working_days_between(txn_time, reported_at)
    results = []
    for p in policies_for(category):
        for c in p["clauses"]:
            if c.get("kind") != "eligibility":
                continue
            cond = c.get("conditions") or {}
            status = "needs_information"
            reasons = []
            ok = True
            if "report_lag_working_days_max" in cond:
                if lag > cond["report_lag_working_days_max"]:
                    ok = False
                reasons.append(f"reported {lag} working day(s) after the transaction (limit ≤ {cond['report_lag_working_days_max']})")
            if "report_lag_working_days_min" in cond:
                if lag < cond["report_lag_working_days_min"]:
                    ok = False
                reasons.append(f"reported {lag} working day(s) after the transaction (needs ≥ {cond['report_lag_working_days_min']})")
            needs = c.get("needs") or []
            if not ok:
                status = "not_applicable"
            elif cond and not needs:
                status = "conditions_met"
            elif cond and needs:
                status = "conditions_met_needs_information"
            results.append({"clause_id": c["id"], "policy_id": p["id"], "text": c["text"], "status": status,
                            "reasons": reasons, "needs": needs})
    overall = "needs_information"
    if results and all(r["status"] == "not_applicable" for r in results):
        overall = "not_eligible_under_listed_clauses"
    elif any(r["status"] == "conditions_met" for r in results):
        overall = "eligible"
    return {
        "category": category,
        "report_lag_working_days": lag,
        "overall": overall,
        "clauses": results,
        "note": "Eligibility is computed from dates and category only; facts in 'needs' must be established by the investigator.",
    }
