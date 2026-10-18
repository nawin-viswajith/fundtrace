"""Assembles a case's investigation context from deterministic services.

This is the single place that turns database rows into the facts the UI, the rules and the AI
investigator all share, so every consumer sees the same numbers.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.config import get_settings
from app.services import evidence_scoring, scoring
from app.services.attribution import annotate_graph, attribute
from app.services.graph_store import SqlGraphStore
from app.services.policy import evaluate_eligibility
from app.services.rules import CATALOGUE_BY_ID, RuleContext, evaluate, ruleset_version, summarise
from app.services.trace import CONTRADICTORY, DERIVED, UNKNOWN, TraceParams, TraceResult, trace


def rule_overrides(db: Session) -> dict[str, tuple[int, dict, bool]]:
    out: dict[str, tuple[int, dict, bool]] = {}
    for rv in db.scalars(select(m.RuleVersion).order_by(m.RuleVersion.rule_id, m.RuleVersion.version)).all():
        out[rv.rule_id] = (rv.version, rv.params, rv.enabled)
    return out


def evidence_dicts(db: Session, case_id: str) -> list[dict]:
    rows = db.scalars(select(m.EvidenceItem).where(m.EvidenceItem.case_id == case_id).order_by(m.EvidenceItem.uploaded_at)).all()
    return [evidence_to_dict(e) for e in rows]


def evidence_to_dict(e: m.EvidenceItem) -> dict:
    out = {"id": e.id, "case_id": e.case_id, "kind": e.kind, "checklist_key": e.checklist_key, "filename": e.filename,
            "mime": e.mime, "sha256": e.sha256, "size": e.size, "uploaded_by": e.uploaded_by,
            "uploaded_at": e.uploaded_at.isoformat() + "Z", "analysis_status": e.analysis_status, "analysis_note": e.analysis_note,
            "extracted": e.extracted, "reconciliation": e.reconciliation, "is_synthetic": e.is_synthetic,
            "retention_status": e.retention_status or "active", "retention_note": e.retention_note,
            "deleted_at": e.deleted_at.isoformat() + "Z" if e.deleted_at else None, "dlp": e.dlp}
    out["score"] = evidence_scoring.score(out)
    return out


def request_dicts(db: Session, case_id: str) -> list[dict]:
    rows = db.scalars(select(m.EvidenceRequest).where(m.EvidenceRequest.case_id == case_id)).all()
    return [{"id": r.id, "checklist_key": r.checklist_key, "requested_from": r.requested_from, "status": r.status, "note": r.note,
             "created_at": r.created_at.isoformat() + "Z"} for r in rows]


def default_params(**kw) -> TraceParams:
    s = get_settings()
    p = TraceParams(depth=s.trace_default_depth, window_hours=s.trace_default_window_hours, max_nodes=s.trace_default_max_nodes,
                    hub_threshold=s.trace_hub_threshold, per_account_cap=s.trace_per_account_cap)
    for k, v in kw.items():
        if v is not None:
            setattr(p, k, v)
    return p.clamp(s.trace_max_depth, s.trace_max_window_hours, s.trace_max_nodes)


def build_trace(db: Session, case: m.DisputeCase, params: TraceParams | None = None
                ) -> tuple[TraceResult, TraceResult, dict, SqlGraphStore]:
    """Returns (display trace, forward trace, attribution, store)."""
    store = SqlGraphStore(db)
    p = params or default_params()
    res = trace(store, case.disputed_txn_id, p)
    # Attribution and rules always use a forward trace (they follow where the funds went).
    fwd = res if p.direction in ("forward", "both") else trace(store, case.disputed_txn_id, TraceParams(**{**p.__dict__, "direction": "forward"}))
    att = attribute(store, fwd)
    annotate_graph(res, att)
    return res, fwd, att, store


def build_context(db: Session, case: m.DisputeCase, params: TraceParams | None = None, now: datetime | None = None,
                  persist_flags: bool = False) -> dict:
    now = now or m.utcnow()
    res, fwd, att, store = build_trace(db, case, params)
    root = store.get_transaction(case.disputed_txn_id)
    payer, payee = store.get_account(root.debit_account_id), store.get_account(root.credit_account_id)
    evidence = evidence_dicts(db, case.id)
    add_evidence_nodes(res, evidence, root.id)
    requests = request_dicts(db, case.id)
    overrides = rule_overrides(db)
    rules = evaluate(RuleContext(case_id=case.id, category=case.category, root=root, payer=payer, payee=payee, trace=fwd,
                                 attribution=att, store=store, evidence=evidence, now=now), overrides)
    rs_version = ruleset_version(overrides)
    sla_info = scoring.sla(case.category, root.currency, case.reported_at, now)
    prio, reasons = scoring.priority(root, rules, att, sla_info, case.reported_at)
    ctx = {
        "case": case_summary(case),
        "disputed_transaction": res.nodes[root.id]["data"] | {"id": root.id},
        "payer": res.nodes[payer.id],
        "beneficiary": res.nodes[payee.id],
        "graph": res.to_dict(),
        "attribution": att,
        "rules": [r.to_dict() for r in rules],
        "rules_summary": summarise(rules),
        "ruleset_version": rs_version,
        "completeness": scoring.completeness(case.category, case.allegation, root, payer, payee, store, evidence, requests, att),
        "consistency": scoring.consistency(case.allegation, root, store, evidence),
        "traceability": scoring.traceability(res, att),
        "policy": evaluate_eligibility(case.category, root.occurred_at, case.reported_at),
        "sla": sla_info,
        "computed_priority": {"priority": prio, "reasons": reasons},
        "evidence": evidence,
        "evidence_requests": requests,
        "holds": hold_dicts(db, case.id),
        "generated_at": now.isoformat() + "Z",
    }
    if persist_flags:
        eval_id = "EVAL-" + uuid.uuid4().hex[:10].upper()
        for r in rules:
            db.add(m.RiskFlag(id=f"FLAG-{case.id[-6:]}-{r.rule_id}-{eval_id[-4:]}", case_id=case.id, evaluation_id=eval_id,
                              rule_id=r.rule_id, rule_version=r.version, name=r.name, severity=r.severity, status=r.status,
                              facts=r.facts, source_ids=r.source_ids, params=r.params, limitations=r.limitations,
                              missing_fields=r.missing_fields, suggested_step=r.suggested_step, evaluated_at=now))
        ctx["evaluation_id"] = eval_id
    return ctx


def add_evidence_nodes(res: TraceResult, evidence: list[dict], root_id: str) -> None:
    """Evidence appears on the graph linked to the transaction it was reconciled against."""
    for e in evidence:
        rec = e.get("reconciliation") or {}
        target = rec.get("matched_txn_id") or root_id
        if e["analysis_status"] != "analysed":
            prov, etype, label = UNKNOWN, "relates_to", "not analysed"
        elif rec.get("contradictions"):
            prov, etype, label = CONTRADICTORY, "contradicts", rec.get("summary")
        elif rec.get("matches"):
            prov, etype, label = DERIVED, "supports", rec.get("summary")
        else:
            prov, etype, label = UNKNOWN, "relates_to", rec.get("summary") or "no comparable fields"
        res.nodes[e["id"]] = {"id": e["id"], "type": "evidence", "label": e["filename"], "provenance": prov, "source_ids": [e["id"]],
                              "depth": 0, "roles": ["evidence"], "endpoint": None,
                              "data": {"kind": e["kind"], "analysis_status": e["analysis_status"], "sha256": e["sha256"],
                                       "checks": rec.get("checks"), "summary": rec.get("summary")}}
        res.add_edge(e["id"], target, etype, prov, [e["id"], target], None, label)


def hold_dicts(db: Session, case_id: str) -> list[dict]:
    rows = db.scalars(select(m.Hold).where(m.Hold.case_id == case_id).order_by(m.Hold.id)).all()
    return [{"id": h.id, "account_id": h.account_id, "amount_minor": h.amount_minor, "currency": h.currency, "basis": h.basis,
             "status": h.status, "recommended_by": h.recommended_by, "decision_note": h.decision_note,
             "created_at": h.created_at.isoformat() + "Z", "decided_at": h.decided_at.isoformat() + "Z" if h.decided_at else None}
            for h in rows]


def case_summary(c: m.DisputeCase) -> dict:
    t = c.disputed_txn
    return {
        "id": c.id, "category": c.category, "category_label": scoring.CATEGORIES.get(c.category, c.category),
        "category_source": c.category_source, "status": c.status, "priority": c.priority, "priority_reasons": c.priority_reasons,
        "owner": {"id": c.owner.id, "username": c.owner.username, "full_name": c.owner.full_name} if c.owner else None,
        "allegation": c.allegation, "allegation_language": c.allegation_language, "allegation_translation": c.allegation_translation,
        "reported_at": c.reported_at.isoformat() + "Z", "created_at": c.created_at.isoformat() + "Z",
        "updated_at": c.updated_at.isoformat() + "Z" if c.updated_at else None,
        "due_at": c.due_at.isoformat() + "Z" if c.due_at else None, "sla_policy": c.sla_policy,
        "decision": c.decision, "decision_rationale": c.decision_rationale,
        "decided_at": c.decided_at.isoformat() + "Z" if c.decided_at else None,
        "disputed_txn_id": c.disputed_txn_id, "customer_id": c.customer_id,
        "amount_minor": t.amount_minor if t else None, "currency": t.currency if t else None,
        "txn_status": t.status if t else None, "txn_reference": t.reference if t else None,
        "is_synthetic": c.is_synthetic, "scenario": c.scenario,
        "channel": c.channel or "seed", "intake": c.intake,
    }


def rule_catalogue(db: Session) -> list[dict]:
    ov = rule_overrides(db)
    out = []
    for rid, rd in CATALOGUE_BY_ID.items():
        version, params, enabled = ov.get(rid, (1, rd.default_params, True))
        out.append({"rule_id": rid, "name": rd.name, "description": rd.description, "severity": rd.default_severity,
                    "version": version, "params": {**rd.default_params, **(params or {})}, "default_params": rd.default_params,
                    "enabled": enabled, "needs": rd.needs})
    return out


def sync_hold_recommendations(db: Session, case: m.DisputeCase, attribution: dict) -> int:
    """Create 'recommended' holds for visible accounts that may still hold disputed funds.

    Deterministic (from attribution), idempotent, never applied without investigator approval.
    """
    existing = {h.account_id for h in db.scalars(select(m.Hold).where(m.Hold.case_id == case.id)).all()}
    added = 0
    for h in attribution.get("holdable", []):
        if h["account_id"] in existing or h["max_minor"] <= 0:
            continue
        db.add(m.Hold(case_id=case.id, account_id=h["account_id"], amount_minor=h["max_minor"], currency=attribution["currency"],
                      basis={"min_minor": h["min_minor"], "max_minor": h["max_minor"], "by_method": h.get("by_method"),
                             "citations": [f"HOLD-{h['account_id']}", f"ATTR-{h['account_id']}"],
                             "method": "attribution upper bound, capped by balance"},
                      status="recommended", recommended_by="system (attribution)"))
        added += 1
    if added:
        db.flush()
    return added
