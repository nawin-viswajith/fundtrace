"""Read-only access to ledger data for tracing.

The trace engine, attribution and rules only talk to a `GraphStore`, never to the ORM directly.
`SqlGraphStore` reads Cloud SQL/SQLite; `InMemoryGraphStore` backs unit tests. A Spanner Graph
adapter can implement the same protocol later without touching callers.

Every query is bounded (time window + row limit), so no caller can trigger an unbounded scan.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Protocol

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app import models as m

# Statuses whose money actually moved (a reversed transaction moved money, and its reversal is a
# separate record that moved it back). Failed transactions never moved money.
EFFECTIVE_STATUSES = ("posted", "pending", "reversed")


@dataclass(frozen=True)
class TxnRec:
    id: str
    debit_account_id: str
    credit_account_id: str
    amount_minor: int
    currency: str
    status: str
    channel: str
    reference: str | None
    occurred_at: datetime
    posted_at: datetime | None
    reversal_of_id: str | None
    device_id: str | None
    source_system: str
    source_record_id: str
    narrative: str = ""
    sources: tuple = ()

    @property
    def moved_money(self) -> bool:
        return self.status in EFFECTIVE_STATUSES


@dataclass(frozen=True)
class AccountRec:
    id: str
    customer_id: str | None
    institution_id: str
    institution_name: str
    external: bool
    kind: str
    holder_label: str
    masked_number: str
    opened_at: datetime | None
    opening_balance_minor: int | None
    currency: str


@dataclass(frozen=True)
class AuthRec:
    id: str
    account_id: str
    device_id: str | None
    event_type: str
    outcome: str
    occurred_at: datetime
    source_system: str
    source_record_id: str


@dataclass(frozen=True)
class DeviceRec:
    id: str
    label: str
    first_seen_at: datetime


@dataclass(frozen=True)
class CaseLink:
    case_id: str
    disputed_txn_id: str
    beneficiary_account_id: str
    status: str


class GraphStore(Protocol):
    def get_transaction(self, txn_id: str) -> TxnRec | None: ...
    def get_transactions(self, txn_ids: Iterable[str]) -> list[TxnRec]: ...
    def get_account(self, account_id: str) -> AccountRec | None: ...
    def get_accounts(self, account_ids: Iterable[str]) -> dict[str, AccountRec]: ...
    def outgoing(self, account_id: str, after: datetime, until: datetime, limit: int) -> list[TxnRec]: ...
    def incoming(self, account_id: str, before: datetime, since: datetime, limit: int) -> list[TxnRec]: ...
    def count_outgoing(self, account_id: str, after: datetime, until: datetime) -> int: ...
    def count_incoming(self, account_id: str, before: datetime, since: datetime) -> int: ...
    def activity(self, account_id: str, start: datetime, end: datetime, limit: int) -> list[TxnRec]: ...
    def balance_before(self, account_id: str, at: datetime) -> int | None: ...
    def reversals_of(self, txn_ids: Iterable[str]) -> list[TxnRec]: ...
    def debits_between(self, account_id: str, start: datetime, end: datetime, limit: int) -> list[TxnRec]: ...
    def auth_events(self, account_id: str, start: datetime, end: datetime, limit: int) -> list[AuthRec] | None: ...
    def get_device(self, device_id: str) -> DeviceRec | None: ...
    def accounts_using_device(self, device_id: str, limit: int) -> list[str]: ...
    def cases_with_beneficiaries(self, account_ids: Iterable[str]) -> list[CaseLink]: ...


# --------------------------------------------------------------------------------------------
# SQL implementation
# --------------------------------------------------------------------------------------------


def _txn(r: m.Transaction) -> TxnRec:
    return TxnRec(
        id=r.id,
        debit_account_id=r.debit_account_id,
        credit_account_id=r.credit_account_id,
        amount_minor=int(r.amount_minor),
        currency=r.currency,
        status=r.status,
        channel=r.channel,
        reference=r.reference,
        occurred_at=r.occurred_at,
        posted_at=r.posted_at,
        reversal_of_id=r.reversal_of_id,
        device_id=r.device_id,
        source_system=r.source_system,
        source_record_id=r.source_record_id,
        narrative=r.narrative or "",
        sources=tuple(r.sources or ()),
    )


def _acct(r: m.Account) -> AccountRec:
    return AccountRec(
        id=r.id,
        customer_id=r.customer_id,
        institution_id=r.institution_id,
        institution_name=r.institution.name if r.institution else r.institution_id,
        external=(r.institution.kind == "external") if r.institution else False,
        kind=r.kind,
        holder_label=r.holder_label,
        masked_number=r.masked_number,
        opened_at=r.opened_at,
        opening_balance_minor=None if r.opening_balance_minor is None else int(r.opening_balance_minor),
        currency=r.currency,
    )


class SqlGraphStore:
    def __init__(self, db: Session):
        self.db = db
        self._acct_cache: dict[str, AccountRec] = {}

    def get_transaction(self, txn_id: str) -> TxnRec | None:
        r = self.db.get(m.Transaction, txn_id)
        return _txn(r) if r else None

    def get_transactions(self, txn_ids: Iterable[str]) -> list[TxnRec]:
        ids = list(set(txn_ids))
        if not ids:
            return []
        rows = self.db.scalars(select(m.Transaction).where(m.Transaction.id.in_(ids))).all()
        return [_txn(r) for r in rows]

    def get_account(self, account_id: str) -> AccountRec | None:
        if account_id in self._acct_cache:
            return self._acct_cache[account_id]
        r = self.db.get(m.Account, account_id)
        if not r:
            return None
        rec = _acct(r)
        self._acct_cache[account_id] = rec
        return rec

    def get_accounts(self, account_ids: Iterable[str]) -> dict[str, AccountRec]:
        missing = [a for a in set(account_ids) if a not in self._acct_cache]
        if missing:
            for r in self.db.scalars(select(m.Account).where(m.Account.id.in_(missing))).unique().all():
                self._acct_cache[r.id] = _acct(r)
        return {a: self._acct_cache[a] for a in set(account_ids) if a in self._acct_cache}

    def outgoing(self, account_id: str, after: datetime, until: datetime, limit: int) -> list[TxnRec]:
        q = (
            select(m.Transaction)
            .where(
                m.Transaction.debit_account_id == account_id,
                m.Transaction.occurred_at > after,
                m.Transaction.occurred_at <= until,
            )
            .order_by(m.Transaction.occurred_at, m.Transaction.id)
            .limit(limit)
        )
        return [_txn(r) for r in self.db.scalars(q).all()]

    def incoming(self, account_id: str, before: datetime, since: datetime, limit: int) -> list[TxnRec]:
        q = (
            select(m.Transaction)
            .where(
                m.Transaction.credit_account_id == account_id,
                m.Transaction.occurred_at < before,
                m.Transaction.occurred_at >= since,
            )
            .order_by(m.Transaction.occurred_at.desc(), m.Transaction.id)
            .limit(limit)
        )
        return [_txn(r) for r in self.db.scalars(q).all()]

    def count_outgoing(self, account_id: str, after: datetime, until: datetime) -> int:
        q = select(func.count()).select_from(m.Transaction).where(
            m.Transaction.debit_account_id == account_id,
            m.Transaction.occurred_at > after,
            m.Transaction.occurred_at <= until,
        )
        return int(self.db.scalar(q) or 0)

    def count_incoming(self, account_id: str, before: datetime, since: datetime) -> int:
        q = select(func.count()).select_from(m.Transaction).where(
            m.Transaction.credit_account_id == account_id,
            m.Transaction.occurred_at < before,
            m.Transaction.occurred_at >= since,
        )
        return int(self.db.scalar(q) or 0)

    def activity(self, account_id: str, start: datetime, end: datetime, limit: int) -> list[TxnRec]:
        q = (
            select(m.Transaction)
            .where(
                or_(m.Transaction.debit_account_id == account_id, m.Transaction.credit_account_id == account_id),
                m.Transaction.occurred_at >= start,
                m.Transaction.occurred_at <= end,
            )
            .order_by(m.Transaction.occurred_at, m.Transaction.id)
            .limit(limit)
        )
        return [_txn(r) for r in self.db.scalars(q).all()]

    def balance_before(self, account_id: str, at: datetime) -> int | None:
        acct = self.get_account(account_id)
        if acct is None or acct.external or acct.opening_balance_minor is None:
            return None
        eff = m.Transaction.status.in_(EFFECTIVE_STATUSES)
        credits = self.db.scalar(
            select(func.coalesce(func.sum(m.Transaction.amount_minor), 0)).where(
                and_(m.Transaction.credit_account_id == account_id, m.Transaction.occurred_at < at, eff)
            )
        )
        debits = self.db.scalar(
            select(func.coalesce(func.sum(m.Transaction.amount_minor), 0)).where(
                and_(m.Transaction.debit_account_id == account_id, m.Transaction.occurred_at < at, eff)
            )
        )
        return int(acct.opening_balance_minor) + int(credits or 0) - int(debits or 0)

    def reversals_of(self, txn_ids: Iterable[str]) -> list[TxnRec]:
        ids = list(set(txn_ids))
        if not ids:
            return []
        rows = self.db.scalars(select(m.Transaction).where(m.Transaction.reversal_of_id.in_(ids))).all()
        return [_txn(r) for r in rows]

    def debits_between(self, account_id: str, start: datetime, end: datetime, limit: int) -> list[TxnRec]:
        q = (
            select(m.Transaction)
            .where(
                m.Transaction.debit_account_id == account_id,
                m.Transaction.occurred_at >= start,
                m.Transaction.occurred_at < end,
            )
            .order_by(m.Transaction.occurred_at)
            .limit(limit)
        )
        return [_txn(r) for r in self.db.scalars(q).all()]

    def auth_events(self, account_id: str, start: datetime, end: datetime, limit: int) -> list[AuthRec] | None:
        # `None` means "no auth telemetry exists for this account at all" (not evaluable), while
        # an empty list means telemetry exists but nothing happened in the window.
        has_any = self.db.scalar(
            select(func.count()).select_from(m.AuthEvent).where(m.AuthEvent.account_id == account_id)
        )
        if not has_any:
            return None
        q = (
            select(m.AuthEvent)
            .where(m.AuthEvent.account_id == account_id, m.AuthEvent.occurred_at >= start, m.AuthEvent.occurred_at <= end)
            .order_by(m.AuthEvent.occurred_at)
            .limit(limit)
        )
        return [
            AuthRec(
                id=r.id,
                account_id=r.account_id,
                device_id=r.device_id,
                event_type=r.event_type,
                outcome=r.outcome,
                occurred_at=r.occurred_at,
                source_system=r.source_system,
                source_record_id=r.source_record_id,
            )
            for r in self.db.scalars(q).all()
        ]

    def get_device(self, device_id: str) -> DeviceRec | None:
        r = self.db.get(m.Device, device_id)
        return DeviceRec(id=r.id, label=r.label, first_seen_at=r.first_seen_at) if r else None

    def accounts_using_device(self, device_id: str, limit: int) -> list[str]:
        a = select(m.Transaction.debit_account_id).where(m.Transaction.device_id == device_id)
        b = select(m.AuthEvent.account_id).where(m.AuthEvent.device_id == device_id)
        ids = {x for x in self.db.scalars(a.limit(limit * 5)).all()} | {x for x in self.db.scalars(b.limit(limit * 5)).all()}
        return sorted(ids)[:limit]

    def cases_with_beneficiaries(self, account_ids: Iterable[str]) -> list[CaseLink]:
        ids = list(set(account_ids))
        if not ids:
            return []
        q = (
            select(m.DisputeCase.id, m.DisputeCase.disputed_txn_id, m.Transaction.credit_account_id, m.DisputeCase.status)
            .join(m.Transaction, m.Transaction.id == m.DisputeCase.disputed_txn_id)
            .where(m.Transaction.credit_account_id.in_(ids))
        )
        return [CaseLink(case_id=c, disputed_txn_id=t, beneficiary_account_id=a, status=s) for c, t, a, s in self.db.execute(q).all()]


# --------------------------------------------------------------------------------------------
# In-memory implementation (unit tests, fixtures)
# --------------------------------------------------------------------------------------------


class InMemoryGraphStore:
    def __init__(
        self,
        accounts: list[AccountRec],
        transactions: list[TxnRec],
        auth: list[AuthRec] | None = None,
        devices: list[DeviceRec] | None = None,
        case_links: list[CaseLink] | None = None,
    ):
        self.accounts = {a.id: a for a in accounts}
        self.txns = {t.id: t for t in transactions}
        self.auth = list(auth or [])
        self.devices = {d.id: d for d in devices or []}
        self.case_links = list(case_links or [])

    def _sorted(self, rows):
        return sorted(rows, key=lambda t: (t.occurred_at, t.id))

    def get_transaction(self, txn_id):
        return self.txns.get(txn_id)

    def get_transactions(self, txn_ids):
        return [self.txns[i] for i in set(txn_ids) if i in self.txns]

    def get_account(self, account_id):
        return self.accounts.get(account_id)

    def get_accounts(self, account_ids):
        return {a: self.accounts[a] for a in set(account_ids) if a in self.accounts}

    def outgoing(self, account_id, after, until, limit):
        rows = [t for t in self.txns.values() if t.debit_account_id == account_id and after < t.occurred_at <= until]
        return self._sorted(rows)[:limit]

    def incoming(self, account_id, before, since, limit):
        rows = [t for t in self.txns.values() if t.credit_account_id == account_id and since <= t.occurred_at < before]
        return sorted(rows, key=lambda t: (t.occurred_at, t.id), reverse=True)[:limit]

    def count_outgoing(self, account_id, after, until):
        return sum(1 for t in self.txns.values() if t.debit_account_id == account_id and after < t.occurred_at <= until)

    def count_incoming(self, account_id, before, since):
        return sum(1 for t in self.txns.values() if t.credit_account_id == account_id and since <= t.occurred_at < before)

    def activity(self, account_id, start, end, limit):
        rows = [
            t
            for t in self.txns.values()
            if (t.debit_account_id == account_id or t.credit_account_id == account_id) and start <= t.occurred_at <= end
        ]
        return self._sorted(rows)[:limit]

    def balance_before(self, account_id, at):
        a = self.accounts.get(account_id)
        if a is None or a.external or a.opening_balance_minor is None:
            return None
        bal = a.opening_balance_minor
        for t in self.txns.values():
            if t.occurred_at < at and t.moved_money:
                if t.credit_account_id == account_id:
                    bal += t.amount_minor
                if t.debit_account_id == account_id:
                    bal -= t.amount_minor
        return bal

    def reversals_of(self, txn_ids):
        ids = set(txn_ids)
        return [t for t in self.txns.values() if t.reversal_of_id in ids]

    def debits_between(self, account_id, start, end, limit):
        rows = [t for t in self.txns.values() if t.debit_account_id == account_id and start <= t.occurred_at < end]
        return self._sorted(rows)[:limit]

    def auth_events(self, account_id, start, end, limit):
        rows = [a for a in self.auth if a.account_id == account_id]
        if not rows:
            return None
        return sorted([a for a in rows if start <= a.occurred_at <= end], key=lambda a: a.occurred_at)[:limit]

    def get_device(self, device_id):
        return self.devices.get(device_id)

    def accounts_using_device(self, device_id, limit):
        ids = {t.debit_account_id for t in self.txns.values() if t.device_id == device_id}
        ids |= {a.account_id for a in self.auth if a.device_id == device_id}
        return sorted(ids)[:limit]

    def cases_with_beneficiaries(self, account_ids):
        ids = set(account_ids)
        return [c for c in self.case_links if c.beneficiary_account_id in ids]
