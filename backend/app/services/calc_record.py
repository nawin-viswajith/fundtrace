"""Forensic calculation record: everything needed to recreate the attribution figures of a case.

Why this exists: "the system says ₹28,800" is not reproducible. Another investigator (or a court,
or an auditor a year later) must be able to take the same source records, apply the same named
and versioned method, and get the same amount. So the record keeps three things apart:

- **inputs**   observed facts copied from the bank's records: the trace limits used, every
               transaction the calculation read (in the order it was applied), and the opening
               balance used for each account. A SHA-256 fingerprint of their canonical JSON
               identifies exactly this set of facts plus the method versions.
- **outputs**  calculated estimates: the attribution figures, unchanged from `attribution.attribute`.
- **checks**   tests of the arithmetic itself: money conserved, no impossible balance, nothing
               counted twice, bounds in order, inputs complete, and a recompute from the record alone.

It contains no investigator conclusions. Whether the money was the customer's, or who controlled
it, is decided by people, not by this record.

The inputs are captured by passing a recording wrapper to `attribute` (so the record lists what
attribution actually read, not a re-derivation that could drift from it), and `replay` recomputes
the figures from the record's JSON alone, with no database.

Amounts are integer minor units (paise). Where the bank's own systems disagree on a payment's
amount, the record shows the range `min ≤ amount ≤ max` and which system reported which (§7.6);
the figures use the amount of the record the ledger keeps as the main one.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from app.services.attribution import (
    ACTIVITY_LIMIT,
    ATTRIBUTION_ASSUMPTIONS,
    ATTRIBUTION_VERSION,
    METHOD_DEFINITIONS,
    METHOD_LABELS,
    METHOD_SYMBOLS,
    METHOD_VERSIONS,
    METHODS,
    attribute,
)
from app.services.graph_store import AccountRec, GraphStore, TxnRec
from app.services.trace import TraceParams, TraceResult, fmt_amount, trace

CALC_VERSION = "1.0"
RECORD_TYPE = "fundtrace.calculation_record"

PASS, WARN, FAIL, NA = "pass", "warn", "fail", "not_applicable"
_SEVERITY = {FAIL: 3, WARN: 2, PASS: 1, NA: 0}

# Plain names shown to bank staff (same words as the UI's method labels).
PLAIN_METHOD_NAMES = {
    "min": "Clean money spent first",
    "fifo": "First in, first out",
    "pro_rata": "Proportional mix",
    "max": "Disputed money spent first",
}
SOURCE_LABELS = {"core": "core banking", "upi_switch": "UPI switch", "imps_switch": "IMPS switch", "card_switch": "card switch"}
PRIMARY_RULE = ("When several systems report the same payment, the ledger keeps one record as the main one (the earliest; "
                "core banking first when the times are equal) and stores the others alongside it. All figures use the main "
                "record's amount.")

# Transaction fields that are facts from the source records (and so part of the fingerprint).
_TXN_FIELDS = ("id", "occurred_at", "debit_account_id", "credit_account_id", "amount_minor", "currency", "status",
               "reversal_of_id", "reference", "source_system", "source_record_id", "sources")
_OVERDRAFT_RE = re.compile(r"^(\S+): debit exceeds computed balance")


class ReplayError(ValueError):
    """The record does not contain an input the calculation needs."""


# ---------------------------------------------------------------------------------------------- stores

class _RecordingStore:
    """Passes every call to the real store and keeps what attribution actually read."""

    def __init__(self, inner: GraphStore):
        self._inner = inner
        self.rows: dict[str, TxnRec] = {}
        self.balances: dict[str, tuple[datetime, int | None]] = {}

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def activity(self, account_id, start, end, limit):
        rows = self._inner.activity(account_id, start, end, limit)
        for t in rows:
            self.rows[t.id] = t
        return rows

    def balance_before(self, account_id, at):
        v = self._inner.balance_before(account_id, at)
        self.balances.setdefault(account_id, (at, v))
        return v


class _ReplayStore:
    """Answers attribution's two questions (activity, opening balance) from a record alone.

    Activity is the record's transactions filtered and ordered exactly as the database query does;
    because the record holds every row attribution read for each account, this returns the same rows.
    """

    def __init__(self, txns: list[TxnRec], balances: dict[tuple[str, str], int | None]):
        self.txns = txns
        self.balances = balances

    def activity(self, account_id, start, end, limit):
        rows = [t for t in self.txns
                if (t.debit_account_id == account_id or t.credit_account_id == account_id) and start <= t.occurred_at <= end]
        return sorted(rows, key=lambda t: (t.occurred_at, t.id))[:limit]

    def balance_before(self, account_id, at):
        key = (account_id, _iso(at))
        if key not in self.balances:
            raise ReplayError(f"the record has no opening balance for {account_id} at {_iso(at)}")
        return self.balances[key]


# ---------------------------------------------------------------------------------------------- build

def build_record(store: GraphStore, txn_id: str, params: TraceParams, case_id: str | None = None,
                 now: datetime | None = None, verify: bool = True) -> dict:
    """Trace, attribute and record. Mirrors `investigation.build_trace`, so the figures are the
    same ones the trail view shows for the same parameters."""
    res = trace(store, txn_id, params)
    fwd = res if params.direction in ("forward", "both") else trace(store, txn_id, TraceParams(**{**params.__dict__, "direction": "forward"}))
    rec_store = _RecordingStore(store)
    att = attribute(rec_store, fwd)
    record = _assemble(fwd, att, rec_store, params, case_id, now)
    if verify:
        record["checks"].append(_check_recompute(record))
    record["checks_summary"] = _summary(record["checks"])
    return record


def build_case_record(db, case, params: TraceParams, now: datetime | None = None) -> dict:
    from app.services.graph_store import SqlGraphStore

    return build_record(SqlGraphStore(db), case.disputed_txn_id, params, case_id=case.id, now=now)


def _assemble(res: TraceResult, att: dict, rs: _RecordingStore, params: TraceParams, case_id: str | None,
              now: datetime | None) -> dict:
    root = res.txns[res.root_txn_id]
    cur = root.currency
    rows = dict(rs.rows)
    rows[root.id] = root
    ordered = sorted(rows.values(), key=lambda t: (t.occurred_at, t.id))
    reversed_ids = {t.id for t in ordered if t.status == "reversed"}

    def treatment(t: TxnRec) -> str:
        if not t.moved_money:
            return "excluded_failed"
        if t.id in reversed_ids:
            return "excluded_reversed"
        if t.reversal_of_id in reversed_ids:
            return "excluded_reverses_reversed"
        return "used"

    txns = []
    for i, t in enumerate(ordered):
        role = "disputed" if t.id == root.id else "trail" if t.id in res.txns else "other_activity"
        txns.append({**_txn_dict(t), "order": i + 1, "role": role, "treatment": treatment(t)})

    traced, sinks = _classify(res)
    accounts = []
    for acct_id in sorted(res.accounts):
        a = res.accounts[acct_id]
        node = res.nodes.get(acct_id) or {}
        accounts.append({"id": acct_id, "label": a.holder_label, "external": a.external, "kind": a.kind,
                         "endpoint": node.get("endpoint"), "arrival": _iso(res.arrival.get(acct_id)),
                         "treatment": "followed" if acct_id in traced else sinks.get(acct_id, "not_followed")})

    balances = sorted(({"account_id": acct_id, "as_of": _iso(at), "balance_minor": v,
                        "label": res.accounts[acct_id].holder_label if acct_id in res.accounts else acct_id}
                       for acct_id, (at, v) in rs.balances.items()), key=lambda b: (b["as_of"], b["account_id"]))

    p = res.params
    inputs = {
        "trace_parameters": {
            "direction": params.direction, "attribution_direction": p.direction, "depth": p.depth,
            "window_hours": p.window_hours, "max_nodes": p.max_nodes, "hub_threshold": p.hub_threshold,
            "per_account_cap": p.per_account_cap, "expand_accounts": sorted(p.expand_accounts),
            "window_start": _iso(res.window_start), "window_end": _iso(res.window_end), "activity_limit": ACTIVITY_LIMIT,
        },
        "accounts": accounts,
        "trail_txn_ids": sorted(t for t in res.txns if t in rows),
        "transactions": txns,
        "opening_balances": balances,
    }
    versions = _versions()
    inputs["fingerprint"] = {
        "algorithm": "SHA-256",
        "value": fingerprint_inputs(root.id, inputs, versions),
        "covers": "The disputed transaction id, calculation and method versions, trace parameters, account treatment, "
                  "every transaction read (facts only) and every opening balance used.",
        "canonical_form": "JSON with keys sorted, no spaces, UTF-8; amounts in minor units; times in UTC ISO-8601.",
    }
    outputs = _outputs(att)
    outputs["fingerprint"] = {"algorithm": "SHA-256", "value": fingerprint_outputs(outputs)}
    ranges = amount_ranges(txns, cur)

    record = {
        "record_type": RECORD_TYPE,
        "calc_version": CALC_VERSION,
        "case_id": case_id,
        "disputed_txn_id": root.id,
        "currency": cur,
        "amount_unit": "minor units (1/100 of the currency unit; paise for INR)",
        "generated_at": _iso((now or datetime.now(timezone.utc)).replace(tzinfo=None)),
        "versions": versions,
        "methods": [{"id": m, "name": PLAIN_METHOD_NAMES[m], "label": METHOD_LABELS[m], "version": METHOD_VERSIONS[m],
                     **METHOD_DEFINITIONS[m]} for m in METHODS],
        "method_symbols": METHOD_SYMBOLS,
        "assumptions": [{"id": k, "text": v} for k, v in ATTRIBUTION_ASSUMPTIONS],
        "kinds": {
            "inputs": "Observed: copied from the bank's records.",
            "outputs": "Calculated: worked out by the named methods above. Estimates, not observations.",
            "conclusions": "None. Whether the money was the customer's, and who controlled it, is for the investigator to decide.",
        },
        "inputs": inputs,
        "outputs": outputs,
        "amount_ranges": ranges,
        "primary_record_rule": PRIMARY_RULE,
        "checks": [],
    }
    record["checks"] = [
        _check_conservation(att),
        _check_balances(att, balances, cur),
        _check_duplicates(txns),
        _check_source_agreement(ranges, txns, cur),
        _check_double_counting(att),
        _check_bounds_order(att, txns, root.id),
        _check_completeness(res, att),
    ]
    return record


def _classify(res: TraceResult) -> tuple[set[str], dict[str, str]]:
    """Which accounts attribution follows and which end the trail (same rules as `attribute`)."""
    traced, sinks = set(), {}
    for acct_id in res.arrival:
        node, acct = res.nodes.get(acct_id), res.accounts.get(acct_id)
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
    return traced, sinks


def _outputs(att: dict) -> dict:
    keys = ("disputed_amount_minor", "evaluable", "per_transaction", "per_account", "buckets", "coverage", "exits",
            "holdable", "warnings", "caveat")
    return json.loads(json.dumps({k: att.get(k) for k in keys}))


def _versions() -> dict:
    return {"calc_version": CALC_VERSION, "attribution_version": ATTRIBUTION_VERSION, "method_versions": dict(METHOD_VERSIONS)}


# ---------------------------------------------------------------------------------------------- fingerprints

def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint_inputs(disputed_txn_id: str, inputs: dict, versions: dict) -> str:
    payload = {
        "disputed_txn_id": disputed_txn_id,
        "versions": versions,
        "trace_parameters": inputs["trace_parameters"],
        "accounts": [{k: a[k] for k in ("id", "external", "endpoint", "arrival", "treatment")} for a in inputs["accounts"]],
        "trail_txn_ids": inputs["trail_txn_ids"],
        "transactions": [{k: t.get(k) for k in _TXN_FIELDS} for t in inputs["transactions"]],
        "opening_balances": [{k: b[k] for k in ("account_id", "as_of", "balance_minor")} for b in inputs["opening_balances"]],
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def fingerprint_outputs(outputs: dict) -> str:
    # Warnings are compared as a set: their order can follow set iteration, which is not a figure.
    payload = {k: v for k, v in outputs.items() if k not in ("fingerprint", "caveat")}
    payload["warnings"] = sorted(payload.get("warnings") or [])
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------------------------- replay

def replay(record: dict) -> dict:
    """Recompute the attribution figures from the record's inputs alone (no database)."""
    inp = record["inputs"]
    tp = inp["trace_parameters"]
    txns = [_txn_rec(t) for t in inp["transactions"]]
    by_id = {t.id: t for t in txns}
    params = TraceParams(direction=tp["attribution_direction"], depth=tp["depth"], window_hours=tp["window_hours"],
                         max_nodes=tp["max_nodes"], hub_threshold=tp["hub_threshold"], per_account_cap=tp["per_account_cap"],
                         expand_accounts=tuple(tp["expand_accounts"]))
    res = TraceResult(root_txn_id=record["disputed_txn_id"], params=params)
    res.window_start, res.window_end = _parse(tp["window_start"]), _parse(tp["window_end"])
    if res.root_txn_id not in by_id:
        raise ReplayError("the record does not contain the disputed transaction")
    for a in inp["accounts"]:
        res.accounts[a["id"]] = AccountRec(id=a["id"], customer_id=None, institution_id="", institution_name="",
                                           external=a["external"], kind=a.get("kind") or "", holder_label=a["label"],
                                           masked_number="", opened_at=None, opening_balance_minor=None,
                                           currency=record["currency"])
        res.nodes[a["id"]] = {"id": a["id"], "type": "account", "endpoint": a["endpoint"]}
        if a.get("arrival"):
            res.arrival[a["id"]] = _parse(a["arrival"])
    res.txns = {i: by_id[i] for i in inp["trail_txn_ids"] if i in by_id}
    res.txns[res.root_txn_id] = by_id[res.root_txn_id]
    balances = {(b["account_id"], b["as_of"]): b["balance_minor"] for b in inp["opening_balances"]}
    out = _outputs(attribute(_ReplayStore(txns, balances), res))
    out["fingerprint"] = {"algorithm": "SHA-256", "value": fingerprint_outputs(out)}
    return out


