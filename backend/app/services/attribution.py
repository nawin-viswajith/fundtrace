"""Deterministic attribution of the disputed funds along the traced trail.

"Amounts add up" is not evidence. Money is fungible: once ₹50,000 lands in an account that already
holds other money, any later debit could be paid from either. This module answers, from ledger
balances alone, *how much of each onward transfer could be — or must be — the disputed funds*,
under four standard tracing conventions:

- ``max``      tainted-first: the most of each debit that could be disputed funds (upper bound)
- ``min``      clean-first, i.e. the lowest-intermediate-balance bound: the least that *must* be
               disputed funds given the balance (lower bound)
- ``fifo``     first-in-first-out by arrival of funds
- ``pro_rata`` proportional to the tainted share of the balance

If the lower bound is above zero, the link is **derived** (balance arithmetic forces it). If only the
upper bound is above zero, the link is **inferred** (possible, not established). Neither proves who
controlled the funds or why they moved.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from app.services.graph_store import GraphStore, TxnRec
from app.services.trace import DERIVED, INFERRED, TraceResult, fmt_amount

METHODS = ("min", "fifo", "pro_rata", "max")
METHOD_LABELS = {
    "min": "Lower bound (clean funds spent first; lowest intermediate balance)",
    "fifo": "First in, first out",
    "pro_rata": "Pro-rata (proportional mix)",
    "max": "Upper bound (disputed funds spent first)",
}
ACTIVITY_LIMIT = 500

# ---- Read-only description of the calculation (used by the calculation record) ----------------------
# Bump a method's version whenever its arithmetic in `_debit`/`_fifo_take` changes, and
# ATTRIBUTION_VERSION whenever anything else here changes the figures (what is collected, how
# reversals or sinks are treated). Recorded figures can then always be tied to the exact rules
# that produced them. These constants describe the code below; they do not drive it.
ATTRIBUTION_VERSION = "1.0"
METHOD_VERSIONS = {"min": "1.0", "fifo": "1.0", "pro_rata": "1.0", "max": "1.0"}
METHOD_DEFINITIONS = {
    "min": {
        "bound": "lower",
        "definition": "The account spends its other (clean) money before the disputed money, so each payment out carries "
                      "the least disputed money the balance allows. Also called the lowest-intermediate-balance rule.",
        "formula": "carried = min(T, max(0, d - max(0, B - T))); 0 when the balance B is unknown",
    },
    "fifo": {
        "bound": "estimate",
        "definition": "Money leaves the account in the order it arrived. The opening balance is the oldest (clean) money.",
        "formula": "take d from the oldest lots first; each lot contributes round(taken x lot_disputed / lot_amount); "
                   "not evaluable when the opening balance is unknown",
    },
    "pro_rata": {
        "bound": "estimate",
        "definition": "Every payment out carries the same share of disputed money as the account held at that moment.",
        "formula": "carried = min(T, round(d x T / B)); min(d, T) when B <= 0; not evaluable when B is unknown",
    },
    "max": {
        "bound": "upper",
        "definition": "The account spends the disputed money before anything else, so each payment out carries the most "
                      "disputed money possible.",
        "formula": "carried = min(d, T)",
    },
}
METHOD_SYMBOLS = ("d = payment amount, B = computed balance just before the payment, T = disputed money in the account "
                  "under that method just before the payment. After each payment: B' = B - d and T' = max(0, min(T - carried, B')).")
ATTRIBUTION_ASSUMPTIONS = (
    ("commingling", "Money in an account is mixed: the records cannot say which rupees left, so each method is a convention, "
                    "not an observation."),
    ("time_order", "Payments are applied strictly in time order (ties broken by transaction id); a payment can only carry "
                   "disputed money that had already arrived."),
    ("balances", "Each account's balance is its recorded opening balance plus all recorded money in and out before the "
                 "disputed money arrived, then updated payment by payment. If the opening balance is unknown, FIFO and "
                 "pro-rata are not worked out for that account."),
    ("external_not_visible", "Accounts at other banks are not visible: money sent there is counted as having left this bank's "
                             "view, not as spent or kept."),
    ("excluded_records", "Failed payments moved no money and are ignored. A reversed payment and the payment that reversed "
                         "it cancel out, so both are left out."),
    ("limits", "Only accounts reached within the search depth and time window are followed. Merchants and very busy "
               "accounts stop the trail; accounts past the depth limit are counted as 'went further than this search looked'."),
    ("activity_cap", f"At most {ACTIVITY_LIMIT} records are read per account; if an account has more, its figures may be incomplete."),
)


@dataclass
class _AcctState:
    balance: int | None
    taint: dict[str, int | None]
    lots: deque = field(default_factory=deque)  # FIFO lots: [amount, tainted_amount]


def attribute(store: GraphStore, res: TraceResult) -> dict:
    root = res.txns[res.root_txn_id]
    amount = root.amount_minor
    out: dict = {
        "disputed_txn_id": root.id,
        "disputed_amount_minor": amount,
        "currency": root.currency,
        "methods": METHOD_LABELS,
        "per_transaction": {},
        "per_account": {},
        "buckets": {},
        "coverage": {},
        "warnings": [],
        "caveat": (
            "Attribution is balance arithmetic over recorded transactions. A positive lower bound means "
            "the ledger forces at least that much to be the disputed funds; the upper bound means it is "
            "possible, not established. It does not show who controlled the funds or why they moved."
        ),
        "evaluable": True,
    }
    if not root.moved_money or root.status == "reversed":
        out["evaluable"] = False
        out["warnings"].append("Disputed transaction did not move money (failed) or was reversed.")
        return out

    payer_id = root.debit_account_id
    traced: set[str] = set()
    sinks: dict[str, str] = {}
    for acct_id in res.arrival:
        node = res.nodes.get(acct_id)
        acct = res.accounts.get(acct_id)
        if node is None or acct is None:
            continue
        if acct.external:
            sinks[acct_id] = "left_visibility"
        elif node.get("endpoint") in ("hub_paused", "merchant"):
            sinks[acct_id] = "reached_merchant_or_hub"
        elif node.get("endpoint") == "depth_limit":
            sinks[acct_id] = "beyond_trace_limits"
        else:
            traced.add(acct_id)

    # Collect every transaction touching traced accounts from their tainted arrival to window end,
    # including unrelated inflows/outflows (they change balances and therefore the bounds).
    events: dict[str, TxnRec] = {root.id: root}
    for acct_id in traced:
        rows = store.activity(acct_id, res.arrival[acct_id], res.window_end, ACTIVITY_LIMIT)
        if len(rows) >= ACTIVITY_LIMIT:
            out["warnings"].append(f"Activity for {acct_id} exceeds {ACTIVITY_LIMIT} rows; bounds may be incomplete.")
        for t in rows:
            events[t.id] = t

    # Reversed transfers and their reversals net to zero; exclude both from taint movement.
    reversed_ids = {t.id for t in events.values() if t.status == "reversed"}
    skip = reversed_ids | {t.id for t in events.values() if t.reversal_of_id in reversed_ids}

    state: dict[str, _AcctState] = {}

    def ensure(acct_id: str, at) -> _AcctState:
        if acct_id not in state:
            bal = store.balance_before(acct_id, at)
            st = _AcctState(balance=bal, taint={m: 0 for m in METHODS})
            if bal is None:
                out["warnings"].append(f"Opening balance of {acct_id} is unknown; FIFO and pro-rata are not evaluable there.")
            elif bal > 0:
                st.lots.append([bal, 0])
            state[acct_id] = st
        return state[acct_id]

    buckets = {m: {"residual_in_visible_accounts": 0, "left_visibility": 0, "reached_merchant_or_hub": 0,
                   "returned_to_payer": 0, "beyond_trace_limits": 0} for m in METHODS}
    exits: dict[str, dict[str, int | None]] = {}

    for t in sorted(events.values(), key=lambda x: (x.occurred_at, x.id)):
        if not t.moved_money or t.id in skip:
            continue
        d = t.amount_minor
        taint_out: dict[str, int | None] = {m: 0 for m in METHODS}

        if t.id == root.id:
            taint_in = {m: d for m in METHODS}
        else:
            taint_in = {m: 0 for m in METHODS}
            if t.debit_account_id in traced and t.debit_account_id in state:
                s = state[t.debit_account_id]
                taint_out = _debit(s, d, t, out["warnings"])
                taint_in = dict(taint_out)
                if any((v or 0) > 0 for v in taint_out.values()) or t.id in res.txns:
                    out["per_transaction"][t.id] = _summary(taint_out, d)

        if t.credit_account_id in traced:
            s = ensure(t.credit_account_id, t.occurred_at)
            if s.balance is not None:
                s.balance += d
            for m in METHODS:
                cur, add = s.taint[m], taint_in[m]
                s.taint[m] = None if cur is None or add is None else cur + add
            s.lots.append([d, taint_in["fifo"] or 0])
        elif t.debit_account_id in traced or t.id == root.id:
            # Funds leave the traced set (or the disputed payment itself lands somewhere we do not follow).
            sink = (
                "returned_to_payer" if t.credit_account_id == payer_id and t.id != root.id
                else sinks.get(t.credit_account_id)
                or ("left_visibility" if (res.accounts.get(t.credit_account_id) and res.accounts[t.credit_account_id].external) else "beyond_trace_limits")
            )
            moved = taint_in if t.id == root.id else taint_out
            for m in METHODS:
                v = moved[m]
                if v is None or buckets[m][sink] is None:
                    buckets[m][sink] = None
                else:
                    buckets[m][sink] += v
            if sink == "left_visibility":
                ex = exits.setdefault(t.credit_account_id, {m: 0 for m in METHODS})
                for m in METHODS:
                    ex[m] = None if ex[m] is None or moved[m] is None else ex[m] + moved[m]

    for acct_id, s in state.items():
        out["per_account"][acct_id] = {
            "residual": {m: s.taint[m] for m in METHODS},
            "balance_at_window_end": s.balance,
            "label": res.accounts[acct_id].holder_label if acct_id in res.accounts else acct_id,
        }
        for m in METHODS:
            v = s.taint[m]
            if v is None or buckets[m]["residual_in_visible_accounts"] is None:
                buckets[m]["residual_in_visible_accounts"] = None
            else:
                buckets[m]["residual_in_visible_accounts"] += v

    for m in METHODS:
        b = buckets[m]
        if any(v is None for v in b.values()):
            out["coverage"][m] = None
            b["unaccounted"] = None
            continue
        accounted = b["residual_in_visible_accounts"] + b["left_visibility"] + b["reached_merchant_or_hub"] + b["returned_to_payer"]
        b["unaccounted"] = amount - accounted - b["beyond_trace_limits"]
        out["coverage"][m] = round(accounted / amount, 4) if amount else None
    out["buckets"] = buckets
    out["exits"] = exits
    out["holdable"] = _holdable(out)
    return out


def _debit(s: _AcctState, d: int, t: TxnRec, warnings: list[str]) -> dict[str, int | None]:
    res: dict[str, int | None] = {}
    bal = s.balance
    if bal is not None and d > bal:
        warnings.append(f"{t.id}: debit exceeds computed balance (overdraft or missing records); bounds clamped.")
    for m in METHODS:
        T = s.taint[m]
        if T is None:
            res[m] = None
            continue
        if m == "max":
            v = min(d, T)
        elif m == "min":
            v = 0 if bal is None else min(T, max(0, d - max(0, bal - T)))
        elif m == "pro_rata":
            v = None if bal is None else (min(d, T) if bal <= 0 else min(T, round(d * T / bal)))
        else:  # fifo
            v = None if bal is None else _fifo_take(s.lots, d)
        res[m] = v
    if bal is not None:
        s.balance = bal - d
    for m in METHODS:
        if s.taint[m] is None:
            continue
        if res[m] is None:  # method not evaluable from here on (unknown balance)
            s.taint[m] = None
            continue
        nt = s.taint[m] - res[m]
        if s.balance is not None:
            nt = min(nt, max(0, s.balance))
        s.taint[m] = max(0, nt)
    return res


def _fifo_take(lots: deque, d: int) -> int:
    remaining, tainted = d, 0
    while remaining > 0 and lots:
        lot = lots[0]
        take = min(lot[0], remaining)
        part = round(take * lot[1] / lot[0]) if lot[0] else 0
        lot[0] -= take
        lot[1] -= part
        tainted += part
        remaining -= take
        if lot[0] <= 0:
            lots.popleft()
    return tainted


def _summary(v: dict[str, int | None], amount: int) -> dict:
    lo, hi = v["min"], v["max"]
    return {
        **v,
        "amount_minor": amount,
        "provenance": DERIVED if (lo or 0) > 0 else INFERRED,
        "all_methods_full": all(x == amount for x in v.values() if x is not None),
    }


def _holdable(out: dict) -> list[dict]:
    """Visible accounts still holding possibly-disputed funds at window end (hold candidates)."""
    rows = []
    for acct_id, info in out["per_account"].items():
        vals = [v for v in info["residual"].values() if v is not None]
        if not vals:
            continue
        lo, hi = min(vals), max(vals)
        bal = info["balance_at_window_end"]
        if bal is not None:
            lo, hi = min(lo, max(0, bal)), min(hi, max(0, bal))
        if hi > 0:
            rows.append({"account_id": acct_id, "label": info["label"], "max_minor": hi, "min_minor": lo, "balance_minor": bal,
                         "by_method": info["residual"]})
    return sorted(rows, key=lambda x: -x["max_minor"])


def annotate_graph(res: TraceResult, attribution: dict) -> None:
    """Add attribution to transaction nodes and inferred/derived onward-funding edges."""
    cur = attribution.get("currency", "INR")
    for tid, a in attribution.get("per_transaction", {}).items():
        node = res.nodes.get(tid)
        if node is None:
            continue
        node["attribution"] = a
        parent = res.parent_txn.get(res.txns[tid].debit_account_id) if tid in res.txns else None
        if not parent or parent == tid or (a.get("max") or 0) <= 0:
            continue
        lo, hi = a.get("min") or 0, a.get("max") or 0
        if lo > 0:
            label = f"at least {fmt_amount(lo, cur)} must be disputed funds (balance arithmetic)"
        else:
            label = f"up to {fmt_amount(hi, cur)} may be disputed funds — not established"
        res.add_edge(
            parent,
            tid,
            "possible_onward_funding",
            DERIVED if lo > 0 else INFERRED,
            [parent, tid],
            res.txns[tid].occurred_at,
            label,
            {k: a.get(k) for k in ("min", "fifo", "pro_rata", "max")},
        )
