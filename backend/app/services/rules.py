"""Explainable fraud-signal rules.

Each rule is a *signal for review*, never a verdict. Every evaluation returns one of:
- ``triggered``      the facts listed meet the threshold
- ``not_triggered``  the data needed exists and does not meet the threshold
- ``not_evaluable``  the data needed is missing — this is never treated as "clear"

Facts are structured ``{"text", "source_ids"}`` so the UI and the report can cite them.
Parameters are versioned; supervisors can change them (stored in ``rule_versions``).
"""
from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from app.services.graph_store import AccountRec, GraphStore, TxnRec
from app.services.trace import TraceResult, fmt_amount

TRIGGERED, NOT_TRIGGERED, NOT_EVALUABLE = "triggered", "not_triggered", "not_evaluable"


@dataclass
class RuleContext:
    case_id: str
    category: str
    root: TxnRec
    payer: AccountRec
    payee: AccountRec
    trace: TraceResult
    attribution: dict
    store: GraphStore
    evidence: list[dict] = field(default_factory=list)  # analysed evidence reconciliations
    now: datetime | None = None


@dataclass
class RuleResult:
    rule_id: str
    name: str
    version: int
    severity: str
    status: str
    facts: list[dict] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    suggested_step: str = ""
    evaluated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RuleDef:
    rule_id: str
    name: str
    description: str
    default_severity: str
    default_params: dict
    needs: list[str]
    fn: Callable[["RuleContext", dict, "RuleResult"], None]


def _fact(text: str, *ids: str) -> dict:
    return {"text": text, "source_ids": [i for i in ids if i]}


def _mins(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds() / 60, 1)


def _ist(d: datetime) -> str:
    return (d + timedelta(hours=5, minutes=30)).strftime("%H:%M IST")


def _cur(ctx: RuleContext, minor: int) -> str:
    return fmt_amount(minor, ctx.root.currency)


def _onward(ctx: RuleContext, minutes: float) -> list[TxnRec]:
    end = ctx.root.occurred_at + timedelta(minutes=minutes)
    rows = ctx.store.outgoing(ctx.payee.id, ctx.root.occurred_at, end, 200)
    return [t for t in rows if t.moved_money and t.status != "reversed"]


def _ist_day(d: datetime) -> str:
    return (d + timedelta(hours=5, minutes=30)).strftime("%d %b %H:%M IST")


def _minor(major: float) -> int:
    """Money parameters are stored in rupees (what supervisors type); ledger amounts are in paise."""
    return int(round(float(major) * 100))


def _payer_payments(ctx: RuleContext, around: timedelta, limit: int = 500) -> list[TxnRec]:
    """The payer's payments within ±``around`` of the disputed payment (bounded), oldest first.

    Failed attempts moved no money and are left out; the disputed payment itself is always kept.
    """
    t0 = ctx.root.occurred_at
    rows = ctx.store.debits_between(ctx.payer.id, t0 - around, t0 + around + timedelta(seconds=1), limit)
    return [t for t in rows if (t.moved_money or t.id == ctx.root.id) and t.occurred_at <= t0 + around]


def _payer_history_unavailable(ctx: RuleContext, r: RuleResult) -> bool:
    if ctx.payer.external:
        r.status = NOT_EVALUABLE
        r.missing_fields = ["payer's payment history (account is at another institution)"]
        r.suggested_step = "Ask the customer for their statement covering the days around the payment."
        return True
    return False


# --------------------------------------------------------------------------------------------
# Rule implementations
# --------------------------------------------------------------------------------------------


def _business_beneficiary(ctx: RuleContext, r: RuleResult) -> bool:
    node = ctx.trace.nodes.get(ctx.payee.id, {})
    if ctx.payee.kind == "merchant" or node.get("endpoint") == "hub_paused":
        r.status = NOT_EVALUABLE
        r.missing_fields = ["a personal beneficiary account — this is a merchant/high-activity account whose onward transfers are normal business"]
        r.suggested_step = "Ask the merchant/acquirer for order and settlement records instead."
        return True
    return False


