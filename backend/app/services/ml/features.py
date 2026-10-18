"""Per-account behaviour features for the behaviour model, computed from the ledger.

Twelve cheap, robust measures over a 90-day window, each explainable in one plain sentence. The window ends
at the latest ledger record (not the wall clock), so the same data always gives the same features.

Only in-bank accounts are measured: another bank's account shows us just the payments that touch ours.
Merchant accounts and high-activity business accounts (more distinct counterparties than the trail's
high-activity threshold) are measured but not scored: their payment patterns are normal business and would
dominate a comparison with personal accounts.

A night-time share was considered and left out on purpose: in the synthetic data, background activity is
generated in the daytime only, so the feature would mostly measure the demo clock rather than behaviour.
"""
from __future__ import annotations

import statistics
from bisect import bisect_right
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.config import get_settings
from app.services.graph_store import EFFECTIVE_STATUSES

WINDOW_DAYS = 90
PASS_THROUGH_MINUTES = 60
FANOUT_MINUTES = 120
NO_OUTFLOW_MINUTES = WINDOW_DAYS * 24 * 60  # "money in, nothing went out afterwards" (capped at the window)


@dataclass(frozen=True)
class FeatureDef:
    key: str
    label: str
    description: str
    unit: str  # days | count | money | share | minutes
    transform: str  # log (log1p before modelling; heavy-tailed) | raw
    scale_floor: float  # smallest spread used for the robust z-score, on the transformed scale


FEATURES: list[FeatureDef] = [
    FeatureDef("account_age_days", "Account age", "Days since the account was opened.", "days", "log", 0.25),
    FeatureDef("payments_in", "Payments received", "Number of payments into the account in the last 90 days.", "count", "log", 0.25),
    FeatureDef("money_in", "Money received", "Total money received in the last 90 days.", "money", "log", 0.25),
    FeatureDef("money_out", "Money sent", "Total money sent in the last 90 days.", "money", "log", 0.25),
    FeatureDef("distinct_payers", "Different payers", "How many different accounts sent money to this account.", "count", "log", 0.25),
    FeatureDef("distinct_payees", "Different payees", "How many different accounts this account paid.", "count", "log", 0.25),
    FeatureDef("pass_through_1h", "Money passed on within 1 hour",
               "Share of the money received that was sent out again within 60 minutes of arriving.", "share", "raw", 0.05),
    FeatureDef("minutes_to_next_out", "Time until money goes out again",
               "After a payment comes in, the typical (median) time until the next payment goes out.", "minutes", "log", 0.25),
    FeatureDef("max_payees_2h", "Most payees within 2 hours",
               "The largest number of different accounts paid within any 2-hour period.", "count", "log", 0.25),
    FeatureDef("one_time_payer_share", "Payers seen only once",
               "Share of payers who paid this account only once in the last 90 days.", "share", "raw", 0.05),
    FeatureDef("devices_used", "Devices used", "Different devices used to sign in to or pay from this account.", "count", "log", 0.25),
    FeatureDef("accounts_sharing_devices", "Other accounts on the same devices",
               "How many other accounts signed in or paid from the same devices.", "count", "log", 0.25),
]
FEATURE_KEYS = [f.key for f in FEATURES]
FEATURE_BY_KEY = {f.key: f for f in FEATURES}


@dataclass
class FeatureTable:
    as_of: datetime
    window_start: datetime
    values: dict[str, dict[str, float | None]] = field(default_factory=dict)  # account -> feature -> value
    kinds: dict[str, str] = field(default_factory=dict)
    population: list[str] = field(default_factory=list)  # scored accounts, sorted by id
    not_scored: dict[str, str] = field(default_factory=dict)  # account -> plain reason
    hub_threshold: int = 25


def _pass_through(ins: list[tuple], outs: list[tuple]) -> float:
    """Share of received money that left again within PASS_THROUGH_MINUTES (FIFO matching of out against recent in)."""
    total_in = sum(a for _, a, _ in ins)
    if not total_in or not outs:
        return 0.0
    events = sorted([(t, 0, a) for t, a, _ in ins] + [(t, 1, a) for t, a, _ in outs])  # receipts first at equal times
    window = timedelta(minutes=PASS_THROUGH_MINUTES)
    queue: deque[list] = deque()
    matched = 0
    for t, kind, amount in events:
        if kind == 0:
            queue.append([t, amount])
            continue
        while queue and t - queue[0][0] > window:
            queue.popleft()
        left = amount
        while left and queue:
            take = min(left, queue[0][1])
            matched += take
            left -= take
            queue[0][1] -= take
            if not queue[0][1]:
                queue.popleft()
    return min(1.0, matched / total_in)


