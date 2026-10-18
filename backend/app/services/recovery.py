"""How money found in an account shared by several open disputes would be split between them.

Several disputes can send money into the same account at this bank (a mule). Each case works out
its own hold suggestion from its own trace, so the suggestions on a shared account can add up to
more than the account actually holds: the same rupees are counted in several cases. This module
puts those cases side by side and works out a pro-rata split of the money that is really there:

    allocation = (eligible claim / total eligible claims) x money available, capped at the claim

All arithmetic is integer paise. Rounding uses the largest-remainder method, so the parts add up
exactly to min(money available, total claims) — no paisa is created or lost.

This is a mathematical illustration, not a decision. Claims are treated as equal priority, the
traced amounts are estimates under each case's tracing methods, and insolvency, restitution,
insurance, recovery or other applicable rules may require a different method or order. Nothing
here says who owns the money in the account, and recording a split does not move any money.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.services.investigation import build_trace
from app.services.workflow import STATUS_LABELS

RECOVERY_METHOD = "pro-rata-v1"
BASES = {
    "traced": "Each claim is the most of that case's money that may still be in this account (an estimate), never more than the amount disputed.",
    "disputed": "Each claim is the full amount disputed in the case, whether or not all of it can be traced into this account.",
}
DEFAULT_BASIS = "traced"
FORMULA = ("allocation = (eligible claim / total eligible claims) x money available, capped at the eligible claim; "
           "rounded to the paisa by largest remainder so the parts sum exactly to min(money available, total eligible claims)")
FORMULA_PLAIN = ("Each case gets the same share of the money in the account as its claim is of all the claims together, and never more "
                 "than its own claim. Paise are rounded so the parts add up exactly to the money that can be shared.")
ASSUMPTIONS = [
    "All claims are treated as equal priority: no case is paid ahead of another.",
    "Amounts traced into the account are estimates under each case's own tracing methods (four ways of counting mixed money), "
    "measured at the end of that case's trace window.",
    "Only open cases are included. Resolved cases and claims that have not been raised are not.",
    "Insolvency, restitution, insurance, recovery or other applicable rules may require a different method or order.",
    "This is a calculation only. It does not show who owns the money in the account, and it does not move, hold or release any money.",
]
NOT_A_TRANSFER = "Recorded for the file only. No money was moved, held or released."
DOUBLE_COUNT_STATUSES = ("recommended", "requested")  # declined suggestions no longer claim the money


# ---------------------------------------------------------------------------- pure arithmetic

def allocate(claims: list[tuple[str, int]], available: int) -> dict[str, int]:
    """Pro-rata split of `available` paise across `claims` [(key, eligible paise)], capped at each claim.

    Integer-only: each claim's exact quota is eligible x available / total; everyone gets the whole-paisa
    part, and the paise left over go one each to the largest fractional remainders (ties: the larger
    claim first, then input order). The result always sums exactly to min(available, total claims).
    """
    eligible = {k: max(0, int(e)) for k, e in claims}
    total = sum(eligible.values())
    available = max(0, int(available))
    if total == 0 or available == 0:
        return {k: 0 for k in eligible}
    if total <= available:  # enough for every claim in full: nobody gets more than they claim
        return dict(eligible)
    parts: dict[str, int] = {}
    rems: list[tuple[int, int, int, str]] = []
    for i, (k, e) in enumerate(eligible.items()):
        q, r = divmod(e * available, total)
        parts[k] = q
        rems.append((-r, -e, i, k))
    leftover = available - sum(parts.values())
    for _, _, _, k in sorted(rems)[:leftover]:
        parts[k] += 1
    return parts


# ---------------------------------------------------------------------------- gathering the inputs

@dataclass
class _Entry:
    case: m.DisputeCase
    row: dict  # the case's attribution "holdable" row for this account
    window_end: datetime
    currency: str


def _shared_accounts(db: Session) -> tuple[dict[str, list[_Entry]], int]:
    """Visible accounts that are hold candidates in two or more open cases, with each case's figures.

    Uses the same default trace and attribution as the case screens, so the numbers match what each
    case shows under "Money that could be held".
    """
    cases = db.scalars(select(m.DisputeCase).where(m.DisputeCase.status != "resolved").order_by(m.DisputeCase.id)).unique().all()
    by_account: dict[str, list[_Entry]] = {}
    for c in cases:
        _, fwd, att, _ = build_trace(db, c)
        for row in att.get("holdable") or []:
            by_account.setdefault(row["account_id"], []).append(_Entry(c, row, fwd.window_end, att.get("currency") or "INR"))
    return {a: es for a, es in by_account.items() if len({e.case.id for e in es}) >= 2}, len(cases)


def _holds(db: Session, account_id: str, case_ids: list[str]) -> dict[str, m.Hold]:
    rows = db.scalars(select(m.Hold).where(m.Hold.account_id == account_id, m.Hold.case_id.in_(case_ids),
                                           m.Hold.status.in_(DOUBLE_COUNT_STATUSES)).order_by(m.Hold.id)).all()
    return {h.case_id: h for h in rows}  # latest live suggestion per case


def _available(entries: list[_Entry], now: datetime) -> tuple[int | None, dict | None]:
    """Money in the account: the balance at the end of the latest trace window among these cases.

    One figure for the whole pool (never the sum of hold suggestions). The latest window includes the
    most ledger activity, so it is the closest to what is in the account now.
    """
    known = [e for e in entries if e.row.get("balance_minor") is not None]
    if not known:
        return None, None
    src = max(known, key=lambda e: (e.window_end, e.case.id))
    as_of = min(src.window_end, now)
    return max(0, src.row["balance_minor"]), {
        "case_id": src.case.id, "window_end": src.window_end.isoformat() + "Z", "as_of": as_of.isoformat() + "Z",
        "description": "Account balance on record at the end of the latest trace window among these cases (all recorded activity up to then).",
    }


def build_pool(db: Session, account_id: str, entries: list[_Entry], basis: str = DEFAULT_BASIS, now: datetime | None = None) -> dict:
    if basis not in BASES:
        raise ValueError(f"unknown basis {basis!r}")
    now = now or m.utcnow()
    entries = sorted(entries, key=lambda e: e.case.id)
    case_ids = [e.case.id for e in entries]
    holds = _holds(db, account_id, case_ids)
    available, source = _available(entries, now)
    currency = entries[0].currency
    acct = db.get(m.Account, account_id)
    warnings: list[str] = []

    claims = []
    for e in entries:
        t = e.case.disputed_txn
        disputed = t.amount_minor if t else 0
        traced_max = max(0, e.row["max_minor"])
        eligible = min(traced_max, disputed) if basis == "traced" else disputed
        h = holds.get(e.case.id)
        claims.append({
            "case_id": e.case.id, "status": e.case.status, "status_label": STATUS_LABELS.get(e.case.status, e.case.status),
            "disputed_txn_id": e.case.disputed_txn_id, "disputed_amount_minor": disputed,
            "traced_min_minor": max(0, e.row["min_minor"]), "traced_max_minor": traced_max, "by_method": e.row.get("by_method"),
            "traced_as_of": e.window_end.isoformat() + "Z",
            "eligible_minor": eligible, "allocated_minor": None, "share": None,
            "hold_id": h.id if h else None, "hold_status": h.status if h else None,
            # what this case on its own suggests holding here: its live hold suggestion, else the trace's upper bound
            "hold_suggested_minor": h.amount_minor if h else traced_max,
        })

    total = sum(c["eligible_minor"] for c in claims)
    if available is None:
        distributable = None
        warnings.append("The balance of this account is not known from the records, so no split can be worked out.")
    else:
        parts = allocate([(c["case_id"], c["eligible_minor"]) for c in claims], available)
        distributable = sum(parts.values())
        for c in claims:
            c["allocated_minor"] = parts[c["case_id"]]
            c["share"] = round(c["eligible_minor"] / total, 6) if total else None

    hold_total = sum(c["hold_suggested_minor"] for c in claims)
    exceeds = available is not None and hold_total > available
    double = {
        "hold_total_minor": hold_total, "available_minor": available, "exceeds": exceeds,
        "excess_minor": hold_total - available if exceeds else 0,
        "warning": (f"The hold suggestions for this account across {len(claims)} cases add up to more than the money in it. The same money "
                    "is being counted in more than one case, so do not hold more than the money actually in the account in total.")
        if exceeds else None,
    }
    if exceeds:
        warnings.append(double["warning"])

    input_ids = [account_id, *case_ids, *[c["disputed_txn_id"] for c in claims], *[f"HOLD-{h.id}" for h in holds.values()]]
    return {
        "account_id": account_id,
        "label": acct.holder_label if acct else account_id,
        "currency": currency,
        "method": RECOVERY_METHOD,
        "basis": basis,
        "basis_description": BASES[basis],
        "bases": BASES,
        "available_minor": available,
        "available_source": source,
        "total_eligible_minor": total,
        "distributable_minor": distributable,
        "left_over_minor": (available - distributable) if available is not None and distributable is not None else None,
        "claims": claims,
        "double_counting": double,
        "formula": FORMULA,
        "formula_plain": FORMULA_PLAIN,
        "assumptions": ASSUMPTIONS,
        "warnings": warnings,
        "input_ids": input_ids,
        "is_estimate": True,
        "caveat": ("A mathematical illustration of a pro-rata split, not a decision about who is owed what. Applicable recovery rules "
                   "may require a different method or order."),
        "computed_at": now.isoformat() + "Z",
    }


# ---------------------------------------------------------------------------- entry points

def list_pools(db: Session, basis: str = DEFAULT_BASIS) -> dict:
    shared, scanned = _shared_accounts(db)
    pools = [build_pool(db, a, es, basis) for a, es in shared.items()]
    for p in pools:
        last = latest_record(db, p["account_id"])
        p["last_recorded"] = record_to_dict(last) if last else None
    pools.sort(key=lambda p: (-len(p["claims"]), -(p["double_counting"]["excess_minor"]), p["account_id"]))
    return {"pools": pools, "cases_scanned": scanned, "method": RECOVERY_METHOD,
            "note": ("Accounts at this bank that may hold money from two or more open disputes. The split shown is a pro-rata "
                     "calculation for review; it is not a decision and does not move money.")}


def get_pool(db: Session, account_id: str, basis: str = DEFAULT_BASIS) -> dict | None:
    shared, _ = _shared_accounts(db)
    if account_id not in shared:
        return None
    pool = build_pool(db, account_id, shared[account_id], basis)
    last = latest_record(db, account_id)
    pool["last_recorded"] = record_to_dict(last) if last else None
    return pool


def record_allocation(db: Session, pool: dict, note: str, user: m.User) -> m.RecoveryAllocation:
    """Store the split exactly as computed, for the file. Audited once globally and once on each linked case."""
    from app import audit

    allocations = [{"case_id": c["case_id"], "eligible_minor": c["eligible_minor"], "allocated_minor": c["allocated_minor"]}
                   for c in pool["claims"]]
    rec = m.RecoveryAllocation(
        account_id=pool["account_id"], method=pool["method"], basis=pool["basis"], currency=pool["currency"],
        available_minor=pool["available_minor"], allocations=allocations, note=note, recorded_by=user.username,
        details={k: pool[k] for k in ("available_source", "total_eligible_minor", "distributable_minor", "formula", "assumptions",
                                      "input_ids", "double_counting", "computed_at")}
        | {"claims": [{k: c[k] for k in ("case_id", "disputed_amount_minor", "traced_min_minor", "traced_max_minor",
                                         "hold_suggested_minor")} for c in pool["claims"]]},
    )
    db.add(rec)
    db.flush()
    base = {"recovery_allocation_id": rec.id, "account_id": rec.account_id, "method": rec.method, "basis": rec.basis,
            "available_minor": rec.available_minor, "currency": rec.currency, "money_moved": False}
    audit.record(db, None, user.username, user.role, "recovery_allocation_recorded",
                 base | {"allocations": allocations, "note": note, "input_ids": pool["input_ids"]})
    for a in allocations:
        audit.record(db, a["case_id"], user.username, user.role, "recovery_allocation_recorded",
                     base | {"eligible_minor": a["eligible_minor"], "allocated_minor": a["allocated_minor"],
                             "linked_cases": [x["case_id"] for x in allocations]})
    return rec


def latest_record(db: Session, account_id: str) -> m.RecoveryAllocation | None:
    return db.scalar(select(m.RecoveryAllocation).where(m.RecoveryAllocation.account_id == account_id)
                     .order_by(m.RecoveryAllocation.id.desc()).limit(1))


def history(db: Session, account_id: str) -> list[dict]:
    rows = db.scalars(select(m.RecoveryAllocation).where(m.RecoveryAllocation.account_id == account_id)
                      .order_by(m.RecoveryAllocation.id.desc())).all()
    return [record_to_dict(r) for r in rows]


def record_to_dict(r: m.RecoveryAllocation) -> dict:
    return {"id": r.id, "account_id": r.account_id, "method": r.method, "basis": r.basis, "currency": r.currency,
            "available_minor": r.available_minor, "allocations": r.allocations, "note": r.note, "recorded_by": r.recorded_by,
            "recorded_at": r.recorded_at.isoformat() + "Z", "effect": NOT_A_TRANSFER}


def shared_for_case(db: Session, case: m.DisputeCase) -> list[dict]:
    """Accounts with a live hold suggestion in this case that other open cases also suggest holding.

    A cheap lookup on stored hold suggestions (no re-trace), for the hint on the case screen; the
    Linked cases page works the full split out from the traces.
    """
    if case.status == "resolved":
        return []
    mine = db.scalars(select(m.Hold.account_id).where(m.Hold.case_id == case.id, m.Hold.status.in_(DOUBLE_COUNT_STATUSES))).all()
    if not mine:
        return []
    rows = db.execute(select(m.Hold.account_id, m.Hold.case_id).join(m.DisputeCase, m.DisputeCase.id == m.Hold.case_id)
                      .where(m.Hold.account_id.in_(set(mine)), m.Hold.case_id != case.id,
                             m.Hold.status.in_(DOUBLE_COUNT_STATUSES), m.DisputeCase.status != "resolved")).all()
    others: dict[str, set[str]] = {}
    for acct, cid in rows:
        others.setdefault(acct, set()).add(cid)
    return [{"account_id": a, "other_cases": sorted(cs)} for a, cs in sorted(others.items())]


def redact(pool: dict, visible: set[str]) -> dict:
    """Hide the ids of cases the viewer cannot open (same pattern as linked-case rings). Amounts stay, so the split adds up."""
    hidden = set()
    for c in pool["claims"]:
        if c["case_id"] not in visible:
            hidden |= {c["case_id"], c["disputed_txn_id"]}
            if c["hold_id"]:
                hidden.add(f"HOLD-{c['hold_id']}")
            c.update(case_id="restricted", disputed_txn_id=None, hold_id=None, restricted=True)
        else:
            c["restricted"] = False
    pool["input_ids"] = [i for i in pool["input_ids"] if i not in hidden]
    if pool.get("available_source") and pool["available_source"]["case_id"] not in visible:
        pool["available_source"]["case_id"] = "restricted"
    if pool.get("last_recorded"):
        pool["last_recorded"] = redact_record(pool["last_recorded"], visible)
    return pool


def redact_record(rec: dict, visible: set[str]) -> dict:
    rec["allocations"] = [a | {"case_id": a["case_id"] if a["case_id"] in visible else "restricted"} for a in rec["allocations"]]
    return rec
