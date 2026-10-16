"""LangGraph investigation pipeline.

    gather [D] → explore [Gemini + fixed tools] → evidence [Gemini reads → D reconciles]
      → draft [Gemini Pro | facts-only fallback] → validate [D]
      → (retry draft once with validator feedback) → judge [Gemini] → finalize [D, persist, audit]

The run ends in a durable "awaiting human review" state stored in the database (not an in-memory
interrupt), so a reviewer can act hours later on any Cloud Run instance.
"""
from __future__ import annotations

import json
import operator
import time
import uuid
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.ai import facts_report, prompts, tools, validator
from app.ai.evidence import analyse_item
from app.ai.llm import Gateway, get_gateway
from app.ai.schemas import SECTION_TITLES, ExplorePlan, JudgeResult, ReportDraft
from app.ai.snapshot import build_snapshot, referenced_records, snapshot_json
from app.services.investigation import build_context
from app.telemetry import current_trace_id, span

MAX_EXPLORE_ROUNDS = 2
MAX_DRAFT_ATTEMPTS = 2
HALLUCINATION_CODES = {"invalid_citation", "invented_id", "number_mismatch", "time_mismatch", "missing_citation"}


class State(TypedDict, total=False):
    case_id: str
    run_id: str
    snapshot: dict
    extra_records: dict
    draft: dict
    generator: str
    attempts: int
    feedback: str
    validation: dict
    verdicts: dict
    judge_status: str
    report_id: str
    steps: Annotated[list, operator.add]
    tool_log: Annotated[list, operator.add]
    notes: Annotated[list, operator.add]


def _step(node: str, status: str, t0: float, **detail) -> list[dict]:
    return [{"node": node, "status": status, "ms": int((time.perf_counter() - t0) * 1000), **detail}]


