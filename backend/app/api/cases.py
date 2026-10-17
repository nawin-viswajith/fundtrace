import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.config import get_settings
from app.db import get_db
from app.security import can_access_case, current_user, load_case_for
from app.services import investigation as inv
from app.services.storage import StorageError, get_storage, sha256, sniff_mime
from app.services.trace import fmt_amount
from app.services.workflow import DECISIONS, STATUS_LABELS, STATUSES, TRANSITIONS, apply_action, review_report

router = APIRouter(prefix="/api", tags=["cases"])

GRAPH_RELATIONS = {"sent", "received_by", "reversal_of", "possible_onward_funding", "supports", "contradicts", "relates_to"}
TXN_STATUSES = {"posted", "pending", "failed", "reversed"}


# ---------------------------------------------------------------------------- queue

@router.get("/cases")
def list_cases(status: str | None = None, priority: str | None = None, owner: str = Query("all", pattern="^(all|me|unassigned)$"),
               q: str | None = Query(None, max_length=64), user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(m.DisputeCase)
    if user.role == "investigator":
        stmt = stmt.where(or_(m.DisputeCase.owner_id.is_(None), m.DisputeCase.owner_id == user.id))
    if status:
        if status not in STATUSES:
            raise HTTPException(422, "Unknown status")
        stmt = stmt.where(m.DisputeCase.status == status)
    if priority:
        stmt = stmt.where(m.DisputeCase.priority == priority)
    if owner == "me":
        stmt = stmt.where(m.DisputeCase.owner_id == user.id)
    elif owner == "unassigned":
        stmt = stmt.where(m.DisputeCase.owner_id.is_(None))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(m.DisputeCase.id.like(like), m.DisputeCase.disputed_txn_id.like(like)))
    rows = db.scalars(stmt).unique().all()
    order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
    rows.sort(key=lambda c: (c.status == "resolved", order.get(c.priority, 9), c.due_at or c.reported_at))
    now = m.utcnow()
    out = []
    for c in rows:
        s = inv.case_summary(c)
        # Show the next SLA milestone that is still open (e.g. shadow credit before final resolution);
        # if every milestone is already breached, show the earliest breach.
        from app.services.scoring import sla as sla_clock

        ms = sla_clock(c.category, c.disputed_txn.currency, c.reported_at, now)["milestones"]
        open_ms = sorted((m_ for m_ in ms if not m_["breached"]), key=lambda m_: m_["remaining_hours"])
        nxt = open_ms[0] if open_ms else min(ms, key=lambda m_: m_["remaining_hours"])
        s["sla_remaining_hours"] = nxt["remaining_hours"]
        s["sla_next_label"] = nxt["label"]
        s["amount_label"] = fmt_amount(c.disputed_txn.amount_minor, c.disputed_txn.currency)
        out.append(s)
    counts = {st: sum(1 for c in rows if c.status == st) for st in STATUSES}
    return {"cases": out, "counts": counts, "status_labels": STATUS_LABELS}


