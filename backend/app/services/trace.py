"""Time-ordered fund-trail reconstruction around a disputed transaction.

Key properties (all covered by tests):
- **Time-respecting**: a hop is followed only if it happens *after* the funds arrived at the
  account (forward) or *before* they left it (backward). Plain path-finding would wrongly chain
  "B→C at 09:00" after "A→B at 10:02".
- **Bounded**: depth, time window, per-account fan-out and total node caps. Hitting a cap is
  reported (`truncated`), never silent.
- **Honest endpoints**: external institutions end visibility; high-activity (hub) accounts pause
  expansion; failed/reversed transactions are shown but never propagated; cycles are detected.
- **Provenance**: every node/edge says whether it is confirmed by a record, derived, inferred,
  unknown or contradictory, and carries its source record ids.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from app.services.graph_store import AccountRec, GraphStore, TxnRec

CONFIRMED = "confirmed"
DERIVED = "derived"
INFERRED = "inferred"
UNKNOWN = "unknown"
CONTRADICTORY = "contradictory"

ENDPOINT_LABELS = {
    "visibility_ends": "Funds left this bank — visibility ends (request trail from the receiving institution)",
    "hub_paused": "High-activity account — expansion paused to avoid overload",
    "merchant": "Merchant/business account — payment reached a business; its settlements are not followed by default",
    "depth_limit": "Depth limit reached — expand to continue",
    "funds_remain": "No onward movement in the window — funds may remain here",
    "cycle": "Cycle — funds returned to an account already on this path",
    "truncated": "Result cap reached — not all activity shown",
    "origin_unknown": "No earlier inflow in the window — source of funds not visible",
}


@dataclass
class TraceParams:
    direction: str = "forward"  # forward | backward | both
    depth: int = 3
    window_hours: int = 72
    max_nodes: int = 150
    hub_threshold: int = 25
    per_account_cap: int = 40
    expand_accounts: tuple[str, ...] = ()  # accounts the investigator chose to expand past hub/depth limits

    def clamp(self, max_depth: int, max_window: int, max_nodes: int) -> "TraceParams":
        self.depth = max(1, min(int(self.depth), max_depth))
        self.window_hours = max(1, min(int(self.window_hours), max_window))
        self.max_nodes = max(10, min(int(self.max_nodes), max_nodes))
        if self.direction not in ("forward", "backward", "both"):
            raise ValueError("direction must be forward, backward or both")
        return self


@dataclass
class TraceResult:
    root_txn_id: str
    params: TraceParams
    nodes: dict[str, dict] = field(default_factory=dict)
    edges: dict[str, dict] = field(default_factory=dict)
    paths: list[dict] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None
    # internal bookkeeping
    txns: dict[str, TxnRec] = field(default_factory=dict)
    accounts: dict[str, AccountRec] = field(default_factory=dict)
    arrival: dict[str, datetime] = field(default_factory=dict)  # forward: earliest tainted arrival per account
    parent_txn: dict[str, str | None] = field(default_factory=dict)  # account -> txn that first reached it
    forward_txn_ids: list[str] = field(default_factory=list)
    backward_txn_ids: list[str] = field(default_factory=list)

    # ---- builders -------------------------------------------------------------------------
    def add_account(self, acct: AccountRec, role: str, depth: int) -> dict:
        node = self.nodes.get(acct.id)
        if node is None:
            node = {
                "id": acct.id,
                "type": "account",
                "label": acct.holder_label,
                "provenance": CONFIRMED,
                "source_ids": [acct.id],
                "depth": depth,
                "roles": [role],
                "endpoint": None,
                "endpoint_reason": None,
                "data": {
                    "masked_number": acct.masked_number,
                    "institution": acct.institution_name,
                    "external": acct.external,
                    "kind": acct.kind,
                    "opened_at": _iso(acct.opened_at),
                    "currency": acct.currency,
                },
            }
            self.nodes[acct.id] = node
            self.accounts[acct.id] = acct
        else:
            if role not in node["roles"]:
                node["roles"].append(role)
            node["depth"] = min(node["depth"], depth)
        return node

    def mark_endpoint(self, account_id: str, kind: str, extra: str | None = None) -> None:
        node = self.nodes[account_id]
        # Keep the most informative endpoint; visibility/hub outrank generic ones.
        order = ["visibility_ends", "hub_paused", "merchant", "cycle", "truncated", "depth_limit", "funds_remain", "origin_unknown"]
        current = node.get("endpoint")
        if current is None or order.index(kind) < order.index(current):
            node["endpoint"] = kind
            node["endpoint_reason"] = ENDPOINT_LABELS[kind] + (f" ({extra})" if extra else "")
            if kind in ("visibility_ends", "origin_unknown"):
                node["provenance_note"] = "Beyond this point the trail is unknown, not absent."

    def add_txn(self, t: TxnRec, depth: int, direction: str) -> bool:
        """Returns False when the node cap is reached."""
        if t.id in self.nodes:
            return True
        if len(self.nodes) >= self.params.max_nodes:
            self.truncated = True
            return False
        self.txns[t.id] = t
        self.nodes[t.id] = {
            "id": t.id,
            "type": "transaction",
            "label": f"{_fmt_amount(t.amount_minor, t.currency)} · {t.channel}",
            "provenance": CONFIRMED,
            "source_ids": [t.id, f"{t.source_system}:{t.source_record_id}"],
            "depth": depth,
            "direction": direction,
            "time": _iso(t.occurred_at),
            "data": {
                "amount_minor": t.amount_minor,
                "currency": t.currency,
                "status": t.status,
                "channel": t.channel,
                "reference": t.reference,
                "reference_missing": not t.reference,
                "occurred_at": _iso(t.occurred_at),
                "posted_at": _iso(t.posted_at),
                "debit_account_id": t.debit_account_id,
                "credit_account_id": t.credit_account_id,
                "reversal_of_id": t.reversal_of_id,
                "device_id": t.device_id,
                "source_system": t.source_system,
                "source_record_id": t.source_record_id,
                "narrative": t.narrative,
            },
        }
        if not t.reference:
            self.nodes[t.id]["flags"] = ["missing_reference"]
        self.add_edge(t.debit_account_id, t.id, "sent", CONFIRMED, [t.id], t.occurred_at)
        self.add_edge(t.id, t.credit_account_id, "received_by", CONFIRMED, [t.id], t.occurred_at)
        if direction == "forward":
            self.forward_txn_ids.append(t.id)
        elif direction == "backward":
            self.backward_txn_ids.append(t.id)
        return True

    def add_edge(
        self,
        source: str,
        target: str,
        etype: str,
        provenance: str,
        source_ids: list[str],
        time: datetime | None,
        label: str | None = None,
        data: dict | None = None,
    ) -> str:
        eid = f"{etype}:{source}->{target}"
        if eid not in self.edges:
            self.edges[eid] = {
                "id": eid,
                "source": source,
                "target": target,
                "type": etype,
                "provenance": provenance,
                "source_ids": source_ids,
                "time": _iso(time),
                "label": label,
                "data": data or {},
            }
        return eid

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_txn_id": self.root_txn_id,
            "params": {
                "direction": self.params.direction,
                "depth": self.params.depth,
                "window_hours": self.params.window_hours,
                "max_nodes": self.params.max_nodes,
                "hub_threshold": self.params.hub_threshold,
            },
            "window": {"start": _iso(self.window_start), "end": _iso(self.window_end)},
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges.values()),
            "paths": self.paths,
            "cycles": self.cycles,
            "truncated": self.truncated,
            "warnings": self.warnings,
            "stats": {
                "nodes": len(self.nodes),
                "edges": len(self.edges),
                "transactions": len(self.txns),
                "accounts": len(self.accounts),
                "endpoints": sum(1 for n in self.nodes.values() if n.get("endpoint")),
            },
        }


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() + "Z" if d else None


def _fmt_amount(minor: int, currency: str) -> str:
    symbol = {"INR": "₹", "USD": "$", "EUR": "€", "SGD": "S$"}.get(currency, currency + " ")
    major = minor / 100
    if currency == "INR":
        return f"{symbol}{_indian_grouping(major)}"
    return f"{symbol}{major:,.2f}".replace(".00", "")


def _indian_grouping(x: float) -> str:
    neg = x < 0
    x = abs(x)
    whole = int(x)
    frac = round(x - whole, 2)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    out = s + (f"{frac:.2f}"[1:] if frac else "")
    return ("-" if neg else "") + out


fmt_amount = _fmt_amount


# --------------------------------------------------------------------------------------------
# Trace
# --------------------------------------------------------------------------------------------


def trace(store: GraphStore, txn_id: str, params: TraceParams) -> TraceResult:
    root = store.get_transaction(txn_id)
    if root is None:
        raise KeyError(f"transaction {txn_id} not found")
    res = TraceResult(root_txn_id=root.id, params=params)
    window = timedelta(hours=params.window_hours)
    res.window_start = root.occurred_at - window if params.direction in ("backward", "both") else root.occurred_at
    res.window_end = root.occurred_at + window if params.direction in ("forward", "both") else root.occurred_at

    accts = store.get_accounts([root.debit_account_id, root.credit_account_id])
    payer, payee = accts.get(root.debit_account_id), accts.get(root.credit_account_id)
    if payer is None or payee is None:
        raise KeyError("disputed transaction references unknown accounts")
    res.add_account(payer, "payer", 0)
    res.add_account(payee, "beneficiary", 1)
    res.add_txn(root, 0, "root")
    res.nodes[root.id]["roles"] = ["disputed"]
    res.parent_txn[payee.id] = root.id
    res.arrival[payee.id] = root.occurred_at

    if root.status == "failed":
        res.warnings.append("The disputed transaction failed; no money moved, so there is no onward trail.")
    else:
        if params.direction in ("forward", "both"):
            _trace_forward(store, res, root, payer, payee)
        if params.direction in ("backward", "both"):
            _trace_backward(store, res, root, payer)

    _attach_reversals(store, res)
    _build_paths(res)
    return res


def _trace_forward(store: GraphStore, res: TraceResult, root: TxnRec, payer: AccountRec, payee: AccountRec) -> None:
    p = res.params
    end = res.window_end
    if root.status == "reversed":
        res.warnings.append("The disputed transaction was reversed; funds were returned and are not followed onward.")
        res.mark_endpoint(payee.id, "funds_remain", "transaction reversed")
        return
    # heap of (arrival_time, depth, account_id, path_accounts)
    heap: list[tuple[datetime, int, str, frozenset[str]]] = [(root.occurred_at, 1, payee.id, frozenset({payer.id, payee.id}))]
    expanded: set[str] = set()
    while heap:
        arrival, depth, acct_id, path = heapq.heappop(heap)
        if acct_id in expanded:
            continue
        expanded.add(acct_id)
        acct = res.accounts[acct_id]
        if acct.external:
            res.mark_endpoint(acct_id, "visibility_ends", acct.institution_name)
            continue
        total = store.count_outgoing(acct_id, arrival, end)
        forced = acct_id in p.expand_accounts
        if acct.kind == "merchant" and not forced:
            res.mark_endpoint(acct_id, "merchant")
            res.nodes[acct_id]["data"]["outgoing_in_window"] = total
            res.nodes[acct_id]["expandable"] = total > 0
            continue
        if total > p.hub_threshold and not forced:
            res.mark_endpoint(acct_id, "hub_paused", f"{total} outgoing transfers in window")
            res.nodes[acct_id]["data"]["outgoing_in_window"] = total
            res.nodes[acct_id]["expandable"] = True
            continue
        cap = p.per_account_cap * (3 if forced else 1)
        outs = store.outgoing(acct_id, arrival, end, cap)
        if total > len(outs):
            res.nodes[acct_id]["data"]["outgoing_shown"] = f"{len(outs)} of {total}"
            res.mark_endpoint(acct_id, "truncated", f"showing {len(outs)} of {total} outgoing")
            res.nodes[acct_id]["expandable"] = True
            res.truncated = True
        if not outs:
            res.mark_endpoint(acct_id, "funds_remain")
            continue
        moved_on = False
        for t in outs:
            new_accts = store.get_accounts([t.credit_account_id])
            dest = new_accts.get(t.credit_account_id)
            if dest is None:
                res.warnings.append(f"{t.id} credits an unknown account {t.credit_account_id}")
                continue
            if t.credit_account_id not in res.nodes and len(res.nodes) + 2 > p.max_nodes:
                res.truncated = True
                res.mark_endpoint(acct_id, "truncated")
                res.nodes[acct_id]["expandable"] = True
                break
            res.add_account(dest, "downstream", depth + 1)
            if not res.add_txn(t, depth, "forward"):
                res.mark_endpoint(acct_id, "truncated")
                break
            if not t.moved_money:
                res.nodes[t.id]["note"] = "Failed — no money moved; not followed."
                continue
            if t.status == "reversed":
                res.nodes[t.id]["note"] = "Reversed — funds returned; not followed onward."
                continue
            moved_on = True
            if dest.id in path:
                res.cycles.append([*sorted(path), dest.id])
                res.mark_endpoint(dest.id, "cycle")
                continue
            res.parent_txn.setdefault(dest.id, t.id)
            if dest.id not in res.arrival or t.occurred_at < res.arrival[dest.id]:
                res.arrival[dest.id] = t.occurred_at
            if depth + 1 > p.depth and dest.id not in p.expand_accounts:
                if not dest.external:
                    res.mark_endpoint(dest.id, "depth_limit")
                    res.nodes[dest.id]["expandable"] = True
                else:
                    res.mark_endpoint(dest.id, "visibility_ends", dest.institution_name)
                continue
            heapq.heappush(heap, (t.occurred_at, depth + 1, dest.id, path | {dest.id}))
        if not moved_on and res.nodes[acct_id].get("endpoint") is None:
            res.mark_endpoint(acct_id, "funds_remain")


def _trace_backward(store: GraphStore, res: TraceResult, root: TxnRec, payer: AccountRec) -> None:
    """Where did the payer's funds come from before the disputed transaction?"""
    p = res.params
    start = res.window_start
    # heap ordered by latest departure first (negated timestamp)
    heap: list[tuple[float, int, str, frozenset[str]]] = [(-_secs(root.occurred_at), 1, payer.id, frozenset({payer.id}))]
    expanded: set[str] = set()
    while heap:
        neg_ts, depth, acct_id, path = heapq.heappop(heap)
        before = _EPOCH + timedelta(seconds=-neg_ts)
        if acct_id in expanded:
            continue
        expanded.add(acct_id)
        acct = res.accounts[acct_id]
        if acct.external:
            res.mark_endpoint(acct_id, "visibility_ends", acct.institution_name)
            continue
        total = store.count_incoming(acct_id, before, start)
        if total > p.hub_threshold and acct_id not in p.expand_accounts:
            res.mark_endpoint(acct_id, "hub_paused", f"{total} incoming transfers in window")
            res.nodes[acct_id]["expandable"] = True
            continue
        ins = store.incoming(acct_id, before, start, p.per_account_cap)
        if not ins:
            if acct_id != payer.id or not res.forward_txn_ids:
                res.mark_endpoint(acct_id, "origin_unknown")
            continue
        for t in ins:
            src = store.get_accounts([t.debit_account_id]).get(t.debit_account_id)
            if src is None:
                continue
            if t.debit_account_id not in res.nodes and len(res.nodes) + 2 > p.max_nodes:
                res.truncated = True
                break
            res.add_account(src, "upstream", -(depth))
            if not res.add_txn(t, -depth, "backward"):
                break
            if not t.moved_money or t.status == "reversed":
                continue
            if src.id in path:
                res.cycles.append([*sorted(path), src.id])
                res.mark_endpoint(src.id, "cycle")
                continue
            if depth + 1 > p.depth:
                if not src.external:
                    res.mark_endpoint(src.id, "depth_limit")
                    res.nodes[src.id]["expandable"] = True
                else:
                    res.mark_endpoint(src.id, "visibility_ends", src.institution_name)
                continue
            heapq.heappush(heap, (-_secs(t.occurred_at), depth + 1, src.id, path | {src.id}))


