"""Normalisation of raw transaction records from one or more source systems.

`LedgerSource` is the adapter boundary for future, authorised bank integrations (core banking,
UPI/IMPS switch, card switch). The demo uses `SyntheticLedgerSource` only.

Normalisation rules:
- amounts are parsed with Decimal into integer minor units — never floats
- timestamps become naive UTC
- the same payment reported by several systems (same reference, parties, close in time) becomes
  ONE transaction that keeps every source record and any disagreement between them
- exact duplicate source records (same system + record id) are dropped and reported
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable, Protocol

MINOR_UNITS = {"INR": 2, "USD": 2, "EUR": 2, "SGD": 2, "JPY": 0}
SOURCE_PRIORITY = ("core", "upi_switch", "imps_switch", "card_switch")  # first wins on disagreement
MERGE_WINDOW = timedelta(minutes=5)
VALID_STATUSES = {"posted", "pending", "failed", "reversed"}


class LedgerSource(Protocol):
    """Adapter for an authorised source of transaction records."""

    name: str

    def fetch(self, since: datetime, until: datetime) -> Iterable[dict]: ...


class NormalisationError(ValueError):
    pass


def to_minor(amount: str | int | float | Decimal, currency: str) -> int:
    if currency not in MINOR_UNITS:
        raise NormalisationError(f"unsupported currency {currency!r}")
    try:
        d = Decimal(str(amount))
    except InvalidOperation as exc:
        raise NormalisationError(f"invalid amount {amount!r}") from exc
    if d < 0:
        raise NormalisationError("amount must be non-negative; direction comes from debit/credit accounts")
    q = Decimal(1).scaleb(-MINOR_UNITS[currency])
    return int((d.quantize(q, rounding=ROUND_HALF_UP) * (10 ** MINOR_UNITS[currency])).to_integral_value())


def to_utc_naive(ts: str | datetime) -> datetime:
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if ts.tzinfo is not None:
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    return ts


@dataclass
class NormalisationReport:
    input_records: int = 0
    transactions: int = 0
    merged: list[dict] = field(default_factory=list)
    dropped_duplicates: list[str] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)


def normalise(records: Iterable[dict]) -> tuple[list[dict], NormalisationReport]:
    """Raw records -> normalised transaction dicts (ready for the `transactions` table)."""
    rep = NormalisationReport()
    seen_source: set[tuple[str, str]] = set()
    clean: list[dict] = []
    for r in records:
        rep.input_records += 1
        key = (r.get("source_system", ""), str(r.get("source_record_id", "")))
        if key in seen_source:
            rep.dropped_duplicates.append(f"{key[0]}:{key[1]}")
            continue
        seen_source.add(key)
        try:
            cur = (r.get("currency") or "").upper()
            status = (r.get("status") or "posted").lower()
            if status not in VALID_STATUSES:
                raise NormalisationError(f"invalid status {status!r}")
            if not r.get("debit_account_id") or not r.get("credit_account_id"):
                raise NormalisationError("missing debit or credit account")
            if r["debit_account_id"] == r["credit_account_id"]:
                raise NormalisationError("debit and credit account are the same")
            clean.append({
                **r,
                "currency": cur,
                "status": status,
                "amount_minor": to_minor(r["amount"], cur),
                "occurred_at": to_utc_naive(r["occurred_at"]),
                "posted_at": to_utc_naive(r["posted_at"]) if r.get("posted_at") else None,
                "reference": (r.get("reference") or None),
            })
        except (NormalisationError, KeyError, ValueError) as exc:
            rep.rejected.append({"source": f"{key[0]}:{key[1]}", "reason": str(exc)})

    # Merge the same payment reported by several systems.
    clean.sort(key=lambda x: (x["occurred_at"], _prio(x["source_system"])))
    out: list[dict] = []
    by_ref: dict[tuple, dict] = {}
    for r in clean:
        mk = (r["reference"], r["debit_account_id"], r["credit_account_id"]) if r["reference"] else None
        prior = by_ref.get(mk) if mk else None
        if prior and abs(r["occurred_at"] - prior["occurred_at"]) <= MERGE_WINDOW and r["source_system"] != prior["source_system"]:
            prior["sources"].append(_source_entry(r))
            diffs = [f for f in ("amount_minor", "currency", "status") if r[f] != prior[f]]
            if diffs:
                prior.setdefault("discrepancies", []).append(
                    {"source": r["source_system"], "fields": {f: {"primary": prior[f], "other": r[f]} for f in diffs}})
            rep.merged.append({"txn_id": prior["id"], "merged": f"{r['source_system']}:{r['source_record_id']}", "discrepancies": diffs})
            continue
        txn = {k: r[k] for k in ("id", "source_system", "source_record_id", "debit_account_id", "credit_account_id",
                                 "amount_minor", "currency", "status", "channel", "reference", "occurred_at", "posted_at")}
        txn.update({"reversal_of_id": r.get("reversal_of_id"), "device_id": r.get("device_id"),
                    "narrative": r.get("narrative", ""), "sources": [_source_entry(r)]})
        out.append(txn)
        if mk:
            by_ref[mk] = txn
    for t in out:
        if t.get("discrepancies"):
            t["sources"][0]["discrepancies"] = t.pop("discrepancies")
    rep.transactions = len(out)
    return out, rep


def _prio(system: str) -> int:
    return SOURCE_PRIORITY.index(system) if system in SOURCE_PRIORITY else len(SOURCE_PRIORITY)


def _source_entry(r: dict) -> dict:
    return {"system": r["source_system"], "record_id": str(r["source_record_id"]), "amount_minor": r["amount_minor"],
            "currency": r["currency"], "status": r["status"], "occurred_at": r["occurred_at"].isoformat() + "Z"}
