"""Bank-format adapters: turn delivered ledger data into raw records for `ledger.normalise`.

Formats:
- ``fundtrace.v1``        JSON: one raw record, a list of records, or {"records": [...]}
- ``csv``                 CSV whose header uses the raw-record field names (see `CSV_FIELDS`)
- ``iso20022.camt.053``   ISO 20022 bank-to-customer statement (camt.053, versions .001.02 to .001.08)

Every adapter produces the same raw-record shape, so normalisation, merging and provenance are identical
whatever the source. Account identifiers are passed through as given; `ingest` resolves them to accounts.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from typing import Iterable
from xml.etree import ElementTree as ET

from app.services.ledger import LedgerSource, to_utc_naive

FORMATS = {
    "fundtrace.v1": "FundTrace JSON records",
    "csv": "CSV with FundTrace column names",
    "iso20022.camt.053": "ISO 20022 camt.053 bank statement (XML)",
}
CSV_FIELDS = ("source_record_id", "debit_account_id", "credit_account_id", "amount", "currency", "status", "channel", "reference",
              "occurred_at", "posted_at", "narrative", "reversal_of_id", "device_id")
REQUIRED = ("source_record_id", "debit_account_id", "credit_account_id", "amount", "currency", "occurred_at")
CHANNELS = {"UPI", "IMPS", "NEFT", "RTGS", "CARD", "INTERNAL"}
MAX_BYTES = 10 * 1024 * 1024


class FormatError(ValueError):
    pass


def parse(fmt: str, data: bytes, source_system: str) -> list[dict]:
    if fmt not in FORMATS:
        raise FormatError(f"unsupported format {fmt!r}; use one of {', '.join(FORMATS)}")
    if len(data) > MAX_BYTES:
        raise FormatError("payload too large")
    if fmt == "fundtrace.v1":
        records = _json_records(data)
    elif fmt == "csv":
        records = _csv_records(data)
    else:
        records = camt053_records(data)
    for r in records:
        r.setdefault("source_system", source_system)
        r["channel"] = (str(r.get("channel") or "OTHER")).upper()[:16]
    return records


# ---------------------------------------------------------------------------- JSON / CSV

def _json_records(data: bytes) -> list[dict]:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormatError(f"invalid JSON: {exc}") from exc
    records = doc.get("records") if isinstance(doc, dict) and "records" in doc else doc
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        raise FormatError("expected a record, a list of records or {\"records\": [...]}")
    return [{k: v for k, v in r.items() if k in CSV_FIELDS + ("source_system", "debit_account_name", "credit_account_name")}
            for r in records]


def _csv_records(data: bytes) -> list[dict]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FormatError("CSV must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    missing = [f for f in REQUIRED if f not in (reader.fieldnames or [])]
    if missing:
        raise FormatError(f"CSV header is missing: {', '.join(missing)}")
    return [{k: (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k in CSV_FIELDS and v not in (None, "")}
            for row in reader]


# ---------------------------------------------------------------------------- ISO 20022 camt.053

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: ET.Element | None, path: str) -> ET.Element | None:
    """Namespace-agnostic path lookup ('A/B/C' by local names)."""
    for part in path.split("/"):
        if el is None:
            return None
        el = next((c for c in el if _local(c.tag) == part), None)
    return el


def _text(el: ET.Element | None, path: str) -> str | None:
    found = _child(el, path)
    return found.text.strip() if found is not None and found.text and found.text.strip() else None


def _children(el: ET.Element | None, name: str) -> list[ET.Element]:
    return [c for c in el if _local(c.tag) == name] if el is not None else []


def _account_id(acct: ET.Element | None) -> str | None:
    return _text(acct, "Id/IBAN") or _text(acct, "Id/Othr/Id") or _text(acct, "Id/Prxy/Id")


def _when(entry: ET.Element) -> str | None:
    for path in ("BookgDt/DtTm", "ValDt/DtTm", "BookgDt/Dt", "ValDt/Dt"):
        v = _text(entry, path)
        if v:
            return v if "T" in v else v + "T00:00:00"
    return None


def camt053_records(data: bytes) -> list[dict]:
    head = data[:2048].decode("utf-8", "ignore").upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in head:  # no DTDs or entities: blocks entity-expansion attacks
        raise FormatError("XML with DOCTYPE or ENTITY declarations is not accepted")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise FormatError(f"invalid XML: {exc}") from exc
    stmt_root = _child(root, "BkToCstmrStmt")
    if stmt_root is None:
        raise FormatError("not a camt.053 document (BkToCstmrStmt missing)")
    out: list[dict] = []
    for stmt in _children(stmt_root, "Stmt"):
        own = _account_id(_child(stmt, "Acct"))
        stmt_id = _text(stmt, "Id") or "STMT"
        if not own:
            raise FormatError(f"statement {stmt_id} has no account identifier")
        for n, entry in enumerate(_children(stmt, "Ntry"), 1):
            amt_el = _child(entry, "Amt")
            direction = _text(entry, "CdtDbtInd")
            tx = _child(entry, "NtryDtls/TxDtls")
            parties = _child(tx, "RltdPties")
            if direction == "DBIT":
                debit, credit = own, _account_id(_child(parties, "CdtrAcct"))
                credit_name = _text(parties, "Cdtr/Nm") or _text(parties, "Cdtr/Pty/Nm")
                debit_name = None
            else:
                debit, credit = _account_id(_child(parties, "DbtrAcct")), own
                debit_name = _text(parties, "Dbtr/Nm") or _text(parties, "Dbtr/Pty/Nm")
                credit_name = None
            status_code = (_text(entry, "Sts/Cd") or _text(entry, "Sts") or "BOOK").upper()
            status = "pending" if status_code in ("PDNG", "INFO") else "posted"
            if (_text(entry, "RvslInd") or "").lower() == "true":
                status = "reversed"
            channel = (_text(entry, "BkTxCd/Prtry/Cd") or "").upper()
            out.append({
                "source_record_id": _text(entry, "AcctSvcrRef") or _text(entry, "NtryRef") or f"{stmt_id}:{n}",
                "debit_account_id": debit,
                "credit_account_id": credit,
                "debit_account_name": debit_name,
                "credit_account_name": credit_name,
                "amount": amt_el.text.strip() if amt_el is not None and amt_el.text else None,
                "currency": (amt_el.get("Ccy") if amt_el is not None else None) or _text(stmt, "Acct/Ccy"),
                "status": status,
                "channel": channel if channel in CHANNELS else "OTHER",
                "reference": _text(tx, "Refs/ClrSysRef") or _text(tx, "Refs/EndToEndId") or _text(tx, "Refs/TxId") or _text(tx, "Refs/UETR"),
                "occurred_at": _when(entry),
                "posted_at": _text(entry, "BookgDt/DtTm") if status == "posted" else None,
                "narrative": (_text(tx, "RmtInf/Ustrd") or _text(entry, "AddtlNtryInf") or "")[:255],
            })
    return out


class StatementFileSource(LedgerSource):
    """`LedgerSource` over a delivered statement file (e.g. an SFTP drop or a Pub/Sub payload)."""

    def __init__(self, name: str, fmt: str, data: bytes):
        self.name, self.fmt, self.data = name, fmt, data

    def fetch(self, since: datetime, until: datetime) -> Iterable[dict]:
        for r in parse(self.fmt, self.data, self.name):
            try:
                at = to_utc_naive(r["occurred_at"])
            except (KeyError, TypeError, ValueError):
                yield r  # let normalisation reject and report it
                continue
            if since <= at < until:
                yield r


_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def safe_identifier(v: object) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s if _SAFE_ID.match(s) else None