def _check_recompute(record: dict) -> dict:
    name = "Recalculating gives the same result"
    what = "The figures are worked out again from this record alone (no database) and must come out identical."
    copy = json.loads(json.dumps(record))  # exactly what a downloaded file would contain
    try:
        again = replay(copy)
    except (ReplayError, KeyError, TypeError, ValueError) as exc:
        return _check("recompute", name, what, FAIL, f"Could not recalculate from the record: {exc}.", [])
    fp_in = fingerprint_inputs(copy["disputed_txn_id"], copy["inputs"], copy["versions"])
    items = []
    if fp_in != record["inputs"]["fingerprint"]["value"]:
        items.append(_item(FAIL, "The fingerprint of the inputs does not match when worked out again."))
    if again["fingerprint"]["value"] != record["outputs"]["fingerprint"]["value"]:
        diffs = diff(record["outputs"], again, "outputs")
        items.append(_item(FAIL, "Recalculated figures differ: " + "; ".join(diffs[:5]) + "."))
    if items:
        return _check("recompute", name, what, FAIL, "Recalculating from the same inputs did not give the same result.", items)
    return _check("recompute", name, what, PASS,
                  f"Recalculated from the {len(copy['inputs']['transactions'])} recorded transactions: same input fingerprint "
                  f"and identical figures (output fingerprint {record['outputs']['fingerprint']['value'][:12]}…).", [])


