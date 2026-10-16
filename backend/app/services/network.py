"""Global mule-ring signals across all dispute trails (NetworkX).

Builds one graph from every case's forward trail plus shared-device links, then reports connected
groups that touch several disputes. These are *signals for review*, not findings.
"""
from __future__ import annotations

from collections import defaultdict

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.services.graph_store import SqlGraphStore
from app.services.investigation import default_params
from app.services.trace import trace


def mule_rings(db: Session, min_cases: int = 2) -> dict:
    store = SqlGraphStore(db)
    g = nx.Graph()
    case_accounts: dict[str, set[str]] = defaultdict(set)
    cases = db.scalars(select(m.DisputeCase)).unique().all()
    amounts: dict[str, int] = {}
    for c in cases:
        res = trace(store, c.disputed_txn_id, default_params(depth=3))
        payer = res.txns[c.disputed_txn_id].debit_account_id
        amounts[c.id] = res.txns[c.disputed_txn_id].amount_minor
        for t in res.txns.values():
            for a in (t.debit_account_id, t.credit_account_id):
                if a == payer:
                    continue
                acct = res.accounts.get(a)
                if acct and (acct.external or acct.kind == "merchant"):
                    continue
                case_accounts[c.id].add(a)
            if t.debit_account_id != payer and t.credit_account_id != payer:
                g.add_edge(t.debit_account_id, t.credit_account_id, kind="transfer", txn=t.id)
            elif t.debit_account_id == payer:
                g.add_node(t.credit_account_id)
    # shared devices among in-trail accounts
    acct_set = set().union(*case_accounts.values()) if case_accounts else set()
    dev_rows = db.execute(select(m.Transaction.device_id, m.Transaction.debit_account_id)
                          .where(m.Transaction.debit_account_id.in_(acct_set), m.Transaction.device_id.is_not(None))).all() if acct_set else []
    by_dev: dict[str, set[str]] = defaultdict(set)
    for d, a in dev_rows:
        by_dev[d].add(a)
    for d, accts in by_dev.items():
        accts = sorted(accts)
        for i in range(len(accts) - 1):
            g.add_edge(accts[i], accts[i + 1], kind="shared_device", device=d)
    rings = []
    sub = g.subgraph([n for n in g.nodes if n in acct_set])
    for comp in nx.connected_components(sub):
        linked = sorted(cid for cid, accts in case_accounts.items() if accts & comp)
        if len(linked) < min_cases:
            continue
        h = sub.subgraph(comp)
        centrality = nx.degree_centrality(h) if len(h) > 1 else {n: 0 for n in h}
        hub = max(centrality, key=centrality.get) if centrality else None
        devices = sorted({d["device"] for _, _, d in h.edges(data=True) if d.get("kind") == "shared_device"})
        rings.append({
            "accounts": sorted(comp), "cases": linked, "hub_account": hub, "shared_devices": devices,
            "transfers": sorted({d["txn"] for _, _, d in h.edges(data=True) if d.get("kind") == "transfer"}),
            "disputed_amount_minor": sum(amounts[c] for c in linked), "currency": "INR",
            "edges": [{"source": u, "target": v, "kind": d.get("kind"), "ref": d.get("txn") or d.get("device")} for u, v, d in h.edges(data=True)],
            "signal": f"{len(comp)} accounts connected across {len(linked)} disputes",
        })
    rings.sort(key=lambda r: (-len(r["cases"]), -r["disputed_amount_minor"]))
    return {"rings": rings, "cases_scanned": len(cases), "accounts_in_trails": len(acct_set),
            "note": "Connected accounts across disputes are a signal for coordinated review, not proof of a mule network."}