@router.get("/meta")
def meta(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services.scoring import CATEGORIES

    users = db.scalars(select(m.User).where(m.User.role.in_(("investigator", "supervisor")))).all()
    return {"statuses": STATUSES, "status_labels": STATUS_LABELS, "categories": CATEGORIES, "decisions": DECISIONS,
            "graph_relations": sorted(GRAPH_RELATIONS), "assignees": [{"id": u.id, "username": u.username, "full_name": u.full_name,
                                                                        "role": u.role} for u in users],
            "limits": {"max_depth": get_settings().trace_max_depth, "max_window_hours": get_settings().trace_max_window_hours,
                       "max_nodes": get_settings().trace_max_nodes}}


# ---------------------------------------------------------------------------- case context

@router.get("/cases/{case_id}")
def get_case(case_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    case = load_case_for(user, db, case_id)
    ctx = inv.build_context(db, case)
    ctx["notes"] = [{"id": n.id, "author": db.get(m.User, n.author_id).username, "body": n.body, "created_at": n.created_at.isoformat() + "Z"}
                    for n in db.scalars(select(m.CaseNote).where(m.CaseNote.case_id == case.id).order_by(m.CaseNote.id)).all()]
    latest = db.scalar(select(m.Report).where(m.Report.case_id == case.id).order_by(m.Report.version.desc()).limit(1))
    ctx["latest_report"] = report_brief(latest) if latest else None
    ctx["allowed_transitions"] = sorted(TRANSITIONS.get(case.status, []))
    ctx["can_edit"] = can_access_case(user, case)
    last = db.scalar(select(m.AuditEvent).where(m.AuditEvent.case_id == case.id).order_by(m.AuditEvent.id.desc()).limit(1))
    if not (last and last.action == "case_viewed" and last.actor == user.username and (m.utcnow() - last.created_at) < timedelta(minutes=30)):
        audit.record(db, case.id, user.username, user.role, "case_viewed", {})  # access log, de-duplicated
        db.commit()
    return ctx


def _graph_params(direction, depth, window_hours, max_nodes, expand: tuple[str, ...] = ()):
    try:
        return inv.default_params(direction=direction, depth=depth, window_hours=window_hours, max_nodes=max_nodes, expand_accounts=expand)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


def _filter_graph(g: dict, statuses: set[str] | None, rels: set[str] | None) -> dict:
    if statuses:
        drop = {n["id"] for n in g["nodes"] if n["type"] == "transaction" and n["data"]["status"] not in statuses and "disputed" not in (n.get("roles") or [])}
        g["nodes"] = [n for n in g["nodes"] if n["id"] not in drop]
        g["edges"] = [e for e in g["edges"] if e["source"] not in drop and e["target"] not in drop]
    if rels:
        g["edges"] = [e for e in g["edges"] if e["type"] in rels]
    return g


@router.get("/cases/{case_id}/graph")
def graph(case_id: str, direction: str = Query("forward", pattern="^(forward|backward|both)$"), depth: int = Query(3, ge=1, le=10),
          window_hours: int = Query(72, ge=1, le=10000), max_nodes: int = Query(150, ge=10, le=2000),
          status: str | None = Query(None, max_length=64), rel: str | None = Query(None, max_length=200),
          expand: str | None = Query(None, max_length=400), user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    case = load_case_for(user, db, case_id)
    statuses = {s for s in (status or "").split(",") if s}
    rels = {r for r in (rel or "").split(",") if r}
    if statuses - TXN_STATUSES or rels - GRAPH_RELATIONS:
        raise HTTPException(422, "Unknown status or relationship filter")
    exp = tuple(a for a in (expand or "").split(",") if a)[:10]
    if exp:
        base, _, _, _ = inv.build_trace(db, case, _graph_params(direction, depth, window_hours, max_nodes))
        known = {n["id"] for n in base.nodes.values() if n["type"] == "account"}
        if not set(exp) <= known:
            raise HTTPException(422, "Only accounts already on the trail can be expanded")
    res, _, att, store = inv.build_trace(db, case, _graph_params(direction, depth, window_hours, max_nodes, exp))
    root = store.get_transaction(case.disputed_txn_id)
    inv.add_evidence_nodes(res, inv.evidence_dicts(db, case.id), root.id)
    g = _filter_graph(res.to_dict(), statuses, rels)
    if exp:
        audit.record(db, case.id, user.username, user.role, "graph_expanded", {"accounts": list(exp)})
        db.commit()
    return {"graph": g, "attribution": att}


@router.get("/cases/{case_id}/timeline")
def timeline(case_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    case = load_case_for(user, db, case_id)
    res, _, att, store = inv.build_trace(db, case, inv.default_params(direction="both"))
    root = store.get_transaction(case.disputed_txn_id)
    items = []
    for t in res.txns.values():
        a = att.get("per_transaction", {}).get(t.id)
        node = res.nodes[t.id]
        items.append({"time": t.occurred_at.isoformat() + "Z", "kind": "transaction", "id": t.id,
                      "title": f"{fmt_amount(t.amount_minor, t.currency)} {t.channel} {t.debit_account_id} → {t.credit_account_id}",
                      "status": t.status, "reference": t.reference, "provenance": "confirmed", "source_ids": [t.id],
                      "role": (node.get("roles") or [node.get("direction")])[0], "attribution": a, "note": node.get("note")})
    evs = store.auth_events(root.debit_account_id, root.occurred_at - timedelta(hours=2), root.occurred_at, 50) or []
    for e in evs:
        items.append({"time": e.occurred_at.isoformat() + "Z", "kind": "auth_event", "id": e.id, "title": f"{e.event_type} {e.outcome}",
                      "status": e.outcome, "provenance": "confirmed", "source_ids": [e.id], "device": e.device_id})
    items.append({"time": case.reported_at.isoformat() + "Z", "kind": "case", "id": case.id, "title": "Customer reported the dispute",
                  "provenance": "confirmed", "source_ids": [case.id]})
    for e in inv.evidence_dicts(db, case.id):
        items.append({"time": e["uploaded_at"], "kind": "evidence", "id": e["id"], "title": f"Evidence received: {e['filename']}",
                      "status": e["analysis_status"], "provenance": "confirmed", "source_ids": [e["id"]]})
    items.sort(key=lambda x: x["time"])
    return {"items": items, "disputed_txn_id": root.id, "empty": len(res.txns) <= 1}


# ---------------------------------------------------------------------------- risk

@router.get("/cases/{case_id}/risk")
def risk(case_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    case = load_case_for(user, db, case_id)
    ctx = inv.build_context(db, case)
    return {"rules": ctx["rules"], "summary": ctx["rules_summary"], "ruleset_version": ctx["ruleset_version"]}


@router.post("/cases/{case_id}/risk/evaluate")
def risk_evaluate(case_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    case = load_case_for(user, db, case_id)
    ctx = inv.build_context(db, case, persist_flags=True)
    from app.seed.loader import refresh_case_assessments

    refresh_case_assessments(db, [case.id])
    audit.record(db, case.id, user.username, user.role, "rules_evaluated", {"evaluation_id": ctx["evaluation_id"],
                                                                            "ruleset_version": ctx["ruleset_version"], **ctx["rules_summary"]})
    db.commit()
    return {"evaluation_id": ctx["evaluation_id"], "rules": ctx["rules"], "summary": ctx["rules_summary"]}


# ---------------------------------------------------------------------------- evidence

@router.get("/cases/{case_id}/evidence")
def evidence(case_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    case = load_case_for(user, db, case_id)
    ctx = inv.build_context(db, case)
    return {"evidence": ctx["evidence"], "checklist": ctx["completeness"], "requests": ctx["evidence_requests"],
            "consistency": ctx["consistency"]}


@router.post("/cases/{case_id}/evidence")
async def upload_evidence(case_id: str, file: UploadFile = File(...), checklist_key: str | None = Form(None),
                          kind: str = Form("customer_upload"), user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    case = load_case_for(user, db, case_id)
    if kind not in ("customer_upload", "bank_record", "merchant_response", "complaint_ack"):
        raise HTTPException(422, "Unknown evidence kind")
    s = get_settings()
    data = await file.read(s.max_upload_bytes + 1)
    if len(data) > s.max_upload_bytes:
        raise HTTPException(413, f"File too large (max {s.max_upload_bytes // (1024 * 1024)} MB)")
    if not data:
        raise HTTPException(422, "Empty file")
    try:
        mime = sniff_mime(data, file.content_type, file.filename or "")
    except StorageError as exc:
        raise HTTPException(415, str(exc))
    uri = get_storage().put(data, case.id, mime)
    eid = "EV-" + uuid.uuid4().hex[:8].upper()
    name = (file.filename or "upload").replace("/", "_").replace("\\", "_")[:200]
    db.add(m.EvidenceItem(id=eid, case_id=case.id, kind=kind, checklist_key=checklist_key, filename=name, mime=mime, sha256=sha256(data),
                          storage_uri=uri, size=len(data), uploaded_by=user.username, analysis_status="not_analysed", is_synthetic=False))
    db.flush()
    audit.record(db, case.id, user.username, user.role, "evidence_uploaded", {"evidence_id": eid, "filename": name, "sha256": sha256(data),
                                                                               "size": len(data), "mime": mime})
    db.commit()
    return {"id": eid, "analysis_status": "not_analysed"}


@router.post("/cases/{case_id}/evidence/{evidence_id}/analyse")
def analyse_evidence(case_id: str, evidence_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    from app.ai.evidence import analyse_item
    from app.ai.llm import get_gateway

    case = load_case_for(user, db, case_id)
    item = db.get(m.EvidenceItem, evidence_id)
    if item is None or item.case_id != case.id:
        raise HTTPException(404, "Evidence not found")
    if item.retention_status == "deleted":
        raise HTTPException(409, "This evidence file was deleted under the retention policy")
    result = analyse_item(db, item, get_gateway(), actor=user.username)
    db.commit()
    return {**result, "evidence": inv.evidence_to_dict(item)}


@router.get("/cases/{case_id}/evidence/{evidence_id}/file")
def evidence_file(case_id: str, evidence_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    case = load_case_for(user, db, case_id)
    item = db.get(m.EvidenceItem, evidence_id)
    if item is None or item.case_id != case.id:
        raise HTTPException(404, "Evidence not found")
    if item.retention_status == "deleted":
        raise HTTPException(410, "This evidence file was deleted under the retention policy; its hash is kept in the audit trail")
    data = get_storage().get(item.storage_uri)
    audit.record(db, case.id, user.username, user.role, "evidence_viewed", {"evidence_id": item.id})
    db.commit()
    return Response(content=data, media_type=item.mime, headers={"Content-Disposition": f'inline; filename="{item.filename}"',
                                                                 "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


# ---------------------------------------------------------------------------- actions + audit

class ActionIn(BaseModel):
    type: str = Field(max_length=32)
    model_config = {"extra": "allow"}


@router.post("/cases/{case_id}/actions")
def action(case_id: str, body: ActionIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    case = load_case_for(user, db, case_id)
    result = apply_action(db, case, user, body.model_dump())
    if body.type in ("status", "decision", "recategorise", "hold"):
        from app.seed.loader import refresh_case_assessments

        refresh_case_assessments(db, [case.id])
    db.commit()
    return result


@router.get("/cases/{case_id}/audit")
def audit_trail(case_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    case = load_case_for(user, db, case_id)
    rows = db.scalars(select(m.AuditEvent).where(m.AuditEvent.case_id == case.id).order_by(m.AuditEvent.id)).all()
    return {"events": [audit.to_dict(e) for e in rows], "verification": audit.verify(db, case.id)}


@router.get("/cases/{case_id}/audit/verify")
def audit_verify(case_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    case = load_case_for(user, db, case_id)
    return audit.verify(db, case.id)


# ---------------------------------------------------------------------------- AI

@router.post("/cases/{case_id}/investigate")
def investigate(case_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    from app.ai.investigator import run_investigation

    case = load_case_for(user, db, case_id)
    rep = run_investigation(db, case, actor=user.username)
    db.commit()
    return report_full(db, rep)


@router.get("/cases/{case_id}/reports")
def reports(case_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    case = load_case_for(user, db, case_id)
    rows = db.scalars(select(m.Report).where(m.Report.case_id == case.id).order_by(m.Report.version.desc())).all()
    return {"reports": [report_brief(r) for r in rows]}


@router.get("/reports/{report_id}")
def get_report(report_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rep = db.get(m.Report, report_id)
    if rep is None:
        raise HTTPException(404, "Report not found")
    load_case_for(user, db, rep.case_id)
    return report_full(db, rep)


@router.post("/reports/{report_id}/review")
def post_review(report_id: str, body: dict, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rep = db.get(m.Report, report_id)
    if rep is None:
        raise HTTPException(404, "Report not found")
    load_case_for(user, db, rep.case_id)
    out = review_report(db, rep, user, body)
    db.commit()
    return out


@router.get("/reports/{report_id}/export")
def export_report(report_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rep = db.get(m.Report, report_id)
    if rep is None:
        raise HTTPException(404, "Report not found")
    load_case_for(user, db, rep.case_id)
    audit.record(db, rep.case_id, user.username, user.role, "report_exported", {"report_id": rep.id})
    db.commit()
    return report_full(db, rep)


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=800)


@router.post("/cases/{case_id}/ask")
def ask(case_id: str, body: AskIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    from app.ai.copilot import ask as copilot_ask

    case = load_case_for(user, db, case_id)
    out = copilot_ask(db, case, body.question, user)
    db.commit()
    return out


@router.post("/cases/{case_id}/classify")
def classify(case_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    from app.ai.copilot import classify as ai_classify

    case = load_case_for(user, db, case_id)
    out = ai_classify(db, case, user)
    db.commit()
    return out


def report_brief(r: m.Report) -> dict:
    return {"id": r.id, "case_id": r.case_id, "version": r.version, "status": r.status, "generator": r.generator,
            "claims_total": r.claims_total, "claims_supported": r.claims_supported, "claims_flagged": r.claims_flagged,
            "hallucination_rate": r.hallucination_rate, "confidence": r.confidence, "review_status": r.review_status,
            "created_at": r.created_at.isoformat() + "Z", "cost_usd": (r.metrics or {}).get("cost_usd"), "trace_id": r.trace_id}


def report_full(db: Session, r: m.Report) -> dict:
    from app.telemetry import trace_url

    run = db.get(m.AIRun, r.run_id)
    snap = (run.snapshot or {}).get("records", {}) if run else {}
    cited = sorted({c for s in r.sections for cl in s["claims"] for c in cl.get("citations", [])} |
                   {c for a in (r.recommended_actions or []) for c in a.get("citations", [])})
    return {**report_brief(r), "sections": r.sections, "recommended_actions": r.recommended_actions, "metrics": r.metrics,
            "snapshot_hash": r.snapshot_hash, "review": r.review, "trace_url": trace_url(r.trace_id),
            "records": {k: snap[k] for k in cited if k in snap},
            "run": {"id": run.id, "status": run.status, "steps": run.steps, "tool_log": run.tool_log, "models": run.models,
                    "prompt_versions": run.prompt_versions, "ruleset_version": run.ruleset_version, "input_tokens": run.input_tokens,
                    "output_tokens": run.output_tokens, "cost_usd": run.cost_usd, "latency_ms": run.latency_ms,
                    "started_at": run.started_at.isoformat() + "Z"} if run else None}
