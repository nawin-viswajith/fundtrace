import statistics
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.ai.pricing import PRICE_SOURCE, PRICE_TABLE_VERSION, price_for, table
from app.config import get_settings
from app.db import get_db
from app.security import current_user, require_role
from app.services.investigation import rule_catalogue
from app.services.rules import CATALOGUE_BY_ID

router = APIRouter(prefix="/api", tags=["ops"])


def _pct(vals: list[int], p: float) -> int | None:
    if not vals:
        return None
    vals = sorted(vals)
    k = max(0, min(len(vals) - 1, int(round(p * (len(vals) - 1)))))
    return vals[k]


@router.get("/ops/metrics")
def ops_metrics(days: int = 14, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    since = m.utcnow() - timedelta(days=max(1, min(days, 90)))
    calls = db.scalars(select(m.AICall).where(m.AICall.created_at >= since)).all()
    reports = db.scalars(select(m.Report).where(m.Report.created_at >= since).order_by(m.Report.created_at)).all()
    by_node: dict[str, list[m.AICall]] = defaultdict(list)
    for c in calls:
        by_node[c.node].append(c)
    nodes = []
    for node, cs in sorted(by_node.items()):
        ok = [c for c in cs if c.status == "ok"]
        lat = [c.latency_ms for c in ok]
        nodes.append({"node": node, "calls": len(cs), "ok": len(ok),
                      "errors": {s: sum(1 for c in cs if c.status == s) for s in ("error", "timeout", "invalid", "budget", "disabled")},
                      "p50_ms": _pct(lat, 0.5), "p95_ms": _pct(lat, 0.95), "input_tokens": sum(c.input_tokens for c in cs),
                      "output_tokens": sum(c.output_tokens + c.thinking_tokens for c in cs), "cost_usd": round(sum(c.cost_usd for c in cs), 6),
                      "models": sorted({c.model for c in ok})})
    per_day: dict[str, dict] = defaultdict(lambda: {"cost_usd": 0.0, "calls": 0, "errors": 0})
    for c in calls:
        d = per_day[c.created_at.date().isoformat()]
        d["cost_usd"] = round(d["cost_usd"] + c.cost_usd, 6)
        d["calls"] += 1
        d["errors"] += c.status not in ("ok",)
    per_case: dict[str, float] = defaultdict(float)
    for c in calls:
        if c.case_id:
            per_case[c.case_id] += c.cost_usd
    ai_reports = [r for r in reports if r.generator != "deterministic"]
    verdicts: dict[str, int] = defaultdict(int)
    for r in reports:
        for k, v in ((r.metrics or {}).get("verdicts") or {}).items():
            verdicts[k] += v
    total_calls = len(calls)
    ok_calls = sum(1 for c in calls if c.status == "ok")
    latest_eval = db.scalar(select(m.EvalRun).where(m.EvalRun.kind != "ground_truth").order_by(m.EvalRun.id.desc()).limit(1))
    s = get_settings()
    return {
        "window_days": days,
        "llm": {"enabled": s.llm_enabled, "configured": bool(s.gcp_project), "fast_models": s.fast_models, "pro_models": s.pro_models,
                "location": s.gemini_location, "daily_budget_usd": s.llm_daily_budget_usd, "case_budget_usd": s.llm_case_budget_usd},
        "totals": {"calls": total_calls, "ok": ok_calls, "error_rate": round(1 - ok_calls / total_calls, 4) if total_calls else None,
                   "cost_usd": round(sum(c.cost_usd for c in calls), 6), "input_tokens": sum(c.input_tokens for c in calls),
                   "output_tokens": sum(c.output_tokens + c.thinking_tokens for c in calls),
                   "reports": len(reports), "ai_reports": len(ai_reports), "facts_only_reports": len(reports) - len(ai_reports),
                   "mean_cost_per_case_usd": round(statistics.mean(per_case.values()), 6) if per_case else None},
        "nodes": nodes,
        "per_day": [{"day": k, **v} for k, v in sorted(per_day.items())],
        "per_case": [{"case_id": k, "cost_usd": round(v, 6)} for k, v in sorted(per_case.items(), key=lambda x: -x[1])][:20],
        "quality": {
            "hallucination_trend": [{"report_id": r.id, "case_id": r.case_id, "created_at": r.created_at.isoformat() + "Z", "generator": r.generator,
                                     "hallucination_rate": r.hallucination_rate, "confidence": r.confidence, "claims": r.claims_total,
                                     "flagged": r.claims_flagged, "status": r.status} for r in reports],
            "mean_hallucination_rate": round(statistics.mean([r.hallucination_rate for r in ai_reports if r.hallucination_rate is not None]), 4)
            if ai_reports else None,
            "mean_confidence": round(statistics.mean([r.confidence for r in ai_reports if r.confidence is not None]), 4) if ai_reports else None,
            "verdicts": dict(verdicts),
            "report_status": {st: sum(1 for r in reports if r.status == st) for st in ("verified", "partially_verified", "unverified", "facts_only")},
        },
        "pricing": {"version": PRICE_TABLE_VERSION, "source": PRICE_SOURCE, "table": table(),
                    "unpriced_models": sorted({c.model for c in calls if c.status == "ok" and price_for(c.model) is None}),
                    "note": "Calls to unpriced models are counted with cost 0 until LLM_PRICE_OVERRIDES adds them."},
        "latest_eval": {"id": latest_eval.id, "started_at": latest_eval.started_at.isoformat() + "Z", "metrics": latest_eval.metrics}
        if latest_eval else None,
    }


@router.get("/ops/calls")
def ops_calls(limit: int = 100, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(m.AICall).order_by(m.AICall.id.desc()).limit(max(1, min(limit, 500)))).all()
    from app.telemetry import trace_url

    return {"calls": [{"id": c.id, "run_id": c.run_id, "case_id": c.case_id, "node": c.node, "model": c.model, "prompt_version": c.prompt_version,
                       "status": c.status, "input_tokens": c.input_tokens, "output_tokens": c.output_tokens, "thinking_tokens": c.thinking_tokens,
                       "cost_usd": c.cost_usd, "latency_ms": c.latency_ms, "avg_logprob": c.avg_logprob, "trace_id": c.trace_id,
                       "trace_url": trace_url(c.trace_id), "error": c.error, "created_at": c.created_at.isoformat() + "Z"} for c in rows]}


@router.get("/ops/evals")
def ops_evals(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(m.EvalRun).where(m.EvalRun.kind != "ground_truth").order_by(m.EvalRun.id.desc()).limit(10)).all()
    return {"runs": [{"id": r.id, "kind": r.kind, "started_at": r.started_at.isoformat() + "Z", "metrics": r.metrics, "details": r.details}
                     for r in rows]}


@router.post("/ops/evals/run")
def ops_eval_run(include_classification: bool = False, user: m.User = Depends(require_role("supervisor", "admin")),
                 db: Session = Depends(get_db)):
    from app.eval.harness import run_and_store

    run = run_and_store(db, include_classification=include_classification)
    audit.record(db, None, user.username, user.role, "evaluation_run", {"eval_run_id": run.id})
    db.commit()
    return {"id": run.id, "metrics": run.metrics, "details": run.details}


# ---------------------------------------------------------------------------- rules

@router.get("/rules")
def rules(user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    return {"rules": rule_catalogue(db)}


class RuleUpdate(BaseModel):
    params: dict = Field(default_factory=dict)
    enabled: bool = True
    change_note: str = Field(min_length=5, max_length=255)


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, body: RuleUpdate, user: m.User = Depends(require_role("supervisor", "admin")), db: Session = Depends(get_db)):
    rd = CATALOGUE_BY_ID.get(rule_id)
    if rd is None:
        raise HTTPException(404, "Unknown rule")
    unknown = set(body.params) - set(rd.default_params)
    if unknown:
        raise HTTPException(422, f"Unknown parameters: {sorted(unknown)}")
    clean = {}
    for k, v in body.params.items():
        default = rd.default_params[k]
        if isinstance(default, bool) or not isinstance(v, (int, float)) or isinstance(v, bool):
            raise HTTPException(422, f"{k} must be a number")
        if v < 0 or (isinstance(default, float) and default <= 1 and v > 1):
            raise HTTPException(422, f"{k} is out of range")
        clean[k] = type(default)(v)
    last = db.scalar(select(func.max(m.RuleVersion.version)).where(m.RuleVersion.rule_id == rule_id)) or 1
    rv = m.RuleVersion(rule_id=rule_id, version=last + 1, params={**rd.default_params, **clean}, enabled=body.enabled,
                       change_note=body.change_note, created_by=user.username)
    db.add(rv)
    db.flush()
    audit.record(db, None, user.username, user.role, "rule_changed", {"rule_id": rule_id, "version": rv.version, "params": rv.params,
                                                                     "enabled": rv.enabled, "note": body.change_note})
    from app.seed.loader import refresh_case_assessments

    refresh_case_assessments(db)
    db.commit()
    return {"rule_id": rule_id, "version": rv.version, "params": rv.params, "enabled": rv.enabled}


@router.get("/rules/{rule_id}/history")
def rule_history(rule_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(m.RuleVersion).where(m.RuleVersion.rule_id == rule_id).order_by(m.RuleVersion.version.desc())).all()
    return {"versions": [{"version": r.version, "params": r.params, "enabled": r.enabled, "note": r.change_note, "by": r.created_by,
                          "at": r.created_at.isoformat() + "Z"} for r in rows]}


# ---------------------------------------------------------------------------- network, admin, health

@router.get("/network/rings")
def rings(min_cases: int = 2, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    from app.services.network import mule_rings

    out = mule_rings(db, max(2, min(min_cases, 10)))
    if user.role == "investigator":  # investigators see ring structure only for cases they can open
        from app.security import can_access_case

        for r in out["rings"]:
            r["cases"] = [c if can_access_case(user, db.get(m.DisputeCase, c)) else "restricted" for c in r["cases"]]
    return out


@router.post("/admin/reset-demo")
def reset_demo(user: m.User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    from app.seed.loader import reset_demo as do_reset

    info = do_reset(db)
    audit.record(db, None, user.username, user.role, "demo_reset", {k: v for k, v in info.items() if k != "truth"})
    db.commit()
    return {k: v for k, v in info.items() if k != "truth"}


@router.post("/admin/retention/run")
def retention_run(dry_run: bool = True, user: m.User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    from app.services.retention import run_retention

    out = run_retention(db, user, dry_run=dry_run)
    db.commit()
    return out


# ---------------------------------------------------------------------------- users, MFA and security status

@router.get("/admin/users")
def admin_users(user: m.User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    from app.services.mfa import required_for

    rows = db.scalars(select(m.User).order_by(m.User.username)).all()
    return {"users": [{"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role, "is_active": u.is_active,
                       "mfa_enabled": bool(u.mfa_enabled), "mfa_required": required_for(u),
                       "recovery_codes_left": len(u.mfa_recovery or []) if u.mfa_enabled else None} for u in rows]}


class MfaResetIn(BaseModel):
    reason: str = Field(min_length=10, max_length=255)


@router.post("/admin/users/{user_id}/mfa/reset")
def admin_mfa_reset(user_id: int, body: MfaResetIn, user: m.User = Depends(require_role("admin")), db: Session = Depends(get_db)):
    """For a lost authenticator: removes the user's MFA so they can enrol again at next sign-in. Audited."""
    from app.services.mfa import reset

    target = db.get(m.User, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    if target.id == user.id:
        raise HTTPException(403, "Ask another admin to reset your own MFA")
    reset(target)
    audit.record(db, None, user.username, user.role, "mfa_reset_by_admin", {"user": target.username, "reason": body.reason})
    db.commit()
    return {"ok": True}


@router.get("/admin/security")
def security_status(user: m.User = Depends(require_role("supervisor", "admin")), db: Session = Depends(get_db)):
    from app import crypto
    from app.services.dlp import LABELS, MASK_TYPES, backend

    s = get_settings()
    users = db.scalars(select(m.User)).all()
    return {
        "encryption": crypto.status(),
        "dlp": {"backend": backend(), "detects": [LABELS[k] for k in LABELS], "masked_in_notes_and_llm_input": sorted(LABELS[k] for k in MASK_TYPES)},
        "mfa": {"required_roles": sorted(s.mfa_roles), "enrolled": sum(1 for u in users if u.mfa_enabled), "users": len(users)},
        "firebase_sign_in": bool(s.firebase_project_id and s.firebase_api_key),
        "pubsub_ingest": bool(s.pubsub_push_audience),
    }


@router.get("/healthz")
def healthz(db: Session = Depends(get_db)):
    db.execute(select(1))
    s = get_settings()
    return {"ok": True, "environment": s.environment, "llm_configured": bool(s.gcp_project and s.llm_enabled)}