def r1_rapid_onward(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    if _business_beneficiary(ctx, r):
        return
    if ctx.payee.external:
        r.status = NOT_EVALUABLE
        r.missing_fields = ["beneficiary account activity (account is at another institution)"]
        r.suggested_step = "Request the beneficiary's statement from the receiving institution."
        return
    outs = _onward(ctx, p["window_minutes"])
    amount = ctx.root.amount_minor
    cum = 0
    r.facts.append(_fact(f"{_cur(ctx, amount)} credited to {ctx.payee.id} at {_ist(ctx.root.occurred_at)}.", ctx.root.id))
    for t in outs:
        cum += t.amount_minor
        r.facts.append(_fact(
            f"{t.id}: {_cur(ctx, t.amount_minor)} left {ctx.payee.id} {_mins(ctx.root.occurred_at, t.occurred_at)} min later "
            f"(cumulative {round(100 * cum / amount)}% of the receipt).", t.id))
        r.source_ids.append(t.id)
        if cum >= amount * p["min_share"]:
            r.status = TRIGGERED
            r.facts.append(_fact(f"Threshold met: ≥{int(p['min_share'] * 100)}% moved on within {p['window_minutes']} min."))
            break
    else:
        r.status = NOT_TRIGGERED
        r.facts.append(_fact(f"Only {round(100 * cum / amount) if amount else 0}% moved on within {p['window_minutes']} min."))
    r.source_ids.insert(0, ctx.root.id)
    r.limitations.append("Shows recorded onward transfers; whether they carried the disputed funds is given by attribution, not by timing.")
    r.suggested_step = "Review attribution bounds and consider a hold on visible downstream accounts still holding funds."


def r2_split(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    if _business_beneficiary(ctx, r):
        return
    if ctx.payee.external:
        r.status = NOT_EVALUABLE
        r.missing_fields = ["beneficiary account activity (account is at another institution)"]
        return
    outs = _onward(ctx, p["window_minutes"])
    dests = {t.credit_account_id for t in outs}
    total = sum(t.amount_minor for t in outs)
    amount = ctx.root.amount_minor
    r.source_ids = [ctx.root.id] + [t.id for t in outs]
    r.facts.append(_fact(
        f"{len(outs)} onward transfers to {len(dests)} distinct accounts within {p['window_minutes']} min, "
        f"totalling {_cur(ctx, total)} ({round(100 * total / amount) if amount else 0}% of the receipt).",
        *[t.id for t in outs]))
    if len(outs) >= p["min_transfers"] and len(dests) >= p["min_destinations"] and total >= amount * p["min_share"]:
        r.status = TRIGGERED
    else:
        r.status = NOT_TRIGGERED
    r.limitations.append("Splitting is common in legitimate use (rent, bills); it is a pattern to review, not evidence of intent.")
    r.suggested_step = "Check each destination account's ownership and whether destinations appear in other disputes."


def r3_shared_beneficiary(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    accts = [n["id"] for n in ctx.trace.nodes.values() if n["type"] == "account" and "payer" not in n["roles"]]
    links = [l for l in ctx.store.cases_with_beneficiaries(accts) if l.case_id != ctx.case_id]
    by_acct: dict[str, list] = {}
    for l in links:
        by_acct.setdefault(l.beneficiary_account_id, []).append(l)
    for a, ls in by_acct.items():
        r.facts.append(_fact(f"{a} is the beneficiary in {len(ls)} other dispute(s): {', '.join(sorted(l.case_id for l in ls))}.",
                             a, *[l.disputed_txn_id for l in ls]))
        r.source_ids += [a] + [l.case_id for l in ls]
    hits = sum(1 for ls in by_acct.values() if len(ls) >= p["min_other_cases"])
    r.status = TRIGGERED if hits else NOT_TRIGGERED
    if not by_acct:
        r.facts.append(_fact(f"None of the {len(accts)} trail accounts is a beneficiary in another dispute on record."))
    if r.status == TRIGGERED and max(len(v) for v in by_acct.values()) >= p["high_severity_cases"]:
        r.severity = "high"
    r.limitations.append("Only disputes recorded in this system are compared; other banks' reports are not visible.")
    r.suggested_step = "Open the linked cases and compare allegations; consider a coordinated hold request."


def r4_failed_auth(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    start = ctx.root.occurred_at - timedelta(minutes=p["window_minutes"])
    evs = ctx.store.auth_events(ctx.payer.id, start, ctx.root.occurred_at, 200)
    if evs is None:
        r.status = NOT_EVALUABLE
        r.missing_fields = ["authentication logs for the payer's account/channel"]
        r.suggested_step = "Request authentication and device logs from the digital-channel team."
        return
    fails = [e for e in evs if e.outcome == "failure"]
    succ = [e for e in evs if e.outcome == "success" and (not fails or e.occurred_at > fails[0].occurred_at)]
    r.source_ids = [e.id for e in fails + succ] + [ctx.root.id]
    r.facts.append(_fact(f"{len(fails)} failed and {len(succ)} successful authentication events in the {p['window_minutes']} min before the transfer.",
                         *[e.id for e in fails + succ]))
    if len(fails) >= p["min_failures"] and succ:
        r.status = TRIGGERED
        r.facts.append(_fact(f"Success at {_ist(succ[0].occurred_at)} followed {len(fails)} failures; the transfer followed "
                             f"{_mins(succ[0].occurred_at, ctx.root.occurred_at)} min later.", succ[0].id, ctx.root.id))
    else:
        r.status = NOT_TRIGGERED
    r.limitations.append("Failed attempts can be the genuine customer mistyping; combine with device and location evidence.")
    r.suggested_step = "Compare the device and IP of the successful login with the customer's usual devices."


def r5_new_device(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    if not ctx.root.device_id:
        r.status = NOT_EVALUABLE
        r.missing_fields = ["device identifier on the disputed transaction"]
        return
    dev_id = ctx.root.device_id
    lookback = ctx.root.occurred_at - timedelta(days=p["history_days"])
    auth = ctx.store.auth_events(ctx.payer.id, lookback, ctx.root.occurred_at, 2000)
    debits = [t for t in ctx.store.debits_between(ctx.payer.id, lookback, ctx.root.occurred_at, 2000) if t.device_id]
    if auth is None and not debits:
        r.status = NOT_EVALUABLE
        r.missing_fields = ["device history for the payer's account"]
        return
    seen = [e.occurred_at for e in (auth or []) if e.device_id == dev_id] + [t.occurred_at for t in debits if t.device_id == dev_id]
    first = min(seen) if seen else ctx.root.occurred_at
    age_h = (ctx.root.occurred_at - first).total_seconds() / 3600
    r.source_ids = [ctx.root.id, dev_id] + [e.id for e in (auth or []) if e.device_id == dev_id][:3]
    r.facts.append(_fact(f"Device {dev_id} was first used on {ctx.payer.id} {round(age_h, 1)} h before the disputed transfer "
                         f"(history checked: {p['history_days']} days).", dev_id, ctx.root.id))
    r.status = TRIGGERED if age_h < p["max_device_age_hours"] else NOT_TRIGGERED
    r.limitations.append("Customers do change phones; a new device on the account is a signal, not proof of account takeover.")
    r.suggested_step = "Ask the customer whether they registered a new device; check SIM-swap indicators with the telecom partner."


def r6_unusual_amount(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    start = ctx.root.occurred_at - timedelta(days=p["lookback_days"])
    hist = [t for t in ctx.store.debits_between(ctx.payer.id, start, ctx.root.occurred_at, 1000) if t.moved_money]
    if len(hist) < p["min_history"]:
        r.status = NOT_EVALUABLE
        r.missing_fields = [f"at least {p['min_history']} prior debits in {p['lookback_days']} days (found {len(hist)})"]
        return
    med = statistics.median(t.amount_minor for t in hist)
    ratio = ctx.root.amount_minor / med if med else float("inf")
    r.source_ids = [ctx.root.id]
    r.facts.append(_fact(f"Disputed amount {_cur(ctx, ctx.root.amount_minor)} is {round(ratio, 1)}× the payer's median debit of "
                         f"{_cur(ctx, int(med))} over {len(hist)} debits in {p['lookback_days']} days.", ctx.root.id))
    r.status = TRIGGERED if ratio >= p["multiple"] else NOT_TRIGGERED
    r.limitations.append("Large one-off payments (deposits, purchases) are normal; baseline is this bank's records only.")
    r.suggested_step = "Ask the customer about any expected large payments around this date."


def r7_young_beneficiary(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    if ctx.payee.external or ctx.payee.opened_at is None:
        r.status = NOT_EVALUABLE
        r.missing_fields = ["beneficiary account opening date"]
        r.suggested_step = "Request beneficiary KYC/opening date from the receiving institution."
        return
    age = (ctx.root.occurred_at - ctx.payee.opened_at).days
    r.source_ids = [ctx.payee.id, ctx.root.id]
    r.facts.append(_fact(f"Beneficiary {ctx.payee.id} was opened {age} day(s) before receiving the funds.", ctx.payee.id))
    r.status = TRIGGERED if age < p["max_age_days"] else NOT_TRIGGERED
    r.limitations.append("New accounts are mostly legitimate; this matters in combination with rapid onward movement.")
    r.suggested_step = "Review beneficiary KYC and recent inflow pattern."


def r8_reversal_resend(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    w = timedelta(hours=p["window_hours"])
    rows = [t for t in ctx.store.debits_between(ctx.payer.id, ctx.root.occurred_at - w, ctx.root.occurred_at + w, 500)]
    reversed_ = [t for t in rows if t.status == "reversed"]
    hits = []
    for rv in reversed_:
        later = [t for t in rows if t.occurred_at > rv.occurred_at and t.occurred_at <= rv.occurred_at + w
                 and t.moved_money and t.status != "reversed" and t.id != rv.id]
        if later:
            hits.append((rv, later[0]))
    for rv, nx in hits:
        r.facts.append(_fact(f"{rv.id} ({_cur(ctx, rv.amount_minor)}) was reversed; {nx.id} ({_cur(ctx, nx.amount_minor)}) was sent "
                             f"{_mins(rv.occurred_at, nx.occurred_at)} min later to {nx.credit_account_id}.", rv.id, nx.id))
        r.source_ids += [rv.id, nx.id]
    r.status = TRIGGERED if hits else NOT_TRIGGERED
    if not hits:
        r.facts.append(_fact(f"No reversal followed by a resend on the payer's account within ±{p['window_hours']} h."))
    r.limitations.append("Reversals happen for technical reasons; check the reversal reason codes.")
    r.suggested_step = "Check reversal reason codes and whether the customer initiated the resend."


def r9_evidence_mismatch(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    analysed = [e for e in ctx.evidence if e.get("analysis_status") == "analysed" and e.get("reconciliation")]
    if not analysed:
        r.status = NOT_EVALUABLE
        r.missing_fields = ["analysed customer evidence (receipt/screenshot/statement)"]
        r.suggested_step = "Ask the customer for the payment receipt or statement and analyse it."
        return
    mism = []
    for e in analysed:
        for chk in e["reconciliation"].get("checks", []):
            if chk.get("result") == "contradicts":
                mism.append((e, chk))
    for e, chk in mism:
        r.facts.append(_fact(f"{e['id']}: {chk['field']} on the document is {chk.get('document_value')!r}, ledger record "
                             f"{chk.get('ledger_id')} has {chk.get('ledger_value')!r}.", e["id"], chk.get("ledger_id")))
        r.source_ids += [e["id"], chk.get("ledger_id")]
    r.status = TRIGGERED if mism else NOT_TRIGGERED
    if not mism:
        r.facts.append(_fact(f"{len(analysed)} analysed document(s) agree with the ledger on every extracted field.",
                             *[e["id"] for e in analysed]))
    r.limitations.append("Extraction is AI-assisted; a mismatch may be a reading error — check the document image.")
    r.suggested_step = "Ask the customer to clarify the discrepancy; compare with the original app receipt."


def r10_shared_device(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    devs = {ctx.root.device_id} if ctx.root.device_id else set()
    evs = ctx.store.auth_events(ctx.payer.id, ctx.root.occurred_at - timedelta(hours=24), ctx.root.occurred_at, 200) or []
    devs |= {e.device_id for e in evs if e.device_id}
    if not devs:
        r.status = NOT_EVALUABLE
        r.missing_fields = ["device identifiers for the disputed session"]
        return
    hits = []
    for d in sorted(devs):
        others = [a for a in ctx.store.accounts_using_device(d, 50) if a != ctx.payer.id]
        if len(others) >= p["min_other_accounts"]:
            hits.append((d, others))
    for d, others in hits:
        r.facts.append(_fact(f"Device {d} is also used by {len(others)} other account(s): {', '.join(others[:6])}.", d, *others[:6]))
        r.source_ids += [d] + others[:6]
    r.status = TRIGGERED if hits else NOT_TRIGGERED
    if not hits:
        r.facts.append(_fact(f"{len(devs)} device(s) on the session are not shared with other accounts on record.", *sorted(devs)))
    r.limitations.append("Family members legitimately share devices.")
    r.suggested_step = "Check whether the other accounts belong to the same household or appear in disputes."


def r11_external_exit(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    a = ctx.attribution
    if not a or not a.get("evaluable"):
        r.status = NOT_EVALUABLE
        r.missing_fields = ["attribution (disputed transaction did not move money)"]
        return
    exits = a.get("exits", {})
    for acct_id, v in exits.items():
        hi, lo = v.get("max") or 0, v.get("min") or 0
        if hi > 0:
            txids = [tid for tid, t in ctx.trace.txns.items() if t.credit_account_id == acct_id]
            r.facts.append(_fact(f"Between {_cur(ctx, lo)} and {_cur(ctx, hi)} of the disputed funds may have left to {acct_id} "
                                 f"({ctx.trace.accounts[acct_id].institution_name}); this bank cannot see further.", acct_id, *txids))
            r.source_ids += [acct_id] + txids
    triggered = any((v.get("max") or 0) >= ctx.root.amount_minor * p["min_share"] for v in exits.values())
    r.status = TRIGGERED if triggered else NOT_TRIGGERED
    if not exits:
        r.facts.append(_fact("No traced funds left this bank's visibility within the window."))
    r.limitations.append("Exits end this bank's visibility; the trail continues only with the receiving institution's records.")
    r.suggested_step = "Send a trail and hold request to the receiving institution (via the national cyber-fraud reporting process)."


def r12_record_inconsistency(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    txns = list(ctx.trace.txns.values())
    missing = [t for t in txns if not t.reference and t.moved_money]
    by_ref: dict[str, list[TxnRec]] = {}
    for t in txns:
        if t.reference:
            by_ref.setdefault(t.reference, []).append(t)
    clashes = [ts for ts in by_ref.values() if len({(x.amount_minor, x.debit_account_id, x.credit_account_id) for x in ts}) > 1]
    for t in missing:
        r.facts.append(_fact(f"{t.id} has no payment reference (UTR/RRN).", t.id))
        r.source_ids.append(t.id)
    for ts in clashes:
        r.facts.append(_fact(f"Reference {ts[0].reference} is used by {len(ts)} records with different amounts or parties.", *[x.id for x in ts]))
        r.source_ids += [x.id for x in ts]
    r.status = TRIGGERED if (missing or clashes) else NOT_TRIGGERED
    if r.status == NOT_TRIGGERED:
        r.facts.append(_fact(f"All {len(txns)} trail records have unique, consistent references."))
    r.limitations.append("Missing references are often a data-feed issue, not fraud.")
    r.suggested_step = "Reconcile the records with the payment switch using amount, time and parties."


def r13_velocity(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    if _payer_history_unavailable(ctx, r):
        return
    w = timedelta(minutes=p["window_minutes"])
    t0 = ctx.root.occurred_at
    rows = _payer_payments(ctx, w)
    # Busiest stretch of `window_minutes` that includes the disputed payment (earliest wins a tie).
    best: list[TxnRec] = []
    for i, first in enumerate(rows):
        if first.occurred_at > t0:
            break
        group = [t for t in rows[i:] if t.occurred_at - first.occurred_at <= w]
        if len(group) > len(best):
            best = group
    shown = best[:12]
    r.source_ids = [ctx.root.id] + [t.id for t in best]
    if len(best) >= p["min_payments"]:
        r.status = TRIGGERED
        r.facts.append(_fact(
            f"{len(best)} payments left {ctx.payer.id} within {p['window_minutes']} min "
            f"({_ist(best[0].occurred_at)} to {_ist(best[-1].occurred_at)}), including the disputed payment.",
            *[t.id for t in best]))
        for t in shown:
            r.facts.append(_fact(f"{t.id}: {_cur(ctx, t.amount_minor)} to {t.credit_account_id} at {_ist(t.occurred_at)}"
                                 f"{' (the disputed payment)' if t.id == ctx.root.id else ''}.", t.id))
        if len(best) > len(shown):
            r.facts.append(_fact(f"…and {len(best) - len(shown)} more in the same stretch.", *[t.id for t in best[len(shown):]]))
    else:
        r.status = NOT_TRIGGERED
        r.facts.append(_fact(
            f"At most {len(best)} payment(s) left {ctx.payer.id} in any {p['window_minutes']}-min stretch that includes the "
            f"disputed payment (threshold: {p['min_payments']}).", ctx.root.id, *[t.id for t in best]))
    r.limitations.append("Busy business accounts, or a customer paying several bills on salary day, can look the same.")
    r.suggested_step = "Ask the customer whether they made each of these payments, and check whether they went to new or unrelated accounts."


def r14_new_beneficiary(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    if _payer_history_unavailable(ctx, r):
        return
    if ctx.payee.kind == "merchant" or ctx.trace.nodes.get(ctx.payee.id, {}).get("endpoint") == "hub_paused":
        # A first order at a shop or a busy business account is ordinary; this sign is about paying new people.
        r.status = NOT_TRIGGERED
        r.source_ids = [ctx.root.id, ctx.payee.id]
        r.facts.append(_fact(f"{ctx.payee.id} is a merchant or high-activity business account; a first purchase there is normal, "
                             "so this check does not apply.", ctx.payee.id))
        r.suggested_step = "Use the merchant's order and delivery records instead."
        return
    limit = 2000
    t0 = ctx.root.occurred_at
    rows = ctx.store.debits_between(ctx.payer.id, t0 - timedelta(days=p["lookback_days"]), t0, limit)
    hist = [t for t in rows if t.moved_money and t.id != ctx.root.id]
    prior = [t for t in hist if t.credit_account_id == ctx.payee.id]
    amount, floor = ctx.root.amount_minor, _minor(p["min_amount_rupees"])
    r.source_ids = [ctx.root.id, ctx.payee.id]
    r.limitations.append("Customers legitimately pay new people and shops (a new landlord, a first order); this matters in "
                         "combination with other signals. Only this bank's records are checked.")
    r.suggested_step = "Ask the customer whether they knew the beneficiary and how they got the account details."
    if prior:
        last = prior[-1]
        r.status = NOT_TRIGGERED
        r.facts.append(_fact(
            f"{ctx.payer.id} paid {ctx.payee.id} {len(prior)} time(s) in the {p['lookback_days']} days before, most recently "
            f"{last.id} ({_cur(ctx, last.amount_minor)}) on {_ist_day(last.occurred_at)}.", *[t.id for t in prior[-3:]]))
        r.source_ids += [t.id for t in prior[-3:]]
        return
    if amount < floor:
        r.status = NOT_TRIGGERED
        r.facts.append(_fact(f"Disputed amount {_cur(ctx, amount)} is below the {_cur(ctx, floor)} this check looks at.", ctx.root.id))
        return
    if len(rows) >= limit:
        r.status = NOT_EVALUABLE
        r.missing_fields = [f"complete payment history (more than {limit} payments in {p['lookback_days']} days; "
                            "only the oldest could be checked)"]
        r.suggested_step = "Search the payer's statement for earlier payments to this beneficiary."
        return
    if len(hist) < p["min_history"]:
        r.status = NOT_EVALUABLE
        r.missing_fields = [f"at least {p['min_history']} earlier payments in {p['lookback_days']} days to compare against "
                            f"(found {len(hist)})"]
        r.suggested_step = "Ask the customer whether they had paid this beneficiary before, and check older statements."
        return
    r.status = TRIGGERED
    r.facts.append(_fact(
        f"No payment from {ctx.payer.id} to {ctx.payee.id} in the {p['lookback_days']} days before this one "
        f"({len(hist)} other payments checked).", ctx.root.id, ctx.payee.id))
    r.facts.append(_fact(f"Disputed amount {_cur(ctx, amount)} is at or above the {_cur(ctx, floor)} this check looks at.", ctx.root.id))


def r15_below_limit(ctx: RuleContext, p: dict, r: RuleResult) -> None:
    if _payer_history_unavailable(ctx, r):
        return
    limit_minor = _minor(p["review_limit_rupees"])
    lo = limit_minor * (1 - p["band_share"])
    rows = _payer_payments(ctx, timedelta(hours=p["window_hours"]))
    near = [t for t in rows if lo <= t.amount_minor < limit_minor]
    r.source_ids = [ctx.root.id] + [t.id for t in near]
    band = f"between {_cur(ctx, int(round(lo)))} and just under {_cur(ctx, limit_minor)}"
    if len(near) >= p["min_below_limit"]:
        r.status = TRIGGERED
        total = sum(t.amount_minor for t in near)
        r.facts.append(_fact(
            f"{len(near)} payments from {ctx.payer.id} within ±{p['window_hours']} h of the disputed payment were {band} "
            f"(the internal review limit); together {_cur(ctx, total)}.", *[t.id for t in near]))
        for t in near[:12]:
            r.facts.append(_fact(f"{t.id}: {_cur(ctx, t.amount_minor)} to {t.credit_account_id} on {_ist_day(t.occurred_at)}"
                                 f"{' (the disputed payment)' if t.id == ctx.root.id else ''}.", t.id))
    else:
        r.status = NOT_TRIGGERED
        r.facts.append(_fact(
            f"{len(near)} payment(s) from {ctx.payer.id} within ±{p['window_hours']} h were {band} "
            f"(threshold: {p['min_below_limit']}).", ctx.root.id, *[t.id for t in near]))
    r.limitations.append("The review limit is an internal configured value, and payments near round amounts are common.")
    r.suggested_step = "Check whether these payments together pass the review limit, and ask the customer why the amount was split."


CATALOGUE: list[RuleDef] = [
    RuleDef("R1", "Rapid onward movement", "Most of the received amount leaves the beneficiary quickly.", "high",
            {"window_minutes": 60, "min_share": 0.8}, ["beneficiary outgoing transfers"], r1_rapid_onward),
    RuleDef("R2", "Split into multiple transfers", "Receipt is split into several transfers to different accounts.", "high",
            {"window_minutes": 120, "min_transfers": 2, "min_destinations": 2, "min_share": 0.8}, ["beneficiary outgoing transfers"], r2_split),
    RuleDef("R3", "Beneficiary linked to other disputes", "An account on the trail is the beneficiary in other disputes.", "medium",
            {"min_other_cases": 1, "high_severity_cases": 2}, ["case links"], r3_shared_beneficiary),
    RuleDef("R4", "Failed logins before the transfer", "Repeated failed authentication, then success, then the transfer.", "high",
            {"window_minutes": 30, "min_failures": 3}, ["authentication events"], r4_failed_auth),
    RuleDef("R5", "New device", "The transfer was made from a recently first-seen device.", "medium",
            {"max_device_age_hours": 24, "history_days": 180}, ["device history"], r5_new_device),
    RuleDef("R6", "Unusual amount", "Amount is far above the payer's usual debits.", "medium",
            {"lookback_days": 90, "min_history": 5, "multiple": 5.0}, ["payer debit history"], r6_unusual_amount),
    RuleDef("R7", "Recently opened beneficiary", "Beneficiary account was opened shortly before receiving funds.", "medium",
            {"max_age_days": 30}, ["beneficiary opening date"], r7_young_beneficiary),
    RuleDef("R8", "Reversal then resend", "A reversed transfer is followed by a new transfer.", "low",
            {"window_hours": 24}, ["transaction status history"], r8_reversal_resend),
    RuleDef("R9", "Evidence contradicts the ledger", "Customer evidence differs from the bank's record.", "high",
            {}, ["analysed evidence"], r9_evidence_mismatch),
    RuleDef("R10", "Shared device", "The session device is used by other accounts.", "medium",
            {"min_other_accounts": 1}, ["device links"], r10_shared_device),
    RuleDef("R11", "Funds left this bank", "Disputed funds may have moved to another institution.", "medium",
            {"min_share": 0.1}, ["attribution"], r11_external_exit),
    RuleDef("R12", "Record inconsistency", "Missing or conflicting payment references on the trail.", "low",
            {}, ["transaction references"], r12_record_inconsistency),
    RuleDef("R13", "Many payments in a short time", "The payer made many payments in a short time around the disputed payment.",
            "medium", {"window_minutes": 30, "min_payments": 5}, ["payer debit history"], r13_velocity),
    RuleDef("R14", "First payment to this beneficiary", "A large payment to an account the payer had not paid before.", "medium",
            {"lookback_days": 180, "min_history": 5, "min_amount_rupees": 10000}, ["payer debit history"], r14_new_beneficiary),
    RuleDef("R15", "Payments just below a review limit", "Several payments just under an internal review limit.", "low",
            {"window_hours": 24, "min_below_limit": 2, "review_limit_rupees": 50000, "band_share": 0.1},
            ["payer debit history"], r15_below_limit),
]
CATALOGUE_BY_ID = {r.rule_id: r for r in CATALOGUE}


def ruleset_version(overrides: dict[str, tuple[int, dict, bool]]) -> str:
    payload = {r.rule_id: overrides.get(r.rule_id, (1, r.default_params, True)) for r in CATALOGUE}
    h = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return f"rules-{h}"


def evaluate(ctx: RuleContext, overrides: dict[str, tuple[int, dict, bool]] | None = None) -> list[RuleResult]:
    """Evaluate every enabled rule. ``overrides`` maps rule_id -> (version, params, enabled)."""
    overrides = overrides or {}
    now = (ctx.now or datetime.utcnow()).isoformat() + "Z"
    out: list[RuleResult] = []
    for rd in CATALOGUE:
        version, params, enabled = overrides.get(rd.rule_id, (1, rd.default_params, True))
        if not enabled:
            continue
        merged = {**rd.default_params, **(params or {})}
        r = RuleResult(rule_id=rd.rule_id, name=rd.name, version=version, severity=rd.default_severity,
                       status=NOT_EVALUABLE, params=merged, evaluated_at=now)
        try:
            rd.fn(ctx, merged, r)
        except Exception as exc:  # a broken rule must never look like a clear result
            r.status = NOT_EVALUABLE
            r.missing_fields = [f"rule error: {type(exc).__name__}"]
        if r.status == NOT_EVALUABLE:
            r.limitations.insert(0, "Not evaluable: the data this rule needs is missing. This is not a negative finding.")
        r.source_ids = list(dict.fromkeys(i for i in r.source_ids if i))
        out.append(r)
    return out


def summarise(results: list[RuleResult]) -> dict[str, Any]:
    sev_rank = {"high": 3, "medium": 2, "low": 1}
    trig = [r for r in results if r.status == TRIGGERED]
    return {
        "triggered": len(trig),
        "not_triggered": sum(1 for r in results if r.status == NOT_TRIGGERED),
        "not_evaluable": sum(1 for r in results if r.status == NOT_EVALUABLE),
        "highest_severity": max((r.severity for r in trig), key=lambda s: sev_rank[s], default=None),
        "by_severity": {s: sum(1 for r in trig if r.severity == s) for s in ("high", "medium", "low")},
    }
