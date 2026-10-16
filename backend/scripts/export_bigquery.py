"""Production-path job: export transactions and AI telemetry to BigQuery for baselines, rule
back-testing and cost/quality analytics.

    python -m scripts.export_bigquery --project P --dataset fundtrace
"""
from __future__ import annotations

import argparse


def main() -> None:  # pragma: no cover - requires BigQuery
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dataset", default="fundtrace")
    a = ap.parse_args()
    from google.cloud import bigquery
    from sqlalchemy import select

    from app import models as m
    from app.db import init_engine, session_scope

    init_engine()
    bq = bigquery.Client(project=a.project)
    bq.create_dataset(a.dataset, exists_ok=True)
    with session_scope() as db:
        txns = [{"id": t.id, "debit": t.debit_account_id, "credit": t.credit_account_id, "amount_minor": t.amount_minor,
                 "currency": t.currency, "status": t.status, "channel": t.channel, "occurred_at": t.occurred_at.isoformat(),
                 "is_synthetic": t.is_synthetic} for t in db.scalars(select(m.Transaction)).all()]
        calls = [{"id": c.id, "node": c.node, "model": c.model, "status": c.status, "input_tokens": c.input_tokens,
                  "output_tokens": c.output_tokens, "cost_usd": c.cost_usd, "latency_ms": c.latency_ms, "case_id": c.case_id,
                  "created_at": c.created_at.isoformat()} for c in db.scalars(select(m.AICall)).all()]
    for table, rows in (("transactions", txns), ("ai_calls", calls)):
        job = bq.load_table_from_json(rows, f"{a.project}.{a.dataset}.{table}",
                                      job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", autodetect=True))
        job.result()
        print(f"loaded {len(rows)} rows into {a.dataset}.{table}")


if __name__ == "__main__":
    main()
