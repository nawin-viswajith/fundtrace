"""Relational source of truth (Cloud SQL for MySQL in production, SQLite locally).

Conventions:
- Money is always an integer number of minor units (paise/cents) plus an ISO currency code.
- All datetimes are naive UTC.
- `is_synthetic` marks demo data; the UI shows a SYNTHETIC banner whenever it is set.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.crypto import EncryptedJSON, EncryptedText
from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32))  # investigator | supervisor | admin | customer
    # set only for role "customer": the bank customer this login belongs to (customer portal)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # TOTP MFA. The secret is encrypted; recovery codes are stored only as SHA-256 hashes.
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    mfa_secret: Mapped[str | None] = mapped_column(EncryptedText("users.mfa_secret"), nullable=True)
    mfa_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # last accepted time step (replay guard)
    mfa_recovery: Mapped[list | None] = mapped_column(JSON, nullable=True)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    display_name: Mapped[str] = mapped_column(EncryptedText("customers.display_name"))
    segment: Mapped[str] = mapped_column(String(32), default="retail")
    preferred_language: Mapped[str] = mapped_column(String(16), default="en")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class Institution(Base):
    __tablename__ = "institutions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))  # self | external


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    institution_id: Mapped[str] = mapped_column(ForeignKey("institutions.id"))
    kind: Mapped[str] = mapped_column(String(16))  # savings | current | wallet | merchant | external
    holder_label: Mapped[str] = mapped_column(EncryptedText("accounts.holder_label"))
    masked_number: Mapped[str] = mapped_column(String(32))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    opening_balance_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)

    institution: Mapped[Institution] = relationship(lazy="joined")


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    fingerprint_hash: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(64), default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime)


class AuthEvent(Base):
    __tablename__ = "auth_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32))  # login | otp | mpin
    outcome: Mapped[str] = mapped_column(String(16))  # success | failure
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    source_system: Mapped[str] = mapped_column(String(32))
    source_record_id: Mapped[str] = mapped_column(String(64))

    __table_args__ = (Index("ix_auth_account_time", "account_id", "occurred_at"),)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_system: Mapped[str] = mapped_column(String(32))
    source_record_id: Mapped[str] = mapped_column(String(64))
    debit_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    credit_account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16))  # posted | pending | failed | reversed
    channel: Mapped[str] = mapped_column(String(16))  # UPI | IMPS | NEFT | RTGS | CARD | INTERNAL
    reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reversal_of_id: Mapped[str | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.id"), nullable=True)
    narrative: Mapped[str] = mapped_column(String(255), default="")
    # Every source record merged into this transaction, with the values each source reported.
    sources: Mapped[list] = mapped_column(JSON, default=list)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("source_system", "source_record_id", name="uq_txn_source"),
        Index("ix_txn_debit_time", "debit_account_id", "occurred_at"),
        Index("ix_txn_credit_time", "credit_account_id", "occurred_at"),
        Index("ix_txn_reference", "reference"),
    )


class DisputeCase(Base):
    __tablename__ = "dispute_cases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    disputed_txn_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    category: Mapped[str] = mapped_column(String(48))
    category_source: Mapped[str] = mapped_column(String(16), default="intake")  # intake | ai | investigator
    allegation: Mapped[str] = mapped_column(EncryptedText("dispute_cases.allegation"))  # customer-provided, untrusted
    allegation_language: Mapped[str] = mapped_column(String(16), default="en")
    allegation_translation: Mapped[str | None] = mapped_column(EncryptedText("dispute_cases.allegation_translation"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="new")
    priority: Mapped[str] = mapped_column(String(4), default="P3")
    priority_reasons: Mapped[list] = mapped_column(JSON, default=list)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reported_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sla_policy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(24), nullable=True)
    decision_rationale: Mapped[str | None] = mapped_column(EncryptedText("dispute_cases.decision_rationale"), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    scenario: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # How the dispute was raised (seed | portal_form | portal_chat) and the customer's own answers
    # (OTP shared, when noticed, cyber complaint number, contact preference). Customer-provided, untrusted.
    channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    intake: Mapped[dict | None] = mapped_column(EncryptedJSON("dispute_cases.intake"), nullable=True)

    owner: Mapped[User | None] = relationship(foreign_keys=[owner_id], lazy="joined")
    disputed_txn: Mapped[Transaction] = relationship(lazy="joined")


class CaseNote(Base):
    __tablename__ = "case_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("dispute_cases.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(EncryptedText("case_notes.body"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("dispute_cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # customer_upload | bank_record | merchant_response | complaint_ack
    checklist_key: Mapped[str | None] = mapped_column(String(48), nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_uri: Mapped[str] = mapped_column(String(512))
    size: Mapped[int] = mapped_column(Integer)
    uploaded_by: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    analysis_status: Mapped[str] = mapped_column(String(16), default="not_analysed")
    analysis_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extracted: Mapped[dict | None] = mapped_column(EncryptedJSON("evidence_items.extracted"), nullable=True)
    reconciliation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Retention: active | deletion_requested | deleted. A deleted item keeps its metadata and hash (tombstone).
    retention_status: Mapped[str] = mapped_column(String(24), default="active", server_default="active")
    retention_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Sensitive-data scan of the file: {backend, status, findings: [{type, label, count, likelihood}], scanned_at}
    dlp: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class EvidenceRequest(Base):
    __tablename__ = "evidence_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("dispute_cases.id"), index=True)
    checklist_key: Mapped[str] = mapped_column(String(48))
    requested_from: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | received | cancelled
    note: Mapped[str] = mapped_column(EncryptedText("evidence_requests.note"), default="")
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Hold(Base):
    __tablename__ = "holds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("dispute_cases.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    basis: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="recommended")  # recommended | requested | declined
    recommended_by: Mapped[str] = mapped_column(String(32), default="system")
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(EncryptedText("holds.decision_note"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RuleVersion(Base):
    __tablename__ = "rule_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(String(16), index=True)
    version: Mapped[int] = mapped_column(Integer)
    params: Mapped[dict] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    change_note: Mapped[str] = mapped_column(String(255), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_rule_version"),)


class RiskFlag(Base):
    __tablename__ = "risk_flags"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("dispute_cases.id"), index=True)
    evaluation_id: Mapped[str] = mapped_column(String(32), index=True)
    rule_id: Mapped[str] = mapped_column(String(16))
    rule_version: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(96))
    severity: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16))  # triggered | not_triggered | not_evaluable
    facts: Mapped[list] = mapped_column(JSON, default=list)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)
    suggested_step: Mapped[str] = mapped_column(Text, default="")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AIRun(Base):
    __tablename__ = "ai_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("dispute_cases.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(32))  # investigation | copilot | evidence | classification
    status: Mapped[str] = mapped_column(String(24), default="running")
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    models: Mapped[list] = mapped_column(JSON, default=list)
    prompt_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    ruleset_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_log: Mapped[list] = mapped_column(JSON, default=list)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AICall(Base):
    __tablename__ = "ai_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    case_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    node: Mapped[str] = mapped_column(String(48))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # ok | error | timeout | invalid | budget | disabled
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    thinking_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    avg_logprob: Mapped[float | None] = mapped_column(Float, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("dispute_cases.id"), index=True)
    run_id: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))  # verified | partially_verified | unverified | facts_only
    generator: Mapped[str] = mapped_column(String(64))  # model id or "deterministic"
    sections: Mapped[list] = mapped_column(JSON, default=list)
    recommended_actions: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    claims_total: Mapped[int] = mapped_column(Integer, default=0)
    claims_supported: Mapped[int] = mapped_column(Integer, default=0)
    claims_flagged: Mapped[int] = mapped_column(Integer, default=0)
    hallucination_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | accepted | rejected | partial
    review: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReportDraft(Base):
    """Unsaved edits to a report (e.g. a section cleared through the case assistant). Saving creates a new version."""
    __tablename__ = "report_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(ForeignKey("reports.id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("dispute_cases.id"), index=True)
    sections: Mapped[list] = mapped_column(JSON, default=list)
    changes: Mapped[list] = mapped_column(JSON, default=list)  # [{op, section_key, claim_ids, by, via, at}]
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | saved | discarded
    saved_report_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    version: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(160))
    categories: Mapped[list] = mapped_column(JSON, default=list)
    jurisdiction: Mapped[str] = mapped_column(String(16), default="IN")
    effective_from: Mapped[str] = mapped_column(String(16))
    clauses: Mapped[list] = mapped_column(JSON, default=list)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    details: Mapped[list] = mapped_column(JSON, default=list)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    actor_role: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(48))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class IngestEvent(Base):
    """One ledger delivery (a Pub/Sub message or an uploaded statement) and what happened to it."""
    __tablename__ = "ingest_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(128), unique=True)  # Pub/Sub messageId or file hash: dedupes redelivery
    channel: Mapped[str] = mapped_column(String(16))  # pubsub | upload
    source_system: Mapped[str] = mapped_column(String(32))
    format: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # processed | partial | rejected
    records_in: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[int] = mapped_column(Integer, default=0)
    merged: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[list] = mapped_column(JSON, default=list)
    placeholder_accounts: Mapped[int] = mapped_column(Integer, default=0)
    cases_refreshed: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_by: Mapped[str] = mapped_column(String(128))
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
