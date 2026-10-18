"""Publish a ledger file to the FundTrace Pub/Sub topic (what a core-banking or switch connector would do).

    cd backend
    gcloud auth application-default login        # or run in Cloud Shell
    python -m scripts.publish_ledger --project MY_PROJECT --format iso20022.camt.053 ../docs/samples/statement-camt053.xml
    python -m scripts.publish_ledger --project MY_PROJECT --format fundtrace.v1 --source-system upi_switch records.json

The file is validated locally with the same parser the service uses before it is published, so a malformed file
is caught here rather than as a rejected delivery. Uses the Pub/Sub REST API (no extra client library).
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

from app.services.ledger_sources import FORMATS, FormatError, parse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--project", required=True)
    ap.add_argument("--topic", default="fundtrace-ledger")
    ap.add_argument("--format", required=True, choices=sorted(FORMATS))
    ap.add_argument("--source-system", default="core")
    a = ap.parse_args()
    data = Path(a.file).read_bytes()
    try:
        n = len(parse(a.format, data, a.source_system))
    except FormatError as exc:
        sys.exit(f"Not published: {exc}")
    if len(data) > 9 * 1024 * 1024:
        sys.exit("Not published: Pub/Sub messages are limited to 10 MB; split the file")

    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/pubsub"])
    body = {"messages": [{"data": base64.b64encode(data).decode(),
                          "attributes": {"format": a.format, "source_system": a.source_system, "filename": Path(a.file).name}}]}
    r = AuthorizedSession(creds).post(f"https://pubsub.googleapis.com/v1/projects/{a.project}/topics/{a.topic}:publish", json=body, timeout=30)
    if r.status_code != 200:
        sys.exit(f"Publish failed: HTTP {r.status_code} {r.text[:300]}")
    print(f"Published {n} record(s) as message {r.json()['messageIds'][0]} to {a.topic}. "
          "Check the AI Ops page (Ledger ingest) or GET /api/ingest/events.")


if __name__ == "__main__":
    main()
