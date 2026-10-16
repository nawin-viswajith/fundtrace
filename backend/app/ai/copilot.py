"""Case copilot (Q&A) and AI classification — both cited/validated, both optional."""
from __future__ import annotations

import math
import uuid

from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.ai import prompts, validator
from app.ai.llm import get_gateway
from app.ai.schemas import Classification, CopilotAnswer
from app.ai.snapshot import build_snapshot, referenced_records, snapshot_json
from app.services.investigation import build_context
from app.services.scoring import CATEGORIES


def ask(db: Session, case: m.DisputeCase, question: str, user: m.User) -> dict:
    q = (question or "").strip()
    if not 3 <= len(q) <= 800:
        return {"status": "invalid", "message": "Question must be 3–800 characters"}
    gw = get_gateway()
    ctx = build_context(db, case)
    snap = build_snapshot(ctx, referenced_records(db, ctx))
    contents = [f"{prompts.COPILOT_INSTRUCTIONS}\n\nEVIDENCE SNAPSHOT (JSON):\n{snapshot_json(snap)}\n\n"
                f"INVESTIGATOR QUESTION: {prompts.fence(q)}"]
    res = gw.generate(node="copilot", prompt_version=prompts.COPILOT_V, contents=contents, schema=CopilotAnswer, tier="fast",
                      system=prompts.GROUND_RULES, case_id=case.id, run_id=None, db=db)
    audit.record(db, case.id, user.username, user.role, "copilot_question", {"question_length": len(q), "status": res.status})
    if not res.ok:
        return {"status": "not_analysed", "message": f"Not analysed — {res.not_analysed_reason}", "claims": []}
    ans: CopilotAnswer = res.data
    draft = {"sections": [{"key": "known_facts", "claims": [c.model_dump(mode="json") for c in ans.claims]}], "recommended_actions": []}
    v = validator.validate(draft, snap["records"])
    return {"status": "ok", "claims": v["claims"], "insufficient_data": ans.insufficient_data,
            "follow_up_questions": ans.follow_up_questions[:3], "model": res.model, "cost_usd": res.cost_usd,
            "flagged": v["claims_with_errors"], "snapshot_hash": snap["hash"]}


def classify(db: Session, case: m.DisputeCase, user: m.User) -> dict:
    gw = get_gateway()
    contents = [f"{prompts.CLASSIFY_INSTRUCTIONS}\n\nCUSTOMER STATEMENT: {prompts.fence(case.allegation)}"]
    res = gw.generate(node="classify", prompt_version=prompts.CLASSIFY_V, contents=contents, schema=Classification, tier="fast",
                      system=prompts.GROUND_RULES, case_id=case.id, run_id=None, temperature=0.0, db=db)
    run = m.AIRun(id="RUN-" + uuid.uuid4().hex[:10].upper(), case_id=case.id, kind="classification",
                  status="ok" if res.ok else res.status, prompt_versions={"classify": prompts.CLASSIFY_V}, models=[res.model] if res.model else [],
                  input_tokens=res.input_tokens, output_tokens=res.output_tokens, cost_usd=res.cost_usd, latency_ms=res.latency_ms,
                  requested_by=user.username, finished_at=m.utcnow())
    db.add(run)
    if not res.ok:
        db.flush()
        return {"status": "not_analysed", "message": f"Not analysed — {res.not_analysed_reason}"}
    c: Classification = res.data
    # avg_logprobs is the mean per-token log-probability of the whole response: a coarse model-certainty proxy
    token_conf = round(math.exp(res.avg_logprob), 4) if res.avg_logprob is not None else None
    if c.english_translation and case.allegation_language != "en":
        case.allegation_translation = c.english_translation
    run.steps = [{"suggested_category": c.category.value, "rationale": c.rationale, "token_confidence": token_conf}]
    db.flush()
    audit.record(db, case.id, user.username, user.role, "ai_classification", {"suggested": c.category.value, "current": case.category,
                                                                               "token_confidence": token_conf, "run_id": run.id})
    return {"status": "ok", "suggested_category": c.category.value, "label": CATEGORIES[c.category.value], "rationale": c.rationale,
            "current_category": case.category, "agrees": c.category.value == case.category, "detected_language": c.detected_language,
            "translation": c.english_translation, "token_confidence": token_conf, "model": res.model,
            "note": "Suggestion only. The investigator decides whether to change the category."}