_EPOCH = datetime(1970, 1, 1)


def _secs(d: datetime) -> float:
    """Seconds since epoch for a naive-UTC datetime (avoids local-timezone conversion)."""
    return (d - _EPOCH).total_seconds()


def _attach_reversals(store: GraphStore, res: TraceResult) -> None:
    reversed_ids = [t.id for t in res.txns.values() if t.status == "reversed"]
    for rev in store.reversals_of(reversed_ids):
        accts = store.get_accounts([rev.debit_account_id, rev.credit_account_id])
        for a in accts.values():
            res.add_account(a, "reversal", res.nodes.get(a.id, {}).get("depth", 1))
        if res.add_txn(rev, res.nodes.get(rev.reversal_of_id or "", {}).get("depth", 1), "reversal"):
            res.nodes[rev.id]["roles"] = ["reversal"]
            res.add_edge(rev.reversal_of_id, rev.id, "reversal_of", CONFIRMED, [rev.id], rev.occurred_at, "reversed by")


def _build_paths(res: TraceResult) -> None:
    """Trail paths from the disputed transaction to each forward endpoint, as txn id chains."""
    for acct_id, node in res.nodes.items():
        if node["type"] != "account" or not node.get("endpoint") or "upstream" in node["roles"]:
            continue
        if acct_id not in res.parent_txn and node["endpoint"] != "cycle":
            continue
        chain: list[str] = []
        cur = acct_id
        guard = 0
        while cur in res.parent_txn and guard < 50:
            tid = res.parent_txn[cur]
            if tid is None or tid in chain:
                break
            chain.insert(0, tid)
            cur = res.txns[tid].debit_account_id
            guard += 1
        if chain:
            res.paths.append(
                {
                    "endpoint_account_id": acct_id,
                    "endpoint": node["endpoint"],
                    "txn_ids": chain,
                    "provenance": CONFIRMED,
                    "note": "Each hop is a recorded transfer. Whether these hops carried the disputed funds is shown by attribution, not by the path itself.",
                }
            )


def account_ids_in(res: TraceResult, roles: Iterable[str] | None = None) -> list[str]:
    roles = set(roles or [])
    return [n["id"] for n in res.nodes.values() if n["type"] == "account" and (not roles or roles & set(n["roles"]))]