def build_graph(db: Session, case: m.DisputeCase, gw: Gateway, actor: str):
    def gather(state: State) -> dict:
        t0 = time.perf_counter()
        with span("investigation.gather", case_id=case.id):
            ctx = build_context(db, case, persist_flags=True)
            snap = build_snapshot(ctx, {**referenced_records(db, ctx), **state.get("extra_records", {})})
        return {"snapshot": snap, "steps": _step("gather", "ok", t0, records=len(snap["records"]), snapshot_hash=snap["hash"][:12])}

    def explore(state: State) -> dict:
        t0 = time.perf_counter()
        if not gw.available():
            return {"steps": _step("explore", "skipped", t0, reason="AI unavailable — no agent exploration")}
        snap = state["snapshot"]
        extra: dict = dict(state.get("extra_records", {}))
        logs: list[dict] = []
        for rnd in range(MAX_EXPLORE_ROUNDS):
            compact = {k: v for k, v in snap["records"].items() if v.get("type") in ("account", "transaction", "risk_signal", "device", "case")}
            contents = [f"{prompts.EXPLORE_INSTRUCTIONS}\n\nSNAPSHOT (JSON):\n{json.dumps(compact, ensure_ascii=False, default=str)}\n"
                        f"Tool calls already made: {json.dumps([{'tool': l['tool'], 'target_id': l['target_id']} for l in logs])}"]
            res = gw.generate(node="explore", prompt_version=prompts.EXPLORE_V, contents=contents, schema=ExplorePlan, tier="fast",
                              system=prompts.GROUND_RULES, case_id=case.id, run_id=state["run_id"], db=db)
            if not res.ok:
                return {"extra_records": extra, "tool_log": logs, "steps": _step("explore", res.status, t0, rounds=rnd)}
            plan: ExplorePlan = res.data
            if plan.done or not plan.calls:
                break
            for call in plan.calls[:3]:
                with span("agent.tool", tool=call.tool.value, target=call.target_id):
                    new, log = tools.run(db, case, call, snap["records"])
                log["round"] = rnd + 1
                logs.append(log)
                extra.update(new)
                snap["records"].update(new)
        if extra:
            ctx = build_context(db, case)
            snap = build_snapshot(ctx, {**referenced_records(db, ctx), **extra})
        return {"snapshot": snap, "extra_records": extra, "tool_log": logs,
                "steps": _step("explore", "ok", t0, tool_calls=len(logs), new_records=len(extra))}

    def evidence(state: State) -> dict:
        t0 = time.perf_counter()
        items = db.scalars(select(m.EvidenceItem).where(m.EvidenceItem.case_id == case.id,
                                                        m.EvidenceItem.analysis_status != "analysed")).all()
        if not items:
            return {"steps": _step("evidence", "ok", t0, analysed=0)}
        if not gw.available():
            for it in items:
                it.analysis_note = "Not analysed — AI is not configured for this environment"
            db.flush()
            return {"steps": _step("evidence", "skipped", t0, not_analysed=len(items)),
                    "notes": [f"{len(items)} evidence item(s) not analysed: AI unavailable"]}
        done = 0
        for it in items:
            r = analyse_item(db, it, gw, actor="system", run_id=state["run_id"])
            done += r["status"] == "analysed"
        ctx = build_context(db, case)
        snap = build_snapshot(ctx, {**referenced_records(db, ctx), **state.get("extra_records", {})})
        return {"snapshot": snap, "steps": _step("evidence", "ok", t0, analysed=done, not_analysed=len(items) - done)}

    def draft(state: State) -> dict:
        t0 = time.perf_counter()
        attempts = state.get("attempts", 0) + 1
        snap = state["snapshot"]
        if gw.available():
            contents = [f"{prompts.REPORT_INSTRUCTIONS}\n\nEVIDENCE SNAPSHOT (JSON, the only allowed source):\n{snapshot_json(snap)}"]
            if state.get("feedback"):
                contents.append("Your previous draft failed automatic checks. Fix every item below; drop a claim if no record supports it:\n"
                                + state["feedback"])
            res = gw.generate(node="draft_report", prompt_version=prompts.REPORT_V, contents=contents, schema=ReportDraft, tier="pro",
                              system=prompts.GROUND_RULES, case_id=case.id, run_id=state["run_id"], temperature=0.2, db=db)
            if res.ok:
                d = res.data.model_dump(mode="json")
                return {"draft": d, "generator": res.model, "attempts": attempts, "steps": _step("draft", "ok", t0, attempt=attempts, model=res.model)}
            if state.get("draft") and state.get("generator") not in (None, "deterministic"):
                # keep the earlier AI draft; it will be finalised with its flags visible
                return {"attempts": attempts, "steps": _step("draft", res.status, t0, attempt=attempts, kept_previous=True)}
            note = f"AI drafting unavailable ({res.not_analysed_reason}); facts-only report generated"
        else:
            note = "AI unavailable; facts-only report generated"
        return {"draft": facts_report.build(snap), "generator": "deterministic", "attempts": attempts,
                "steps": _step("draft", "fallback", t0, attempt=attempts), "notes": [note]}

    def validate(state: State) -> dict:
        t0 = time.perf_counter()
        v = validator.validate(state["draft"], state["snapshot"]["records"])
        return {"validation": v, "feedback": validator.feedback(v),
                "steps": _step("validate", "passed" if v["passed"] else "flags", t0, claims=v["claims_total"], errors=v["claims_with_errors"])}

    def route(state: State) -> str:
        v = state["validation"]
        if not v["passed"] and state.get("generator") != "deterministic" and state.get("attempts", 0) < MAX_DRAFT_ATTEMPTS:
            return "draft"
        return "judge"

    def judge(state: State) -> dict:
        t0 = time.perf_counter()
        claims = state["validation"]["claims"]
        if state.get("generator") == "deterministic":
            return {"verdicts": {c["id"]: {"verdict": "system_generated", "reason": "generated from records by code"} for c in claims},
                    "judge_status": "not_needed", "steps": _step("judge", "skipped", t0, reason="facts-only report")}
        if not gw.available():
            return {"verdicts": {}, "judge_status": "unavailable", "steps": _step("judge", "skipped", t0)}
        recs = state["snapshot"]["records"]
        cited = sorted({cid for c in claims for cid in c.get("citations", []) if cid in recs})
        payload = [{"claim_id": c["id"], "text": c["text"], "basis": c["basis"], "citations": c["citations"]} for c in claims]
        contents = [f"{prompts.JUDGE_INSTRUCTIONS}\n\nCLAIMS:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
                    f"CITED RECORDS:\n{snapshot_json(state['snapshot'], cited)}"]
        res = gw.generate(node="judge", prompt_version=prompts.JUDGE_V, contents=contents, schema=JudgeResult, tier="fast",
                          system=prompts.GROUND_RULES, case_id=case.id, run_id=state["run_id"], temperature=0.0, db=db)
        if not res.ok:
            return {"verdicts": {}, "judge_status": res.status, "steps": _step("judge", res.status, t0)}
        jr: JudgeResult = res.data
        verdicts = {v.claim_id: {"verdict": v.verdict.value, "reason": v.reason} for v in jr.verdicts}
        return {"verdicts": verdicts, "judge_status": "ok", "steps": _step("judge", "ok", t0, judged=len(verdicts), model=res.model)}

    def finalize(state: State) -> dict:
        t0 = time.perf_counter()
        report = persist_report(db, case, state, actor)
        return {"report_id": report.id, "steps": _step("finalize", "ok", t0, report_id=report.id, report_status=report.status)}

    g = StateGraph(State)
    for name, fn in (("gather", gather), ("explore", explore), ("evidence", evidence), ("draft", draft), ("validate", validate),
                     ("judge", judge), ("finalize", finalize)):
        g.add_node(name, fn)
    g.set_entry_point("gather")
    g.add_edge("gather", "explore")
    g.add_edge("explore", "evidence")
    g.add_edge("evidence", "draft")
    g.add_edge("draft", "validate")
    g.add_conditional_edges("validate", route, {"draft": "draft", "judge": "judge"})
    g.add_edge("judge", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


def score_claims(claims: list[dict], verdicts: dict, judge_status: str) -> tuple[list[dict], dict]:
    out = []
    counts = {"supported": 0, "partial": 0, "unsupported": 0, "contradicted": 0, "unjudged": 0, "system_generated": 0}
    hallucinated = flagged = 0
    for c in claims:
        v = verdicts.get(c["id"], {"verdict": "unjudged", "reason": "judge unavailable" if judge_status != "ok" else "not returned"})
        verdict = v["verdict"]
        counts[verdict] = counts.get(verdict, 0) + 1
        codes = {i["code"] for i in c["issues"] if i["severity"] == "error"}
        is_h = bool(codes & HALLUCINATION_CODES) or verdict in ("unsupported", "contradicted")
        is_f = bool(codes) or verdict in ("unsupported", "contradicted")
        hallucinated += is_h
        flagged += is_f
        out.append({**c, "verdict": verdict, "verdict_reason": v.get("reason"), "hallucination": is_h, "flagged": is_f})
    n = len(claims) or 1
    supported = sum(1 for c in out if not c["flagged"] and c["verdict"] in ("supported", "system_generated"))
    partial = sum(1 for c in out if not c["flagged"] and c["verdict"] == "partial")
    unjudged_ok = sum(1 for c in out if not c["flagged"] and c["verdict"] == "unjudged")
    metrics = {
        "claims_total": len(claims), "claims_supported": supported, "claims_partial": partial, "claims_flagged": flagged,
        "claims_unjudged": unjudged_ok, "hallucinated_claims": hallucinated, "verdicts": counts,
        "hallucination_rate": round(hallucinated / n, 4),
        "confidence": round((supported + 0.5 * partial) / n, 4),
        "confidence_note": "Share of claims that passed deterministic checks and were judged supported (partial counts half). "
                           "Unjudged claims do not count as supported.",
        "by_basis": {b: sum(1 for c in out if c.get("basis") == b) for b in ("verified", "derived", "inferred", "unknown")},
    }
    return out, metrics


def persist_report(db: Session, case: m.DisputeCase, state: State, actor: str) -> m.Report:
    v = state["validation"]
    claims, metrics = score_claims(v["claims"], state.get("verdicts", {}), state.get("judge_status", "unavailable"))
    generator = state.get("generator", "deterministic")
    total = metrics["claims_total"] or 1
    if generator == "deterministic":
        status = "facts_only"
    elif metrics["claims_flagged"] == 0 and state.get("judge_status") == "ok":
        status = "verified"
    elif metrics["claims_flagged"] / total <= 0.2:
        status = "partially_verified"
    else:
        status = "unverified"
    sections = []
    for key, title in SECTION_TITLES.items():
        sections.append({"key": key, "title": title, "claims": [c for c in claims if c["section"] == key]})
    version = (db.scalar(select(func.max(m.Report.version)).where(m.Report.case_id == case.id)) or 0) + 1
    calls = db.scalars(select(m.AICall).where(m.AICall.run_id == state["run_id"])).all()
    metrics.update({
        "validation_passed": v["passed"], "missing_sections": v["missing_sections"], "action_issues": v["action_issues"],
        "draft_attempts": state.get("attempts", 1), "judge_status": state.get("judge_status"),
        "ai_calls": len(calls), "input_tokens": sum(c.input_tokens for c in calls), "output_tokens": sum(c.output_tokens + c.thinking_tokens for c in calls),
        "cost_usd": round(sum(c.cost_usd for c in calls), 6), "ai_latency_ms": sum(c.latency_ms for c in calls),
        "tool_calls": len(state.get("tool_log", [])), "notes": state.get("notes", []),
    })
    rep = m.Report(id="RPT-" + uuid.uuid4().hex[:8].upper(), case_id=case.id, run_id=state["run_id"], version=version, status=status,
                   generator=generator, sections=sections, recommended_actions=state["draft"].get("recommended_actions", []),
                   metrics=metrics, claims_total=metrics["claims_total"], claims_supported=metrics["claims_supported"],
                   claims_flagged=metrics["claims_flagged"], hallucination_rate=metrics["hallucination_rate"],
                   confidence=metrics["confidence"], snapshot_hash=state["snapshot"]["hash"], trace_id=current_trace_id())
    db.add(rep)
    _recommend_holds(db, case, state["snapshot"])
    db.flush()
    audit.record(db, case.id, actor, "investigator" if actor != "system" else "system", "report_generated",
                 {"report_id": rep.id, "version": version, "status": status, "generator": generator,
                  "claims": metrics["claims_total"], "flagged": metrics["claims_flagged"], "snapshot_hash": rep.snapshot_hash,
                  "cost_usd": metrics["cost_usd"]})
    return rep


def _recommend_holds(db: Session, case: m.DisputeCase, snap: dict) -> None:
    """Deterministic hold recommendations from attribution (never applied without investigator approval)."""
    existing = {h.account_id for h in db.scalars(select(m.Hold).where(m.Hold.case_id == case.id)).all()}
    for rid, r in snap["records"].items():
        if r.get("type") != "hold_candidate" or r["account"] in existing or not r.get("max_minor"):
            continue
        db.add(m.Hold(case_id=case.id, account_id=r["account"], amount_minor=r["max_minor"], currency=case.disputed_txn.currency,
                      basis={"range": r["range"], "min_minor": r["min_minor"], "max_minor": r["max_minor"],
                             "citations": [rid, f"ATTR-{r['account']}"], "method": "attribution upper bound, capped by balance"},
                      status="recommended", recommended_by="system (attribution)"))


def run_investigation(db: Session, case: m.DisputeCase, actor: str = "system", gateway: Gateway | None = None) -> m.Report:
    gw = gateway or get_gateway()
    run_id = "RUN-" + uuid.uuid4().hex[:10].upper()
    with span("investigation.run", case_id=case.id, run_id=run_id) as sp:
        run = m.AIRun(id=run_id, case_id=case.id, kind="investigation", status="running", trace_id=current_trace_id(), requested_by=actor,
                      prompt_versions={"report": prompts.REPORT_V, "judge": prompts.JUDGE_V, "explore": prompts.EXPLORE_V,
                                       "evidence": prompts.EVIDENCE_V})
        db.add(run)
        db.flush()
        t0 = time.perf_counter()
        graph = build_graph(db, case, gw, actor)
        try:
            final: dict[str, Any] = graph.invoke({"case_id": case.id, "run_id": run_id, "attempts": 0, "extra_records": {},
                                                  "steps": [], "tool_log": [], "notes": []})
        except Exception as exc:
            run.status, run.error, run.finished_at = "failed", f"{type(exc).__name__}: {exc}"[:1000], m.utcnow()
            db.flush()
            raise
        calls = db.scalars(select(m.AICall).where(m.AICall.run_id == run_id)).all()
        rep = db.get(m.Report, final["report_id"])
        run.status = "awaiting_review"
        run.finished_at = m.utcnow()
        run.snapshot, run.snapshot_hash = final["snapshot"], final["snapshot"]["hash"]
        run.ruleset_version = final["snapshot"].get("ruleset_version")
        run.tool_log, run.steps = final.get("tool_log", []), final.get("steps", [])
        run.models = sorted({c.model for c in calls if c.status == "ok"})
        run.input_tokens = sum(c.input_tokens for c in calls)
        run.output_tokens = sum(c.output_tokens + c.thinking_tokens for c in calls)
        run.cost_usd = round(sum(c.cost_usd for c in calls), 6)
        run.latency_ms = int((time.perf_counter() - t0) * 1000)
        sp.set_attribute("report.status", rep.status)
        db.flush()
        return rep
