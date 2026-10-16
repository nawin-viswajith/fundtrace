"""Production-path adapter: the same `GraphStore` protocol served from Spanner Graph.

Not used by the hackathon deployment (Cloud SQL is the source of truth there). In production, a
Datastream/Dataflow pipeline keeps a Spanner copy of recent transfers; this adapter answers the
trace engine's bounded neighbour queries from it, so the trace/attribution/rules code is unchanged.

Property graph (GQL DDL, run once in Spanner):

    CREATE PROPERTY GRAPH FundGraph
      NODE TABLES (Accounts KEY (account_id), Transactions KEY (txn_id))
      EDGE TABLES (
        Transactions AS Sent     SOURCE KEY (debit_account_id)  REFERENCES Accounts (account_id)
                                 DESTINATION KEY (txn_id) REFERENCES Transactions (txn_id),
        Transactions AS Received SOURCE KEY (txn_id) REFERENCES Transactions (txn_id)
                                 DESTINATION KEY (credit_account_id) REFERENCES Accounts (account_id));

Bounded multi-hop example (what the trace engine expands one hop at a time):

    GRAPH FundGraph
    MATCH (a:Accounts {account_id: @acct})-[:Sent]->(t:Transactions)-[:Received]->(b:Accounts)
    WHERE t.occurred_at > @after AND t.occurred_at <= @until
    RETURN t.txn_id, b.account_id ORDER BY t.occurred_at LIMIT @limit
"""
from __future__ import annotations

from datetime import datetime

from app.services.graph_store import TxnRec

OUTGOING_GQL = """
GRAPH FundGraph
MATCH (a:Accounts {account_id: @acct})-[:Sent]->(t:Transactions)-[:Received]->(b:Accounts)
WHERE t.occurred_at > @after AND t.occurred_at <= @until
RETURN t.txn_id, t.debit_account_id, t.credit_account_id, t.amount_minor, t.currency, t.status, t.channel, t.reference,
       t.occurred_at, t.posted_at, t.reversal_of_id, t.device_id, t.source_system, t.source_record_id
ORDER BY t.occurred_at LIMIT @limit
"""


class SpannerGraphStore:  # pragma: no cover - requires a Spanner instance
    def __init__(self, instance_id: str, database_id: str, fallback):
        from google.cloud import spanner  # optional dependency

        self.db = spanner.Client().instance(instance_id).database(database_id)
        self.fallback = fallback  # SqlGraphStore for case/auth/device lookups that stay relational

    def outgoing(self, account_id: str, after: datetime, until: datetime, limit: int) -> list[TxnRec]:
        with self.db.snapshot() as snap:
            rows = snap.execute_sql(OUTGOING_GQL, params={"acct": account_id, "after": after, "until": until, "limit": limit})
            return [TxnRec(*r[:14]) for r in rows]

    def __getattr__(self, name):
        # Everything not yet served from Spanner falls back to the relational store.
        return getattr(self.fallback, name)