def verify(store: GraphStore, txn_id: str, params: TraceParams, case_id: str | None = None,
           expected_fingerprint: str | None = None) -> dict:
    """Rebuild the record from the source records twice and replay it; report any difference."""
    a = build_record(store, txn_id, params, case_id=case_id, verify=False)
    b = build_record(store, txn_id, params, case_id=case_id, verify=False)
    differences: list[str] = []
    fa, fb = a["inputs"]["fingerprint"]["value"], b["inputs"]["fingerprint"]["value"]
    if fa != fb:
        differences += diff(_strip_fp(a["inputs"]), _strip_fp(b["inputs"]), "inputs")[:10] or ["Input fingerprints differ."]
    if a["outputs"]["fingerprint"]["value"] != b["outputs"]["fingerprint"]["value"]:
        differences += diff(a["outputs"], b["outputs"], "outputs")[:10]
    try:
        again = replay(json.loads(json.dumps(a)))
        if again["fingerprint"]["value"] != a["outputs"]["fingerprint"]["value"]:
            differences += ["Recalculated from the record alone: " + d for d in diff(a["outputs"], again, "outputs")[:10]]
    except (ReplayError, KeyError, TypeError, ValueError) as exc:
        differences.append(f"Could not recalculate from the record alone: {exc}.")
    if expected_fingerprint and expected_fingerprint != fa:
        differences.append("The bank's records (or the calculation version) have changed since your copy was made: "
                           f"your fingerprint {expected_fingerprint[:12]}…, now {fa[:12]}….")
    return {"matches": not differences, "fingerprint": fa, "output_fingerprint": a["outputs"]["fingerprint"]["value"],
            "expected_fingerprint": expected_fingerprint, "calc_version": CALC_VERSION, "differences": differences,
            "checked_at": _iso(datetime.now(timezone.utc).replace(tzinfo=None))}


