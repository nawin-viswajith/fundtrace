"""AI hypotheses about where the disputed money went, and "Ask the ledger".

"Gemini proposes, the ledger proves": Gemini (or, when it is unavailable or over budget, the fixed
typology detectors) proposes ideas in the small claim language defined in
`app.services.hypothesis_check`. Every idea is then checked by deterministic code against the same
facts the rest of the workspace uses. Gemini never states an amount as settled; only the checker's
verdict and figures, written by code, are shown as proven or possible.

The latest result for a case is persisted on an `AIRun` (kind="hypotheses") so reopening the tab does
not re-spend the AI budget; "Run again" starts a fresh call.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.ai import prompts
from app.ai.llm import Gateway, get_gateway
from app.ai.schemas import HypothesisSet, LedgerQuestion
from app.ai.snapshot import build_snapshot, referenced_records, snapshot_json
from app.services import hypothesis_check as hc
from app.services.investigation import build_context

MAX_HYPOTHESES = 6
MAX_CHECKS_PER_QUESTION = 3


def _ledger(db: Session, case: m.DisputeCase) -> tuple[hc.Ledger, dict]:
    ctx = build_context(db, case)
    snap = build_snapshot(ctx, referenced_records(db, ctx))
    return hc.Ledger(db, ctx, known_ids=set(snap["records"])), snap


def _system_fallback(db: Session, case: m.DisputeCase, run: m.AIRun, lg: hc.Ledger, reason: str | None) -> dict:
    hyps = [hc.check_hypothesis(h, lg) for h in hc.system_hypotheses(lg, MAX_HYPOTHESES)]
    run.status, run.finished_at = "ai_unavailable", m.utcnow()
    run.snapshot = {"hypotheses": hyps, "ai_available": False, "reason": reason}
    db.flush()
    return {"status": "ai_unavailable", "run_id": run.id, "reason": reason, "hypotheses": hyps, "counts": hc.counts(hyps)}


def run(db: Session, case: m.DisputeCase, user: m.User, gateway: Gateway | None = None) -> dict:
    """Run the AI hypothesis proposer (or the system fallback) and persist the result on a new AIRun."""
    gw = gateway or get_gateway()
    lg, snap = _ledger(db, case)
    run_id = "RUN-" + uuid.uuid4().hex[:10].upper()
    ai_run = m.AIRun(id=run_id, case_id=case.id, kind="hypotheses", status="running", requested_by=user.username,
                     prompt_versions={"hypotheses": prompts.HYPOTHESES_V})
    db.add(ai_run)
    db.flush()
    if not gw.available():
        out = _system_fallback(db, case, ai_run, lg, "AI is not configured for this environment")
        audit.record(db, case.id, user.username, user.role, "hypotheses_run", {"run_id": ai_run.id, "status": out["status"]})
        return out
    contents = [f"{prompts.HYPOTHESES_INSTRUCTIONS}\n\nEVIDENCE SNAPSHOT (JSON):\n{snapshot_json(snap)}"]
    res = gw.generate(node="hypotheses", prompt_version=prompts.HYPOTHESES_V, contents=contents, schema=HypothesisSet, tier="fast",
                      system=prompts.GROUND_RULES, case_id=case.id, run_id=ai_run.id, db=db)
    if not res.ok:
        out = _system_fallback(db, case, ai_run, lg, res.not_analysed_reason)
        audit.record(db, case.id, user.username, user.role, "hypotheses_run", {"run_id": ai_run.id, "status": out["status"]})
        return out
    data: HypothesisSet = res.data
    hyps = [hc.check_hypothesis(h.model_dump(), lg) for h in data.hypotheses[:MAX_HYPOTHESES]]
    ai_run.status, ai_run.models, ai_run.input_tokens = "ok", [res.model] if res.model else [], res.input_tokens
    ai_run.output_tokens, ai_run.cost_usd, ai_run.latency_ms, ai_run.finished_at = res.output_tokens, res.cost_usd, res.latency_ms, m.utcnow()
    ai_run.snapshot_hash = snap["hash"]
    ai_run.snapshot = {"hypotheses": hyps, "ai_available": True, "model": res.model}
    db.flush()
    audit.record(db, case.id, user.username, user.role, "hypotheses_run",
                 {"run_id": ai_run.id, "status": "ok", "model": res.model, "counts": hc.counts(hyps)})
    return {"status": "ok", "run_id": ai_run.id, "model": res.model, "cost_usd": res.cost_usd, "hypotheses": hyps, "counts": hc.counts(hyps)}


def latest(db: Session, case: m.DisputeCase) -> dict | None:
    """The most recent persisted hypothesis run for this case, without spending anything."""
    # AIRun ids are random (not sortable by creation order); order by when the run started instead.
    r = db.scalar(select(m.AIRun).where(m.AIRun.case_id == case.id, m.AIRun.kind == "hypotheses")
                  .order_by(m.AIRun.started_at.desc()).limit(1))
    if r is None or not r.snapshot:
        return None
    return {"status": r.status, "run_id": r.id, "model": (r.models or [None])[0], "cost_usd": r.cost_usd,
            "hypotheses": r.snapshot.get("hypotheses", []), "counts": hc.counts(r.snapshot.get("hypotheses", [])),
            "ai_available": r.snapshot.get("ai_available", False), "reason": r.snapshot.get("reason"),
            "generated_at": r.finished_at.isoformat() + "Z" if r.finished_at else None}


def ask_ledger(db: Session, case: m.DisputeCase, question: str, user: m.User, gateway: Gateway | None = None) -> dict:
    """"Ask the ledger": Gemini only translates the question into checks; code answers from the records."""
    q = (question or "").strip()
    if not 3 <= len(q) <= 300:
        return {"status": "invalid", "answer": "Please ask a question of 3 to 300 characters.", "checks": []}
    gw = gateway or get_gateway()
    lg, snap = _ledger(db, case)
    if not gw.available():
        audit.record(db, case.id, user.username, user.role, "ask_ledger", {"question_length": len(q), "status": "ai_unavailable"})
        return {"status": "ai_unavailable", "question": q,
                "answer": "AI is not available right now, so this question cannot be translated into a check on the records.", "checks": []}
    contents = [f"{prompts.ASK_LEDGER_INSTRUCTIONS}\n\nEVIDENCE SNAPSHOT (JSON):\n{snapshot_json(snap)}\n\n"
                f"INVESTIGATOR QUESTION: {prompts.fence(q)}"]
    res = gw.generate(node="ask_ledger", prompt_version=prompts.ASK_LEDGER_V, contents=contents, schema=LedgerQuestion, tier="fast",
                      system=prompts.GROUND_RULES, case_id=case.id, db=db)
    if not res.ok:
        audit.record(db, case.id, user.username, user.role, "ask_ledger", {"question_length": len(q), "status": res.status})
        return {"status": "not_analysed", "question": q, "answer": f"Could not translate the question right now ({res.not_analysed_reason}).",
                "checks": []}
    data: LedgerQuestion = res.data
    if data.cannot_express or not data.checks:
        audit.record(db, case.id, user.username, user.role, "ask_ledger", {"question_length": len(q), "status": "cannot_express"})
        return {"status": "cannot_express", "question": q,
                "answer": data.reason or "This question cannot be turned into a check on the records. Try asking about a specific "
                                        "account or payment, for example \"did at least 25,000 reach ACC-100210\".", "checks": []}
    results = [hc.run_check(c.model_dump(), lg) for c in data.checks[:MAX_CHECKS_PER_QUESTION]]
    unknown = [i for r in results for i in (r.get("unknown_ids") or [])]
    verdict = hc.INVENTED if unknown else hc.overall([r["verdict"] for r in results])
    answer = hc.answer_text(verdict, results)
    audit.record(db, case.id, user.username, user.role, "ask_ledger", {"question_length": len(q), "status": "ok", "verdict": verdict})
    return {"status": "ok", "question": q, "verdict": verdict, "answer": answer, "checks": results, "model": res.model,
            "cost_usd": res.cost_usd}
