"""Checks ideas about where the disputed money went against the ledger: "Gemini proposes, the ledger proves".

Gemini (or, when AI is unavailable, the fixed detectors below) states ideas in a small, typed claim language.
This module evaluates every claim with deterministic code over the same facts the rest of the workspace uses
(`build_context`: the trace graph, the attribution bounds, rule results) plus bounded device and case-link
lookups. The AI never computes a figure here; it only proposes claims for code to test.

Verdict of one check:
- ``proven``        the records force it (a confirmed record, or a derived lower bound from balance arithmetic)
- ``possible``      consistent with the records (within the upper bound / an inferred link) but not forced
- ``refuted``       the records contradict it (above the upper bound, no recorded path, threshold not met)
- ``cannot_check``  the data needed is missing (another bank, the trail stopped early, no device records)

A hypothesis takes its weakest check's verdict. A hypothesis that names an account or payment id that is not in
this case's records is rejected as ``invented``: it is counted and shown, never silently dropped.
Money stays in integer minor units (paise) until it is formatted for display.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Annotated, Literal, Union

import networkx as nx
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.services.graph_store import SqlGraphStore
from app.services.trace import fmt_amount

PROVEN, POSSIBLE, REFUTED, CANNOT_CHECK, INVENTED = "proven", "possible", "refuted", "cannot_check", "invented"
VERDICTS = (PROVEN, POSSIBLE, REFUTED, CANNOT_CHECK, INVENTED)
_RANK = {REFUTED: 0, CANNOT_CHECK: 1, POSSIBLE: 2, PROVEN: 3}  # lower is weaker; a hypothesis takes its weakest check

PATTERNS = ("fan_out", "layering_chain", "round_trip", "cash_out", "mule_reuse", "rapid_pass_through")
PATTERN_LABELS = {
    "fan_out": "Split to several accounts",
    "layering_chain": "Passed along a chain of accounts",
    "round_trip": "Came back round",
    "cash_out": "Taken out as cash",
    "mule_reuse": "Receiving account used in other disputes",
    "rapid_pass_through": "Passed on straight away",
}
MAX_CHECKS = 3
DEVICE_LOOKUP_LIMIT = 200
ID_TOKEN = re.compile(r"\b(?:ACC|TXN|DEV|AUTH|CASE)-[A-Z0-9]+\b")


# ---- The claim language ------------------------------------------------------------------------------

class _Claim(BaseModel):
    model_config = {"extra": "ignore"}


class FlowAtLeast(_Claim):
    """At least this much of the disputed money moved from one account to another (directly or along the trail)."""
    kind: Literal["flow_at_least"]
    from_account: str = Field(min_length=3, max_length=40)
    to_account: str = Field(min_length=3, max_length=40)
    amount_rupees: float = Field(gt=0, le=1e11)


class StillInAccount(_Claim):
    """At least this much of the disputed money may still be in the account at the end of the traced period."""
    kind: Literal["still_in_account"]
    account: str = Field(min_length=3, max_length=40)
    amount_rupees: float = Field(gt=0, le=1e11)


class LeftBank(_Claim):
    """At least this much of the disputed money left this bank (another bank or cash: visibility ends)."""
    kind: Literal["left_bank"]
    amount_rupees: float = Field(gt=0, le=1e11)


class RapidPassThrough(_Claim):
    """The account sent on at least share_pct of what reached it within within_minutes of the first arrival."""
    kind: Literal["rapid_pass_through"]
    account: str = Field(min_length=3, max_length=40)
    share_pct: float = Field(gt=0, le=100)
    within_minutes: int = Field(ge=1, le=10080)


class SharedDevice(_Claim):
    """The two accounts were used from the same device."""
    kind: Literal["shared_device"]
    account_a: str = Field(min_length=3, max_length=40)
    account_b: str = Field(min_length=3, max_length=40)


class LinkedDisputes(_Claim):
    """The account is the receiving account in at least min_cases other disputes on record."""
    kind: Literal["linked_disputes"]
    account: str = Field(min_length=3, max_length=40)
    min_cases: int = Field(ge=1, le=50)


class Typology(_Claim):
    """A named money-movement pattern (see PATTERNS)."""
    kind: Literal["typology"]
    pattern: Literal["fan_out", "layering_chain", "round_trip", "cash_out", "mule_reuse", "rapid_pass_through"]


Check = Annotated[Union[FlowAtLeast, StillInAccount, LeftBank, RapidPassThrough, SharedDevice, LinkedDisputes, Typology],
                  Field(discriminator="kind")]
CHECK_KINDS = ("flow_at_least", "still_in_account", "left_bank", "rapid_pass_through", "shared_device", "linked_disputes", "typology")
_ADAPTER = TypeAdapter(Check)


def parse_check(raw: dict) -> tuple[BaseModel | None, str | None]:
    """A typed check from a loose dict (unused keys and nulls ignored). Returns (check, None) or (None, problem)."""
    clean = {k: v for k, v in (raw or {}).items() if v is not None and v != ""}
    try:
        return _ADAPTER.validate_python(clean), None
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e.get("loc", [])[1:]) or str(e.get("loc", ["?"])[0]) for e in exc.errors()})
        return None, "incomplete or out-of-range values: " + ", ".join(fields)


def account_ids(check: BaseModel) -> list[str]:
    return [getattr(check, f) for f in ("from_account", "to_account", "account", "account_a", "account_b") if getattr(check, f, None)]


def _minor(rupees: float) -> int:
    return int(round(float(rupees) * 100))


def _when(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso.rstrip("Z")) if iso else None


# ---- The ledger view the checks run against -----------------------------------------------------------

class Ledger:
    """Read-only facts for one case, built once from `build_context` and shared by every check."""

    def __init__(self, db: Session, ctx: dict, known_ids: set[str] | None = None):
        self.db, self.ctx = db, ctx
        self.store = SqlGraphStore(db)
        g, att = ctx["graph"], ctx["attribution"]
        self.att = att
        self.case_id = ctx["case"]["id"]
        self.cur = att.get("currency") or ctx["case"].get("currency") or "INR"
        self.amount = att.get("disputed_amount_minor") or ctx["disputed_transaction"].get("amount_minor") or 0
        self.root_id = g["root_txn_id"]
        self.accounts = {n["id"]: n for n in g["nodes"] if n["type"] == "account"}
        self.txns = {n["id"]: n for n in g["nodes"] if n["type"] == "transaction"}
        self.payer = ctx["disputed_transaction"]["debit_account_id"]
        self.beneficiary = ctx["disputed_transaction"]["credit_account_id"]
        self.per_txn = att.get("per_transaction") or {}
        self.evaluable = bool(att.get("evaluable"))
        # The trail: the disputed payment and onward payments that moved money and were not reversed.
        self.trail = sorted(
            (n for n in self.txns.values() if n.get("direction") in ("root", "forward") and n["data"]["status"] in ("posted", "pending")),
            key=lambda n: (n["data"]["occurred_at"], n["id"]))
        self.flow = nx.DiGraph()
        for n in self.trail:
            self.flow.add_edge(n["data"]["debit_account_id"], n["data"]["credit_account_id"])
        try:
            self.idom = nx.immediate_dominators(self.flow, self.payer) if self.payer in self.flow else {}
        except nx.NetworkXError:
            self.idom = {}
        stops = {n.get("endpoint") for n in self.accounts.values()}
        beyond = max((b.get("beyond_trace_limits") or 0) for b in (att.get("buckets") or {}).values()) if att.get("buckets") else 0
        # The search stopped before the money's trail ended: absence of a pattern is then "can't check", not "ruled out".
        self.incomplete = bool(g.get("truncated") or stops & {"depth_limit", "truncated", "hub_paused"} or beyond > 0)
        self.known = set(known_ids) if known_ids is not None else self._known_ids()

    def _known_ids(self) -> set[str]:
        from app.ai.snapshot import build_snapshot, referenced_records  # lazy: services do not depend on app.ai at import

        return set(build_snapshot(self.ctx, referenced_records(self.db, self.ctx))["records"])

    # -- helpers --------------------------------------------------------------------------------------
    def money(self, minor: int | None) -> str:
        return "unknown" if minor is None else fmt_amount(int(minor), self.cur)

    def name(self, acct_id: str) -> str:
        n = self.accounts.get(acct_id)
        label = (n or {}).get("label") or ""
        if not label:
            a = self.store.get_account(acct_id)
            label = a.holder_label if a else ""
        label = label.replace(" (synthetic)", "").strip()
        return f"{label} ({acct_id})" if label else acct_id

    def bounds(self, txn_id: str) -> tuple[int, int]:
        """(least, most) of the disputed money this trail payment can carry, from attribution."""
        if txn_id == self.root_id:
            return self.amount, self.amount
        a = self.per_txn.get(txn_id)
        if not a:
            return 0, 0
        return int(a.get("min") or 0), int(a.get("max") or 0)

    def inflows(self, acct_id: str) -> list[dict]:
        return [n for n in self.trail if n["data"]["credit_account_id"] == acct_id]

    def outflows(self, acct_id: str) -> list[dict]:
        return [n for n in self.trail if n["data"]["debit_account_id"] == acct_id]

    def inflow_bounds(self, acct_id: str) -> tuple[int, int, list[str]]:
        lo = hi = 0
        ids = []
        for n in self.inflows(acct_id):
            a, b = self.bounds(n["id"])
            lo, hi = lo + a, hi + b
            ids.append(n["id"])
        return lo, hi, ids

    def dominates(self, a: str, b: str) -> bool:
        """True when every recorded route from the payer to b passes through a (so all disputed money reaching b came via a)."""
        if a == self.payer:
            return b in self.idom
        cur, guard = b, 0
        while cur in self.idom and guard < 100:
            if cur == a:
                return True
            nxt = self.idom[cur]
            if nxt == cur:
                return False
            cur, guard = nxt, guard + 1
        return False

    def reaches(self, a: str, b: str) -> bool:
        return a in self.flow and b in self.flow and a != b and nx.has_path(self.flow, a, b)

    def internal(self, acct_id: str) -> bool:
        n = self.accounts.get(acct_id)
        return bool(n) and not n["data"].get("external")


def _result(verdict: str, summary: str, figures: list[tuple[str, str]] | None = None, record_ids: list[str] | None = None,
            amounts: dict | None = None) -> dict:
    return {"verdict": verdict, "summary": summary, "figures": [{"label": k, "value": v} for k, v in (figures or [])],
            "record_ids": list(dict.fromkeys(i for i in (record_ids or []) if i)), "amounts_minor": amounts or {}}


def _range_verdict(claimed: int, lo: int, hi: int) -> str:
    if claimed <= lo and lo > 0:
        return PROVEN
    if claimed <= hi:
        return POSSIBLE
    return REFUTED


# ---- Plain-language description of a claim (code-written) ---------------------------------------------

def describe(check: BaseModel, lg: Ledger) -> str:
    k = check.kind
    if k == "flow_at_least":
        return (f"At least {lg.money(_minor(check.amount_rupees))} of the disputed money went from {lg.name(check.from_account)} "
                f"to {lg.name(check.to_account)}.")
    if k == "still_in_account":
        return f"At least {lg.money(_minor(check.amount_rupees))} of the disputed money may still be in {lg.name(check.account)}."
    if k == "left_bank":
        return f"At least {lg.money(_minor(check.amount_rupees))} of the disputed money has left this bank."
    if k == "rapid_pass_through":
        return (f"{lg.name(check.account)} sent on at least {check.share_pct:g}% of what it received within "
                f"{check.within_minutes} minutes.")
    if k == "shared_device":
        return f"{lg.name(check.account_a)} and {lg.name(check.account_b)} were used from the same device."
    if k == "linked_disputes":
        return f"{lg.name(check.account)} received money in at least {check.min_cases} other dispute(s)."
    return f"Pattern: {PATTERN_LABELS.get(check.pattern, check.pattern).lower()}."


# ---- The checks --------------------------------------------------------------------------------------

def _not_on_trail(lg: Ledger, acct: str) -> dict:
    if lg.incomplete:
        return _result(CANNOT_CHECK, f"{lg.name(acct)} is not on the traced trail, and the search stopped before the trail ended, "
                                     "so the records here cannot say.", record_ids=[acct])
    return _result(REFUTED, f"{lg.name(acct)} is not on the traced trail: the bank's records show no disputed money reaching it "
                            "in the traced period.", record_ids=[acct])


def check_flow(c: FlowAtLeast, lg: Ledger) -> dict:
    a, b, claimed = c.from_account, c.to_account, _minor(c.amount_rupees)
    if a == b:
        return _result(CANNOT_CHECK, "The idea names the same account twice, so there is no movement to check.", record_ids=[a])
    if not lg.evaluable:
        return _result(CANNOT_CHECK, "The disputed payment did not move money (it failed or was reversed), so no amounts can be traced.",
                       record_ids=[lg.root_id])
    for acct in (a, b):
        if acct not in lg.accounts:
            return _not_on_trail(lg, acct)
    if not lg.reaches(a, b):
        return _result(REFUTED, f"The bank's records show no payments leading from {lg.name(a)} to {lg.name(b)} in the traced period, "
                                f"so none of the disputed money went that way.", [("Claimed", lg.money(claimed))], [a, b],
                       {"claimed": claimed, "lower": 0, "upper": 0})
    in_lo, in_hi, in_ids = lg.inflow_bounds(b)
    direct = [n for n in lg.outflows(a) if n["data"]["credit_account_id"] == b]
    direct_lo = sum(lg.bounds(n["id"])[0] for n in direct)
    via_all = lg.dominates(a, b)
    lo = in_lo if via_all else direct_lo
    hi = in_hi if a == lg.payer else min(in_hi, lg.inflow_bounds(a)[1])
    lo = min(lo, hi)
    verdict = _range_verdict(claimed, lo, hi)
    route = "directly" if direct and not via_all else "along the trail"
    if verdict == PROVEN:
        why = f"Balance arithmetic forces at least {lg.money(lo)} to have gone {route} from {lg.name(a)} to {lg.name(b)}, which covers {lg.money(claimed)}."
    elif verdict == POSSIBLE:
        why = (f"Up to {lg.money(hi)} could have gone from {lg.name(a)} to {lg.name(b)}, but the records only force {lg.money(lo)}, "
               f"so {lg.money(claimed)} is possible, not proven.")
    else:
        why = f"At most {lg.money(hi)} of the disputed money could have gone from {lg.name(a)} to {lg.name(b)}, so {lg.money(claimed)} is ruled out."
    return _result(verdict, why, [("Claimed", lg.money(claimed)), ("Least the records force", lg.money(lo)),
                                  ("Most the records allow", lg.money(hi))],
                   [a, b] + [n["id"] for n in direct] + in_ids, {"claimed": claimed, "lower": lo, "upper": hi})


def check_still(c: StillInAccount, lg: Ledger) -> dict:
    """Uses the account's attribution residual directly: under the 'disputed money spent first' (max) convention the
    residual is the least that can remain (forced lower bound); under 'clean money spent first' (min) it is the most
    that could remain (upper bound) — the same lower/upper roles these two methods play for onward transfers."""
    acct, claimed = c.account, _minor(c.amount_rupees)
    if acct not in lg.accounts:
        return _not_on_trail(lg, acct)
    if not lg.internal(acct):
        return _result(CANNOT_CHECK, f"{lg.name(acct)} is at another bank (or is cash), so this bank cannot see what it still holds.",
                       record_ids=[acct])
    info = (lg.att.get("per_account") or {}).get(acct)
    if info is None:
        reason = "it is the payer's own account" if acct == lg.payer else "the trail was not followed into it (a business, very busy or out-of-range account)"
        return _result(CANNOT_CHECK, f"The figures do not cover {lg.name(acct)}: {reason}.", record_ids=[acct])
    in_ids = lg.inflow_bounds(acct)[2]
    residual = info.get("residual") or {}
    bal = info.get("balance_at_window_end")
    lo_raw, hi_raw = residual.get("max"), residual.get("min")
    if lo_raw is None or hi_raw is None:
        return _result(CANNOT_CHECK, f"The 'disputed money spent first' or 'clean money spent first' figures for {lg.name(acct)} are not "
                                     "evaluable (an opening balance is unknown).", record_ids=[acct, f"ATTR-{acct}"])
    lo = max(0, min(lo_raw, bal)) if bal is not None else max(0, lo_raw)
    hi = max(0, min(hi_raw, bal)) if bal is not None else max(0, hi_raw)
    lo = min(lo, hi)
    vals = [v for v in residual.values() if v is not None]
    methods = f"{lg.money(min(vals))} to {lg.money(max(vals))}" if vals else "not available"
    verdict = _range_verdict(claimed, lo, hi)
    if verdict == PROVEN:
        why = f"The records force at least {lg.money(lo)} of the disputed money to still be in {lg.name(acct)} at the end of the traced period."
    elif verdict == POSSIBLE:
        why = (f"Up to {lg.money(hi)} of the disputed money could still be in {lg.name(acct)}, but the records only force {lg.money(lo)}, "
               f"so {lg.money(claimed)} is possible, not proven. A hold request is how to find out.")
    else:
        why = (f"At most {lg.money(hi)} of the disputed money can still be in {lg.name(acct)}"
               f"{'' if bal is None else f' (its balance was {lg.money(bal)})'}, so {lg.money(claimed)} is ruled out.")
    figs = [("Claimed", lg.money(claimed)), ("Least that must still be there", lg.money(lo)), ("Most that could still be there", lg.money(hi)),
            ("Balance at the end of the traced period", lg.money(bal)), ("The four tracing methods give", methods)]
    return _result(verdict, why, figs, [acct, f"ATTR-{acct}"] + in_ids, {"claimed": claimed, "lower": lo, "upper": hi, "balance": bal})


def check_left(c: LeftBank, lg: Ledger) -> dict:
    claimed = _minor(c.amount_rupees)
    if not lg.evaluable:
        return _result(CANNOT_CHECK, "The disputed payment did not move money (it failed or was reversed), so no amounts can be traced.",
                       record_ids=[lg.root_id])
    b = lg.att.get("buckets") or {}
    lo = int((b.get("min") or {}).get("left_visibility") or 0)
    hi = int((b.get("max") or {}).get("left_visibility") or 0)
    exits = sorted((lg.att.get("exits") or {}).keys())
    ids = exits + [n["id"] for n in lg.trail if n["data"]["credit_account_id"] in exits]
    verdict = _range_verdict(claimed, lo, hi)
    if verdict == REFUTED and lg.incomplete:
        verdict = CANNOT_CHECK
        why = (f"Within the traced trail at most {lg.money(hi)} left this bank, but the search stopped before the trail ended, so more "
               "may have left later.")
    elif verdict == PROVEN:
        why = f"The records force at least {lg.money(lo)} of the disputed money to have left this bank, which covers {lg.money(claimed)}."
    elif verdict == POSSIBLE:
        why = f"Up to {lg.money(hi)} may have left this bank, but the records only force {lg.money(lo)}, so {lg.money(claimed)} is possible, not proven."
    else:
        why = f"At most {lg.money(hi)} of the disputed money left this bank in the traced period, so {lg.money(claimed)} is ruled out."
    return _result(verdict, why, [("Claimed", lg.money(claimed)), ("Least that must have left", lg.money(lo)),
                                  ("Most that could have left", lg.money(hi))], ids, {"claimed": claimed, "lower": lo, "upper": hi})


def check_rapid(c: RapidPassThrough, lg: Ledger) -> dict:
    acct = c.account
    if acct not in lg.accounts:
        return _not_on_trail(lg, acct)
    if not lg.internal(acct):
        return _result(CANNOT_CHECK, f"{lg.name(acct)} is at another bank (or is cash), so this bank cannot see what it did next.",
                       record_ids=[acct])
    node = lg.accounts[acct]
    if node.get("endpoint") in ("merchant", "hub_paused") or acct == lg.payer:
        return _result(CANNOT_CHECK, f"{lg.name(acct)} is a business, very busy or the payer's own account; its onward payments are not "
                                     "followed, so this cannot be checked here.", record_ids=[acct])
    ins = lg.inflows(acct)
    if not ins:
        return _result(CANNOT_CHECK, f"No recorded payment on the trail reached {lg.name(acct)}.", record_ids=[acct])
    first = _when(ins[0]["data"]["occurred_at"])
    end = first + timedelta(minutes=c.within_minutes)
    received = sum(n["data"]["amount_minor"] for n in ins if _when(n["data"]["occurred_at"]) <= end)
    rows = [t for t in lg.store.outgoing(acct, first, end, 200) if t.moved_money and t.status != "reversed"]
    sent, reached_at, used = 0, None, []
    for t in rows:
        sent += t.amount_minor
        used.append(t.id)
        if reached_at is None and received and sent * 100 >= c.share_pct * received:
            reached_at = round((t.occurred_at - first).total_seconds() / 60, 1)
    share = round(100 * sent / received, 1) if received else 0.0
    ok = share >= c.share_pct
    if ok:
        why = (f"{lg.name(acct)} received {lg.money(received)} and sent on {lg.money(sent)} ({share:g}%) within {c.within_minutes} minutes; "
               f"the {c.share_pct:g}% mark was passed after {reached_at:g} minutes. These are recorded payments.")
    else:
        why = (f"{lg.name(acct)} sent on {lg.money(sent)} of the {lg.money(received)} it received ({share:g}%) within {c.within_minutes} minutes, "
               f"below the {c.share_pct:g}% in the idea.")
    figs = [("Received", lg.money(received)), (f"Sent on within {c.within_minutes} min", lg.money(sent)), ("Share sent on", f"{share:g}%")]
    if reached_at is not None:
        figs.append((f"Minutes to pass {c.share_pct:g}%", f"{reached_at:g}"))
    return _result(PROVEN if ok else REFUTED, why, figs, [acct] + [n["id"] for n in ins] + used,
                   {"received": received, "sent": sent, "share_pct": share, "minutes": reached_at})


def _devices(lg: Ledger, acct: str) -> dict[str, list[str]]:
    """Device id -> example record ids (payments and sign-ins) for one account, bounded."""
    out: dict[str, list[str]] = {}
    for tid, dev in lg.db.execute(select(m.Transaction.id, m.Transaction.device_id).where(
            m.Transaction.debit_account_id == acct, m.Transaction.device_id.is_not(None)).limit(DEVICE_LOOKUP_LIMIT)).all():
        out.setdefault(dev, []).append(tid)
    for aid, dev in lg.db.execute(select(m.AuthEvent.id, m.AuthEvent.device_id).where(
            m.AuthEvent.account_id == acct, m.AuthEvent.device_id.is_not(None)).limit(DEVICE_LOOKUP_LIMIT)).all():
        out.setdefault(dev, []).append(aid)
    return out


def check_device(c: SharedDevice, lg: Ledger) -> dict:
    a, b = c.account_a, c.account_b
    if a == b:
        return _result(CANNOT_CHECK, "The idea names the same account twice.", record_ids=[a])
    da, db_ = _devices(lg, a), _devices(lg, b)
    if not da or not db_:
        missing = [lg.name(x) for x, d in ((a, da), (b, db_)) if not d]
        return _result(CANNOT_CHECK, f"There are no device records for {' or '.join(missing)}, so this cannot be checked.", record_ids=[a, b])
    shared = sorted(set(da) & set(db_))
    if shared:
        ids = [a, b] + shared + [x for d in shared for x in (da[d][:2] + db_[d][:2])]
        return _result(PROVEN, f"Device {', '.join(shared)} was used on both {lg.name(a)} and {lg.name(b)} (recorded payments or sign-ins).",
                       [("Shared devices", ", ".join(shared))], ids, {})
    return _result(REFUTED, f"The device records show no device used on both {lg.name(a)} and {lg.name(b)}.",
                   [("Devices on the first account", str(len(da))), ("Devices on the second account", str(len(db_)))], [a, b], {})


def check_linked(c: LinkedDisputes, lg: Ledger) -> dict:
    acct = c.account
    links = sorted({(l.case_id, l.disputed_txn_id) for l in lg.store.cases_with_beneficiaries([acct]) if l.case_id != lg.case_id})
    n = len(links)
    ids = [acct] + [cid for cid, _ in links]
    figs = [("Other disputes where it received the money", str(n))]
    if n >= c.min_cases:
        return _result(PROVEN, f"{lg.name(acct)} is the receiving account in {n} other dispute(s) on record: {', '.join(cid for cid, _ in links)}.",
                       figs, ids, {"cases": n})
    return _result(REFUTED, f"{lg.name(acct)} is the receiving account in {n} other dispute(s) on record, fewer than {c.min_cases}. "
                            "Only disputes recorded at this bank are compared.", figs, ids, {"cases": n})


def _pattern_result(lg: Ledger, verdict: str, why: str, figs, ids, none_why: str) -> dict:
    if verdict == REFUTED and lg.incomplete:
        return _result(CANNOT_CHECK, none_why + " The search stopped before the trail ended, so it may happen further on.", figs, ids)
    return _result(verdict, why if verdict != REFUTED else none_why, figs, ids)


def _chains(lg: Ledger) -> tuple[list[str], list[str]]:
    """Longest time-ordered chain of trail payments from the disputed payment where each step carries disputed money:
    (forced at every step, possible at every step)."""
    best: dict[str, list[str]] = {"lo": [], "hi": []}

    def walk(path: list[str], key: str, idx: int):
        if len(path) > len(best[key]):
            best[key] = list(path)
        last = lg.txns[path[-1]]["data"]
        t_last = last["occurred_at"]
        for n in lg.outflows(last["credit_account_id"]):
            if n["id"] in path or n["data"]["occurred_at"] < t_last or len(path) > 20:
                continue
            if lg.bounds(n["id"])[idx] > 0:
                walk(path + [n["id"]], key, idx)

    if lg.root_id in lg.txns:
        walk([lg.root_id], "lo", 0)
        walk([lg.root_id], "hi", 1)
    return best["lo"], best["hi"]


def check_typology(c: Typology, lg: Ledger) -> dict:
    p = c.pattern
    if p == "mule_reuse":
        accts = [a for a in lg.accounts if a != lg.payer]
        links = [l for l in lg.store.cases_with_beneficiaries(accts) if l.case_id != lg.case_id]
        by: dict[str, set[str]] = {}
        for l in links:
            by.setdefault(l.beneficiary_account_id, set()).add(l.case_id)
        if by:
            parts = [f"{lg.name(a)} in {', '.join(sorted(cs))}" for a, cs in sorted(by.items())]
            return _result(PROVEN, "Accounts on this trail received the money in other disputes on record: " + "; ".join(parts) + ".",
                           [("Accounts reused", str(len(by))), ("Other disputes", str(len({c for cs in by.values() for c in cs})))],
                           list(by) + sorted({c for cs in by.values() for c in cs}))
        return _result(REFUTED, f"None of the {len(accts)} accounts on this trail received money in another dispute recorded at this bank.",
                       record_ids=accts)
    if p == "rapid_pass_through":
        r1 = next((r for r in lg.ctx["rules"] if r["rule_id"] == "R1"), None)
        prm = (r1 or {}).get("params") or {"window_minutes": 60, "min_share": 0.8}
        return check_rapid(RapidPassThrough(kind="rapid_pass_through", account=lg.beneficiary,
                                            share_pct=round(float(prm["min_share"]) * 100, 1), within_minutes=int(prm["window_minutes"])), lg)
    if not lg.evaluable:
        return _result(CANNOT_CHECK, "The disputed payment did not move money (it failed or was reversed), so no pattern can be traced.",
                       record_ids=[lg.root_id])
    if p == "fan_out":
        best = (None, [], [])
        for acct in lg.accounts:
            if acct == lg.payer:
                continue
            outs = lg.outflows(acct)
            forced = sorted({n["data"]["credit_account_id"] for n in outs if lg.bounds(n["id"])[0] > 0})
            maybe = sorted({n["data"]["credit_account_id"] for n in outs if lg.bounds(n["id"])[1] > 0})
            if (len(forced), len(maybe)) > (len(best[1]), len(best[2])):
                best = (acct, forced, maybe)
        acct, forced, maybe = best
        verdict = PROVEN if len(forced) >= 2 else POSSIBLE if len(maybe) >= 2 else REFUTED
        ids = ([acct] if acct else []) + [n["id"] for n in lg.outflows(acct or "") if lg.bounds(n["id"])[1] > 0] + maybe
        why = (f"{lg.name(acct)} sent disputed money on to {len(maybe)} different accounts; the records force it for {len(forced)} of them."
               if acct else "")
        return _pattern_result(lg, verdict, why, [("Destinations", str(len(maybe))), ("Forced by the records", str(len(forced)))] if acct else [],
                               ids, "No account on the trail sent disputed money on to two or more different accounts.")
    if p == "layering_chain":
        lo, hi = _chains(lg)
        verdict = PROVEN if len(lo) >= 3 else POSSIBLE if len(hi) >= 3 else REFUTED
        chain = lo if verdict == PROVEN else hi
        hops = " → ".join(lg.name(a) for a in [lg.txns[chain[0]]["data"]["debit_account_id"]] +
                          [lg.txns[t]["data"]["credit_account_id"] for t in chain]) if chain else ""
        why = (f"The disputed money crossed {len(chain)} payments in a row: {hops}. "
               + ("Balance arithmetic forces disputed money on every step." if verdict == PROVEN
                  else "Each step could carry disputed money, but the records do not force it on every step."))
        return _pattern_result(lg, verdict, why, [("Longest chain (forced)", f"{len(lo)} payments"), ("Longest chain (possible)", f"{len(hi)} payments")],
                               chain, f"The longest chain of payments carrying disputed money is {len(hi)} payment(s); a chain needs at least 3.")
    if p == "round_trip":
        closing = []
        for acct, node in lg.accounts.items():
            if node.get("endpoint") != "cycle" and acct != lg.payer:
                continue
            ins = lg.inflows(acct)
            first = None if acct == lg.payer else (ins[0]["id"] if ins else None)
            closing += [n["id"] for n in ins if n["id"] != first and n["id"] != lg.root_id]
        lo = sum(lg.bounds(t)[0] for t in closing)
        hi = sum(lg.bounds(t)[1] for t in closing)
        verdict = PROVEN if lo > 0 else POSSIBLE if hi > 0 else REFUTED
        why = (f"Money came back to an account it had already passed through ({', '.join(closing)}): between {lg.money(lo)} and {lg.money(hi)} "
               "of it could be the disputed money.")
        ids = closing + [lg.txns[t]["data"]["credit_account_id"] for t in closing]
        return _pattern_result(lg, verdict, why, [("Came back (forced)", lg.money(lo)), ("Came back (most)", lg.money(hi))], ids,
                               "The records show no disputed money coming back to an account it had already passed through.")
    # cash_out
    cash = [n for n in lg.trail if n["id"] != lg.root_id and (n["data"].get("channel") == "ATM" or
            (lg.accounts.get(n["data"]["credit_account_id"]) or {}).get("data", {}).get("kind") == "cash")]
    if lg.root_id in lg.txns and (lg.accounts.get(lg.beneficiary) or {}).get("data", {}).get("kind") == "cash":
        cash.insert(0, lg.txns[lg.root_id])
    lo = sum(lg.bounds(n["id"])[0] for n in cash)
    hi = sum(lg.bounds(n["id"])[1] for n in cash)
    verdict = PROVEN if lo > 0 else POSSIBLE if hi > 0 else REFUTED
    ids = [n["id"] for n in cash] + [n["data"]["credit_account_id"] for n in cash]
    return _pattern_result(lg, verdict, f"Between {lg.money(lo)} and {lg.money(hi)} of the disputed money was taken out as cash.",
                           [("Cash (forced)", lg.money(lo)), ("Cash (most)", lg.money(hi))], ids,
                           "The trail shows no disputed money taken out as cash.")


_CHECKERS = {"flow_at_least": check_flow, "still_in_account": check_still, "left_bank": check_left, "rapid_pass_through": check_rapid,
             "shared_device": check_device, "linked_disputes": check_linked, "typology": check_typology}


def run_check(raw: dict, lg: Ledger) -> dict:
    """Evaluate one check (a loose dict in the claim language). Never raises for bad input."""
    check, problem = parse_check(raw)
    kind = (raw or {}).get("kind")
    if check is None:
        return {"kind": kind, "check": {k: v for k, v in (raw or {}).items() if v is not None}, "claim": "An incomplete check.",
                **_result(CANNOT_CHECK, f"This check could not be read ({problem}).")}
    unknown = [a for a in account_ids(check) if a not in lg.known]
    base = {"kind": check.kind, "check": check.model_dump(), "claim": describe(check, lg)}
    if unknown:
        return {**base, **_result(CANNOT_CHECK, f"{', '.join(unknown)} is not in this case's records.", record_ids=[]), "unknown_ids": unknown}
    try:
        return {**base, **_CHECKERS[check.kind](check, lg)}
    except Exception as exc:  # a broken check must never look like a finding
        return {**base, **_result(CANNOT_CHECK, f"This check could not be completed ({type(exc).__name__}).")}


def overall(verdicts: list[str]) -> str:
    vs = [v for v in verdicts if v in _RANK]
    return min(vs, key=_RANK.get) if vs else CANNOT_CHECK


def check_hypothesis(raw: dict, lg: Ledger) -> dict:
    """Evaluate a proposed hypothesis: {statement, rationale, typology, record_ids, checks, source}."""
    checks = list(raw.get("checks") or [])[:MAX_CHECKS]
    results = [run_check(c, lg) for c in checks]
    texts = " ".join(str(raw.get(k) or "") for k in ("statement", "rationale"))
    mentioned = set(ID_TOKEN.findall(texts)) | {str(i) for i in (raw.get("record_ids") or [])}
    for r in results:
        mentioned |= set(r.get("unknown_ids") or [])
    invented = sorted(i for i in mentioned if i not in lg.known)
    verdict = INVENTED if invented else overall([r["verdict"] for r in results]) if results else CANNOT_CHECK
    return {"statement": str(raw.get("statement") or "")[:500], "rationale": str(raw.get("rationale") or "")[:800],
            "typology": raw.get("typology") or "other", "source": raw.get("source") or "ai",
            "record_ids": [i for i in dict.fromkeys(str(x) for x in (raw.get("record_ids") or [])) if i][:12],
            "verdict": verdict, "invented_ids": invented, "checks": results}


def counts(hyps: list[dict]) -> dict:
    return {v: sum(1 for h in hyps if h["verdict"] == v) for v in VERDICTS}


# ---- Standard ideas from the detectors (used when AI is unavailable) ------------------------------------

_PATTERN_STATEMENTS = {
    "fan_out": "The money was split and sent on to several accounts soon after it arrived.",
    "layering_chain": "The money was passed along a chain of accounts, which makes it harder to follow.",
    "round_trip": "Some of the money came back round to an account it had already passed through.",
    "cash_out": "Some of the money may have been taken out as cash.",
    "mule_reuse": "An account that received the money also received money in other disputes, so it may be used again and again to collect it.",
    "rapid_pass_through": "The receiving account passed the money on almost as soon as it arrived.",
}


def system_hypotheses(lg: Ledger, limit: int = 6) -> list[dict]:
    """Standard ideas built by code from the typology detectors, the hold candidates and the exits (no AI)."""
    out: list[dict] = []
    if lg.evaluable:
        hold = next(iter(lg.att.get("holdable") or []), None)
        if hold:
            r = check_still(StillInAccount(kind="still_in_account", account=hold["account_id"], amount_rupees=max(hold["max_minor"], 1) / 100), lg)
            lo = r["amounts_minor"].get("lower") or 0
            amt = lo if lo > 0 else r["amounts_minor"].get("upper") or hold["max_minor"]
            if amt > 0:
                out.append({"statement": f"Some of the disputed money may still be in {lg.name(hold['account_id'])}, so a hold request could recover it.",
                            "rationale": "From the hold suggestions worked out by balance arithmetic.", "typology": "other",
                            "record_ids": [hold["account_id"], f"HOLD-{hold['account_id']}"],
                            "checks": [{"kind": "still_in_account", "account": hold["account_id"], "amount_rupees": amt / 100}]})
        b = lg.att.get("buckets") or {}
        lo = int((b.get("min") or {}).get("left_visibility") or 0)
        hi = int((b.get("max") or {}).get("left_visibility") or 0)
        if hi > 0:
            exits = sorted((lg.att.get("exits") or {}).keys())
            out.append({"statement": "Part of the money has already left this bank, so the receiving banks need to be asked to trace and hold it.",
                        "rationale": "From the trail's exits to other banks or cash.", "typology": "other", "record_ids": exits[:6],
                        "checks": [{"kind": "left_bank", "amount_rupees": (lo if lo > 0 else hi) / 100}]})
    for p in PATTERNS:
        r = check_typology(Typology(kind="typology", pattern=p), lg)
        if r["verdict"] not in (PROVEN, POSSIBLE):
            continue
        checks = [{"kind": "typology", "pattern": p}]
        ids = [i for i in r["record_ids"] if i in lg.known][:6]
        if p == "mule_reuse":
            reused = [i for i in r["record_ids"] if i in lg.accounts][:1]
            checks += [{"kind": "linked_disputes", "account": a, "min_cases": 1} for a in reused]
        out.append({"statement": _PATTERN_STATEMENTS[p], "rationale": "Found by the system's fixed pattern detectors.", "typology": p,
                    "record_ids": ids, "checks": checks})
    return [{**h, "source": "system"} for h in out[:limit]]


# ---- Code-written answers for "Ask the ledger" -----------------------------------------------------------

ANSWER_LEAD = {
    PROVEN: "Yes. The bank's records prove this.",
    POSSIBLE: "Possibly. The records allow this but do not prove it.",
    REFUTED: "No. The bank's records rule this out.",
    CANNOT_CHECK: "The records available cannot answer this.",
    INVENTED: "This cannot be checked: it mentions an account or payment that is not in this case's records.",
}


def answer_text(verdict: str, results: list[dict]) -> str:
    """The answer shown to the investigator: a fixed lead for the verdict plus each check's code-written summary."""
    parts = [ANSWER_LEAD.get(verdict, ANSWER_LEAD[CANNOT_CHECK])]
    parts += [r["summary"] for r in results if r.get("summary")]
    return " ".join(parts)