def _minutes_to_next_out(ins: list[tuple], outs: list[tuple]) -> float:
    if not ins:
        return float(NO_OUTFLOW_MINUTES)
    out_times = sorted(t for t, _, _ in outs)
    gaps = []
    for t, _, _ in ins:
        i = bisect_right(out_times, t)
        gaps.append((out_times[i] - t).total_seconds() / 60 if i < len(out_times) else NO_OUTFLOW_MINUTES)
    return float(min(NO_OUTFLOW_MINUTES, statistics.median(gaps)))


def _max_payees_window(outs: list[tuple]) -> int:
    rows = sorted((t, payee) for t, _, payee in outs)
    best, lo = 0, 0
    window = timedelta(minutes=FANOUT_MINUTES)
    for hi in range(len(rows)):
        while rows[hi][0] - rows[lo][0] > window:
            lo += 1
        best = max(best, len({p for _, p in rows[lo:hi + 1]}))
    return best


def compute(db: Session) -> FeatureTable:
    """Features for every in-bank account. Read-only."""
    from sqlalchemy import func

    as_of = db.scalar(select(func.max(m.Transaction.occurred_at))) or m.utcnow()
    start = as_of - timedelta(days=WINDOW_DAYS)
    hub = get_settings().trace_hub_threshold
    ft = FeatureTable(as_of=as_of, window_start=start, hub_threshold=hub)

    accounts = db.execute(select(m.Account.id, m.Account.kind, m.Account.opened_at)
                          .join(m.Institution, m.Institution.id == m.Account.institution_id)
                          .where(m.Institution.kind == "self").order_by(m.Account.id)).all()
    in_bank = {a.id for a in accounts}
    ins: dict[str, list[tuple]] = defaultdict(list)
    outs: dict[str, list[tuple]] = defaultdict(list)
    device_accounts: dict[str, set[str]] = defaultdict(set)
    rows = db.execute(select(m.Transaction.debit_account_id, m.Transaction.credit_account_id, m.Transaction.amount_minor,
                             m.Transaction.occurred_at, m.Transaction.device_id)
                      .where(m.Transaction.status.in_(EFFECTIVE_STATUSES), m.Transaction.occurred_at >= start,
                             m.Transaction.occurred_at <= as_of)).all()
    for debit, credit, amount, at, device in rows:
        if debit == credit:
            continue
        if debit in in_bank:
            outs[debit].append((at, int(amount), credit))
            if device:
                device_accounts[device].add(debit)
        if credit in in_bank:
            ins[credit].append((at, int(amount), debit))
    for acct, device in db.execute(select(m.AuthEvent.account_id, m.AuthEvent.device_id)
                                   .where(m.AuthEvent.device_id.is_not(None), m.AuthEvent.occurred_at >= start,
                                          m.AuthEvent.occurred_at <= as_of)).all():
        device_accounts[device].add(acct)
    devices_of: dict[str, set[str]] = defaultdict(set)
    for dev, accts in device_accounts.items():
        for a in accts:
            devices_of[a].add(dev)

    for a in accounts:
        i, o = ins.get(a.id, []), outs.get(a.id, [])
        payer_counts: dict[str, int] = defaultdict(int)
        for _, _, payer in i:
            payer_counts[payer] += 1
        payees = {p for _, _, p in o}
        devs = devices_of.get(a.id, set())
        sharing = set().union(*(device_accounts[d] for d in devs)) - {a.id} if devs else set()
        ft.values[a.id] = {
            "account_age_days": max(0.0, (as_of - a.opened_at).total_seconds() / 86400) if a.opened_at else None,
            "payments_in": float(len(i)),
            "money_in": float(sum(x for _, x, _ in i)),
            "money_out": float(sum(x for _, x, _ in o)),
            "distinct_payers": float(len(payer_counts)),
            "distinct_payees": float(len(payees)),
            "pass_through_1h": _pass_through(i, o),
            "minutes_to_next_out": _minutes_to_next_out(i, o),
            "max_payees_2h": float(_max_payees_window(o)),
            "one_time_payer_share": (sum(1 for c in payer_counts.values() if c == 1) / len(payer_counts)) if payer_counts else 0.0,
            "devices_used": float(len(devs)),
            "accounts_sharing_devices": float(len(sharing)),
        }
        ft.kinds[a.id] = a.kind
        counterparties = len(set(payer_counts) | payees)
        if a.kind == "merchant":
            ft.not_scored[a.id] = "Merchant account: its payments are business activity, so it is not compared with personal accounts."
        elif counterparties > hub:
            ft.not_scored[a.id] = (f"High-activity account ({counterparties} different counterparties in {WINDOW_DAYS} days): "
                                   "not compared with personal accounts.")
        else:
            ft.population.append(a.id)
    return ft