def verify_case(db, case, params: TraceParams, expected_fingerprint: str | None = None) -> dict:
    from app.services.graph_store import SqlGraphStore

    return verify(SqlGraphStore(db), case.disputed_txn_id, params, case_id=case.id, expected_fingerprint=expected_fingerprint)


def _strip_fp(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "fingerprint"}


def diff(a, b, path: str = "") -> list[str]:
    """Paths where two JSON values differ, e.g. 'outputs.buckets.fifo.unaccounted: 0 → 12'."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b), key=str):
            if k == "fingerprint":
                continue
            out += diff(a.get(k), b.get(k), f"{path}.{k}" if path else str(k))
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [f"{path}: {_short(a)} → {_short(b)}"]


def _short(v) -> str:
    s = json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= 60 else s[:57] + "…"


# ---------------------------------------------------------------------------------------------- §7.6 ranges

def amount_ranges(txns: list[dict], currency: str) -> list[dict]:
    """Payments whose source systems report different amounts: `min ≤ amount ≤ max`, with who said what."""
    out = []
    for t in txns:
        srcs = [s for s in t.get("sources") or [] if s.get("amount_minor") is not None and (s.get("currency") or t["currency"]) == t["currency"]]
        amounts = {s["amount_minor"] for s in srcs}
        if len(amounts) < 2:
            continue
        lo, hi = min(amounts), max(amounts)
        cur = t["currency"] or currency
        used_label = SOURCE_LABELS.get(t["source_system"], t["source_system"])
        out.append({
            "txn_id": t["id"], "role": t["role"], "currency": cur,
            "min_minor": lo, "max_minor": hi, "used_minor": t["amount_minor"],
            "used_system": t["source_system"], "used_system_label": used_label,
            "reported": [{"system": s["system"], "system_label": SOURCE_LABELS.get(s["system"], s["system"]),
                          "record_id": s["record_id"], "amount_minor": s["amount_minor"]} for s in srcs],
            "statement": f"{fmt_amount(lo, cur)} ≤ amount ≤ {fmt_amount(hi, cur)}",
            "explanation": (f"The bank's systems disagree on this payment: {fmt_amount(lo, cur)}–{fmt_amount(hi, cur)}. "
                            f"Figures use the {used_label} amount {fmt_amount(t['amount_minor'], cur)}, the record the ledger "
                            "keeps as the main one."),
        })
    order = {"disputed": 0, "trail": 1, "other_activity": 2}
    return sorted(out, key=lambda r: (order.get(r["role"], 3), r["txn_id"]))


# ---------------------------------------------------------------------------------------------- checks

def _item(status: str, text: str) -> dict:
    return {"status": status, "text": text}


def _check(cid: str, name: str, what: str, status: str, detail: str, items: list[dict]) -> dict:
    return {"id": cid, "name": name, "what_it_checks": what, "status": status, "detail": detail, "items": items}


def _worst(items: list[dict], default: str = PASS) -> str:
    return max((i["status"] for i in items), key=lambda s: _SEVERITY[s], default=default)


def _summary(checks: list[dict]) -> dict:
    out = {s: sum(1 for c in checks if c["status"] == s) for s in (PASS, WARN, FAIL, NA)}
    out["overall"] = _worst(checks, PASS)
    return out


def _check_conservation(att: dict) -> dict:
    name = "Every rupee of the disputed payment is accounted for"
    what = "For each method, the places the money went must add up exactly to the disputed amount."
    if not att.get("evaluable"):
        return _check("conservation", name, what, NA, "The disputed payment moved no money (failed or reversed), so there is nothing to account for.", [])
    amount, cur = att["disputed_amount_minor"], att["currency"]
    items = []
    for m in METHODS:
        b, label = att["buckets"][m], PLAIN_METHOD_NAMES[m]
        if any(v is None for v in b.values()):
            items.append(_item(NA, f"{label}: not worked out, because an opening balance is unknown."))
            continue
        placed = {k: v for k, v in b.items() if k != "unaccounted"}
        total = sum(placed.values())
        if any(v < 0 for v in placed.values()):
            items.append(_item(FAIL, f"{label}: a destination has a negative amount."))
        elif total == amount:
            items.append(_item(PASS, f"{label}: {fmt_amount(total, cur)} placed of {fmt_amount(amount, cur)}. Adds up exactly."))
        elif total < amount:
            items.append(_item(WARN, f"{label}: {fmt_amount(amount - total, cur)} of {fmt_amount(amount, cur)} could not be placed "
                                     "(a balance went below zero or records are missing)."))
        else:
            items.append(_item(FAIL, f"{label}: places {fmt_amount(total, cur)}, more than the {fmt_amount(amount, cur)} disputed."))
    status = _worst(items, NA)
    detail = {PASS: "Under every method that could be worked out, the money adds up exactly to the disputed amount.",
              WARN: "Some of the disputed money could not be placed under at least one method.",
              FAIL: "Under at least one method the figures do not add up. Do not rely on them.",
              NA: "No method could be worked out."}[status]
    return _check("conservation", name, what, status, detail, items)


def _check_balances(att: dict, balances: list[dict], cur: str) -> dict:
    name = "No account goes below zero"
    what = "Balances worked out from the records should never be negative, and no account can hold more disputed money than its balance."
    items = []
    for b in balances:
        if b["balance_minor"] is None:
            items.append(_item(NA, f"{b['label']} ({b['account_id']}): opening balance not known, so its balance could not be checked."))
        elif b["balance_minor"] < 0:
            items.append(_item(WARN, f"{b['label']} ({b['account_id']}) was already below zero ({fmt_amount(b['balance_minor'], cur)}) "
                                     "before the disputed money arrived."))
    for w in att.get("warnings") or []:
        mt = _OVERDRAFT_RE.match(w)
        if mt:
            items.append(_item(WARN, f"Payment {mt.group(1)} is larger than the balance worked out for the account at that moment: "
                                     "an overdraft facility or missing records. Figures were capped at the balance."))
    for acct_id, info in (att.get("per_account") or {}).items():
        bal = info.get("balance_at_window_end")
        if bal is None:
            continue
        if bal < 0:
            items.append(_item(WARN, f"{info.get('label') or acct_id} ({acct_id}) ends the period below zero ({fmt_amount(bal, cur)})."))
            continue
        for m in METHODS:
            r = (info.get("residual") or {}).get(m)
            if r is not None and r > bal:
                items.append(_item(FAIL, f"{info.get('label') or acct_id} ({acct_id}) would hold {fmt_amount(r, cur)} of disputed money "
                                         f"({PLAIN_METHOD_NAMES[m]}), more than its whole balance of {fmt_amount(bal, cur)}."))
    status = _worst([i for i in items if i["status"] != NA], PASS)
    detail = {PASS: "No balance worked out from the records goes below zero.",
              WARN: "At least one balance goes below zero. That is either an overdraft facility or records missing from the ledger; "
                    "figures for that account are capped at its balance.",
              FAIL: "An account would hold more disputed money than its balance. Do not rely on these figures."}[status]
    return _check("impossible_balances", name, what, status, detail, items)


def _check_duplicates(txns: list[dict]) -> dict:
    name = "No payment is counted twice"
    what = ("Each source record may appear only once. The same payment reported by several systems must be merged into one "
            "transaction, not added twice.")
    items = []
    seen: dict[tuple[str, str], str] = {}
    merged = []
    for t in txns:
        entries = t.get("sources") or [{"system": t["source_system"], "record_id": t["source_record_id"]}]
        own: set[tuple[str, str]] = set()
        for s in entries:
            key = (s["system"], str(s["record_id"]))
            if key in own:
                items.append(_item(FAIL, f"{t['id']}: source record {key[0]}:{key[1]} is listed twice."))
            elif key in seen and seen[key] != t["id"]:
                items.append(_item(FAIL, f"Source record {key[0]}:{key[1]} appears in both {seen[key]} and {t['id']}: one payment counted twice."))
            own.add(key)
            seen.setdefault(key, t["id"])
        if len(entries) > 1:
            systems = ", ".join(SOURCE_LABELS.get(s["system"], s["system"]) for s in entries)
            merged.append(t["id"])
            items.append(_item(PASS, f"{t['id']} was reported by {len(entries)} systems ({systems}) and merged into one payment, counted once."))
    by_ref: dict[tuple, list[str]] = {}
    for t in txns:
        if t.get("reference"):
            by_ref.setdefault((t["reference"], t["debit_account_id"], t["credit_account_id"]), []).append(t["id"])
    for (ref, _, _), ids in sorted(by_ref.items()):
        if len(ids) > 1:
            items.append(_item(WARN, f"{', '.join(ids)} share reference {ref} and the same accounts but were kept separate. "
                                     "Check whether this is one payment recorded twice."))
    status = _worst(items, PASS)
    n_src = len(seen)
    detail = {PASS: f"{len(txns)} transactions from {n_src} source records; no record is used twice. "
                    + (f"{len(merged)} payment(s) reported by more than one system were merged and counted once. " if merged else "")
                    + "Exact duplicate source records (same system and record id) are dropped when records are loaded.",
              WARN: "Some payments look alike and may be the same payment recorded twice. The figures count them separately.",
              FAIL: "A source record is used more than once. Do not rely on these figures."}[status]
    return _check("duplicates", name, what, status, detail, items)


def _check_source_agreement(ranges: list[dict], txns: list[dict], cur: str) -> dict:
    name = "The bank's systems agree on each payment"
    what = "Where more than one system reported a payment, their amount, currency and status should match."
    multi = [t for t in txns if len(t.get("sources") or []) > 1]
    if not multi:
        return _check("source_agreement", name, what, NA, "Each payment was reported by a single system, so there is nothing to compare.", [])
    items = []
    for r in ranges:
        who = "; ".join(f"{s['system_label']} {fmt_amount(s['amount_minor'], r['currency'])}" for s in r["reported"])
        role = " (the disputed payment)" if r["role"] == "disputed" else ""
        items.append(_item(WARN, f"{r['txn_id']}{role}: {who}. Range {r['statement']}; figures use {fmt_amount(r['used_minor'], r['currency'])} "
                                 f"from {r['used_system_label']}."))
    for t in multi:
        for d in (t["sources"][0].get("discrepancies") or []):
            for f, v in (d.get("fields") or {}).items():
                if f == "amount_minor":
                    continue  # shown as a range above
                items.append(_item(WARN, f"{t['id']}: {SOURCE_LABELS.get(t['sources'][0]['system'], t['sources'][0]['system'])} reports "
                                         f"{f} {v.get('primary')!r}; {SOURCE_LABELS.get(d['source'], d['source'])} reports {v.get('other')!r}."))
    if not items:
        return _check("source_agreement", name, what, PASS,
                      f"{len(multi)} payment(s) were reported by more than one system and the systems agree.", [])
    return _check("source_agreement", name, what, WARN,
                  "The bank's systems disagree on at least one payment. The amount is shown as a range; the figures use the main record.",
                  items)


def _check_double_counting(att: dict) -> dict:
    name = "Figures never add up to more than the disputed payment"
    what = ("Under each method, money still in accounts plus money that left must not exceed the disputed amount, and no "
            "payment can carry more disputed money than its own amount.")
    if not att.get("evaluable"):
        return _check("double_counting", name, what, NA, "The disputed payment moved no money.", [])
    amount, cur = att["disputed_amount_minor"], att["currency"]
    items = []
    for m in METHODS:
        b, label = att["buckets"][m], PLAIN_METHOD_NAMES[m]
        res = [a["residual"].get(m) for a in (att.get("per_account") or {}).values()]
        ex = [e.get(m) for e in (att.get("exits") or {}).values()]
        if any(v is None for v in res + ex) or any(v is None for v in b.values()):
            items.append(_item(NA, f"{label}: not worked out for every account."))
            continue
        rs, es = sum(res), sum(ex)
        if rs != b["residual_in_visible_accounts"] or es != b["left_visibility"]:
            items.append(_item(FAIL, f"{label}: per-account figures ({fmt_amount(rs, cur)} held, {fmt_amount(es, cur)} left) do not match the totals."))
            continue
        other = b["reached_merchant_or_hub"] + b["returned_to_payer"] + b["beyond_trace_limits"]
        if rs + es + other > amount:
            items.append(_item(FAIL, f"{label}: {fmt_amount(rs + es + other, cur)} in total, more than the {fmt_amount(amount, cur)} disputed."))
        else:
            items.append(_item(PASS, f"{label}: {fmt_amount(rs, cur)} still held + {fmt_amount(es, cur)} left this bank + "
                                     f"{fmt_amount(other, cur)} elsewhere = {fmt_amount(rs + es + other, cur)}, not more than {fmt_amount(amount, cur)}."))
    for tid, a in (att.get("per_transaction") or {}).items():
        bad = [m for m in METHODS if a.get(m) is not None and not (0 <= a[m] <= a["amount_minor"])]
        if bad:
            items.append(_item(FAIL, f"{tid}: carries more disputed money than its own amount ({', '.join(PLAIN_METHOD_NAMES[m] for m in bad)})."))
    # Each account's largest figure is a maximum for that account alone; they cannot all be true together.
    tops = [max(v for v in a["residual"].values() if v is not None) for a in (att.get("per_account") or {}).values()
            if any(v is not None for v in a["residual"].values())]
    tops += [max(v for v in e.values() if v is not None) for e in (att.get("exits") or {}).values() if any(v is not None for v in e.values())]
    hold_total = sum(h["max_minor"] for h in att.get("holdable") or [])
    if hold_total > amount:
        items.append(_item(WARN, f"Holding the largest figure in every account would hold {fmt_amount(hold_total, cur)}, more than the "
                                 f"{fmt_amount(amount, cur)} disputed. Each largest figure is a maximum for that account on its own."))
    status = _worst([i for i in items if i["status"] != NA], PASS)
    note = ("The largest figure shown for each account is the most that account could hold on its own. "
            "Those largest figures must not be added together")
    if sum(tops) > amount:
        note += f": added up they come to {fmt_amount(sum(tops), cur)}, more than the {fmt_amount(amount, cur)} disputed."
    else:
        note += "."
    detail = {PASS: "Nothing is counted twice under any method. " + note,
              WARN: "Nothing is counted twice under any method, but see the note on holds. " + note,
              FAIL: "Some figures add up to more than the disputed payment. Do not rely on them."}[status]
    return _check("double_counting", name, what, status, detail, items)


def _same(vals: dict) -> bool:
    vs = [vals.get(m) for m in METHODS]
    return all(v is not None for v in vs) and len(set(vs)) == 1


def _check_bounds_order(att: dict, txns: list[dict], root_id: str) -> dict:
    """Lower ≤ FIFO, pro-rata ≤ upper, checked where that comparison is meaningful.

    Each method follows its own history: after an account's first payment out, the methods leave
    different amounts of disputed money behind, so a later payment's figures can legitimately cross
    (the lower-bound method kept more disputed money back, so it may later send more). The order is
    therefore enforced only for payments where every method starts from the same position: every
    earlier movement into and out of that account carried the same amount under all four methods.
    """
    name = "Lowest and highest figures are in the right order"
    what = ("Where every method starts from the same position, 'clean money spent first' must give the least disputed money, "
            "'disputed money spent first' the most, and the other two something in between.")
    rows = att.get("per_transaction") or {}
    if not rows:
        return _check("bounds_order", name, what, NA, "No onward payments carried disputed money.", [])
    aligned: dict[str, bool] = {}
    items, compared = [], 0
    for t in txns:
        if t["treatment"] != "used":
            continue
        tid, a = t["id"], rows.get(t["id"])
        if tid in rows:
            same_start = aligned.get(t["debit_account_id"], True)
            lo, hi = a.get("min"), a.get("max")
            out = [m for m in ("fifo", "pro_rata") if a.get(m) is not None and lo is not None and hi is not None and not (lo <= a[m] <= hi)]
            crossed = lo is not None and hi is not None and (lo > hi or bool(out))
            which = f" ({', '.join(PLAIN_METHOD_NAMES[m] for m in out)} outside the lowest-highest pair)" if out else ""
            if same_start:
                compared += 1
                if crossed:
                    items.append(_item(FAIL, f"{tid}: every method started from the same position, yet the figures are out of order{which}."))
            elif crossed:
                items.append(_item(NA, f"{tid}: the methods cross over{which}. Expected here: earlier payments left a different amount "
                                       "of disputed money in the account under each method. The ranges shown use the smallest and largest of the four."))
            if not _same(a):
                aligned[t["debit_account_id"]] = False
        incoming = {m: 0 for m in METHODS} if tid != root_id else {m: t["amount_minor"] for m in METHODS}
        if tid in rows:
            incoming = {m: a.get(m) for m in METHODS}
        if not _same(incoming) and any(incoming.get(m) for m in METHODS):
            aligned[t["credit_account_id"]] = False
    status = _worst([i for i in items if i["status"] != NA], PASS if compared else NA)
    crossed_n = sum(1 for i in items if i["status"] == NA)
    detail = {PASS: f"In order for all {compared} payment(s) where every method starts from the same position."
                    + (f" {crossed_n} later payment(s) cross over, which is expected; see below." if crossed_n else ""),
              FAIL: "Figures are out of order where they must not be. Do not rely on them.",
              NA: "Every onward payment follows an earlier one that the methods treated differently, so their order is not fixed."
                  + (f" {crossed_n} payment(s) cross over; the ranges shown use the smallest and largest of the four." if crossed_n else "")}[status]
    return _check("bounds_order", name, what, status, detail, items)


def _check_completeness(res: TraceResult, att: dict) -> dict:
    name = "All the records needed were available"
    what = "The search must not have hit a size limit, and every account followed must have a known opening balance."
    items = []
    if res.truncated:
        items.append(_item(WARN, "The search reached its size limit, so not every payment on the trail was read."))
    for w in att.get("warnings") or []:
        if "exceeds" in w and "rows" in w:
            items.append(_item(WARN, w))
        elif w.startswith("Opening balance of"):
            items.append(_item(WARN, w))
    for w in res.warnings:
        if "unknown account" in w:
            items.append(_item(WARN, w))
    status = _worst(items, PASS)
    detail = {PASS: "No limit was reached and every opening balance needed was known.",
              WARN: "Some records or balances were not available; the affected figures may be incomplete."}[status]
    return _check("completeness", name, what, status, detail, items)


# ---------------------------------------------------------------------------------------------- helpers

def _iso(d: datetime | None) -> str | None:
    return d.isoformat() + "Z" if d else None


def _parse(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s[:-1] if s.endswith("Z") else s) if s else None


def _txn_dict(t: TxnRec) -> dict:
    sources = [{"system": s.get("system"), "record_id": str(s.get("record_id")), "amount_minor": s.get("amount_minor"),
                "currency": s.get("currency"), "status": s.get("status"),
                **({"discrepancies": s["discrepancies"]} if s.get("discrepancies") else {})} for s in (t.sources or ())]
    return {"id": t.id, "occurred_at": _iso(t.occurred_at), "debit_account_id": t.debit_account_id,
            "credit_account_id": t.credit_account_id, "amount_minor": t.amount_minor, "currency": t.currency, "status": t.status,
            "reversal_of_id": t.reversal_of_id, "reference": t.reference, "source_system": t.source_system,
            "source_record_id": t.source_record_id, "sources": sources}


def _txn_rec(d: dict) -> TxnRec:
    return TxnRec(id=d["id"], debit_account_id=d["debit_account_id"], credit_account_id=d["credit_account_id"],
                  amount_minor=int(d["amount_minor"]), currency=d["currency"], status=d["status"], channel="",
                  reference=d.get("reference"), occurred_at=_parse(d["occurred_at"]), posted_at=None,
                  reversal_of_id=d.get("reversal_of_id"), device_id=None, source_system=d["source_system"],
                  source_record_id=d["source_record_id"], sources=tuple(d.get("sources") or ()))
