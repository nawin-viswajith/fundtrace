"""LangGraph investigation pipeline.

    gather [D] → explore [Gemini + fixed tools] → evidence [Gemini reads → D reconciles]
      → draft [Gemini Pro | facts-only fallback] → validate [D]
      → (retry draft once with validator feedback) → judge [Gemini] → finalize [D, persist, audit]

The run ends in a durable "awaiting human review" state stored in the database (not an in-memory
interrupt), so a reviewer can act hours later on any Cloud Run instance.
"""
from __future__ import annotations

import contextvars
import json
import operator
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.ai import facts_report, prompts, tools, validator
from app.ai.evidence import analyse_item
from app.ai.llm import CallBuffer, Gateway, _spend, get_gateway
from app.ai.schemas import SECTION_TITLES, ExplorePlan, JudgeResult, ReportDraft
from app.ai.snapshot import build_snapshot, referenced_records, snapshot_json
from app.config import get_settings
from app.services.investigation import build_context
from app.telemetry import current_trace_id, span

MAX_EXPLORE_ROUNDS = 2
MAX_DRAFT_ATTEMPTS = 2
JUDGE_BATCH = 8  # claims per fact-check call: small calls finish well inside the timeout
JUDGE_WORKERS = 4
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
                                                        m.EvidenceItem.analysis_status != "analysed",
                                                        m.EvidenceItem.retention_status != "deleted")).all()
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
        verdicts, status, detail = judge_claims(db, gw, case.id, state["run_id"], claims, state["snapshot"])
        return {"verdicts": verdicts, "judge_status": status, "steps": _step("judge", status, t0, judged=len(verdicts), **detail)}

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


def judge_claims(db: Session, gw: Gateway, case_id: str, run_id: str | None, claims: list[dict], snapshot: dict) -> tuple[dict, str, dict]:
    """Fact-check claims in small batches, in parallel. One slow or failed batch leaves only its own claims unjudged.

    Returns (verdicts by claim id, status, detail). Status is "ok" when every batch answered, "partial" when some
    did, otherwise the failure status of the first batch (e.g. "timeout").
    """
    if not claims:
        return {}, "ok", {"batches": 0}
    recs = snapshot["records"]
    batches = [claims[i:i + JUDGE_BATCH] for i in range(0, len(claims), JUDGE_BATCH)]
    spend = _spend(case_id, db)

    def call(batch: list[dict]):
        buf = CallBuffer(spend)  # worker threads never touch the request's DB session
        cited = sorted({cid for c in batch for cid in c.get("citations", []) if cid in recs})
        payload = [{"claim_id": c["id"], "text": c["text"], "basis": c["basis"], "citations": c["citations"]} for c in batch]
        contents = [f"{prompts.JUDGE_INSTRUCTIONS}\n\nCLAIMS:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
                    f"CITED RECORDS:\n{snapshot_json(snapshot, cited)}"]
        res = gw.generate(node="judge", prompt_version=prompts.JUDGE_V, contents=contents, schema=JudgeResult, tier="fast",
                          system=prompts.GROUND_RULES, case_id=case_id, run_id=run_id, temperature=0.0, db=buf,
                          timeout_s=get_settings().llm_judge_timeout_seconds)
        return batch, res, buf, True  # (claims, result, recorded calls, counts towards the status)

    def one(batch: list[dict]) -> list:
        first = call(batch)
        if first[1].status != "timeout" or len(batch) < 2:
            return [first]
        # A batch that needs too long is split in half and retried once, in parallel: smaller calls finish in time.
        halves = [batch[: len(batch) // 2], batch[len(batch) // 2:]]
        with ThreadPoolExecutor(max_workers=2) as inner:
            retried = [f.result() for f in [inner.submit(contextvars.copy_context().run, call, h) for h in halves]]
        return [(batch, first[1], first[2], False)] + retried  # keep the timed-out call's cost row; its halves decide

    with ThreadPoolExecutor(max_workers=min(JUDGE_WORKERS, len(batches))) as ex:
        # each worker runs in a copy of this context, so its spans join the current trace
        futures = [ex.submit(contextvars.copy_context().run, one, b) for b in batches]
        results = [r for f in futures for r in f.result()]
    verdicts: dict = {}
    failures: list[str] = []
    models: set[str] = set()
    for batch, res, buf, counts in results:
        for row in buf.rows:
            db.add(row)
        if not counts:
            continue
        if not res.ok:
            failures.append(res.status)
            continue
        models.add(res.model)
        ids = {c["id"] for c in batch}
        for v in res.data.verdicts:
            if v.claim_id in ids:  # a batch may only judge its own claims
                verdicts[v.claim_id] = {"verdict": v.verdict.value, "reason": v.reason}
    db.flush()
    calls = sum(1 for r in results if r[3])
    status = "ok" if not failures else ("partial" if len(failures) < calls else failures[0])
    return verdicts, status, {"batches": len(batches), "calls": calls, "split_after_timeout": len(results) - calls,
                              "batches_failed": len(failures), "failures": failures, "models": sorted(models)}


def report_status(generator: str, flagged: int, total: int, judge_status: str | None) -> str:
    if generator == "deterministic":
        return "facts_only"
    if flagged == 0 and judge_status == "ok":
        return "verified"
    if flagged / (total or 1) <= 0.2:
        return "partially_verified"
    return "unverified"


JUDGE_REASONS = {"timeout": "fact-check timed out", "partial": "fact-check timed out for this batch", "budget": "AI budget limit reached",
                 "unavailable": "AI unavailable", "error": "fact-check failed", "invalid": "fact-check returned an unreadable answer"}


def score_claims(claims: list[dict], verdicts: dict, judge_status: str) -> tuple[list[dict], dict]:
    out = []
    counts = {"supported": 0, "partial": 0, "unsupported": 0, "contradicted": 0, "unjudged": 0, "system_generated": 0}
    hallucinated = flagged = 0
    for c in claims:
        v = verdicts.get(c["id"], {"verdict": "unjudged", "reason": JUDGE_REASONS.get(judge_status, "not returned")})
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
    status = report_status(generator, metrics["claims_flagged"], metrics["claims_total"], state.get("judge_status"))
    if generator == "deterministic":
        # No AI-generated claims: AI confidence and hallucination rate do not apply (shown as "Not analysed").
        metrics["confidence"] = None
        metrics["hallucination_rate"] = None
        metrics["confidence_note"] = "Not applicable: this report was generated from records by code, without AI."
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
    from app.services.investigation import build_context, sync_hold_recommendations

    sync_hold_recommendations(db, case, build_context(db, case)["attribution"])
    db.flush()
    audit.record(db, case.id, actor, "investigator" if actor != "system" else "system", "report_generated",
                 {"report_id": rep.id, "version": version, "status": status, "generator": generator,
                  "claims": metrics["claims_total"], "flagged": metrics["claims_flagged"], "snapshot_hash": rep.snapshot_hash,
                  "cost_usd": metrics["cost_usd"]})
    return rep


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


def rejudge_report(db: Session, report: m.Report, actor: str, role: str, only_unjudged: bool = True,
                   gateway: Gateway | None = None) -> dict:
    """Run only the fact-check again on an existing report, against the exact snapshot it was written from.

    The claims do not change, so verdicts, status and confidence are updated in place; every re-run is kept in
    metrics["judge_runs"] and audited. Other steps need no separate re-run: evidence is analysed per item, and a
    failed draft already falls back to a facts-only report.
    """
    gw = gateway or get_gateway()
    if report.generator == "deterministic":
        return {"ok": False, "message": "This facts-only report was built from records by code; there is nothing to fact-check."}
    run = db.get(m.AIRun, report.run_id)
    if run is None or not run.snapshot:
        return {"ok": False, "message": "The snapshot this report was written from is not available."}
    if not gw.available():
        return {"ok": False, "message": "AI is not available right now, so the fact-check cannot run."}
    claims = [c for s in report.sections for c in s["claims"]]
    targets = [c for c in claims if not only_unjudged or c.get("verdict") == "unjudged"]
    if not targets:
        return {"ok": True, "message": "Every claim already has a fact-check verdict.", "judged": 0}
    new, status, detail = judge_claims(db, gw, report.case_id, report.run_id, targets, run.snapshot)
    verdicts = {c["id"]: {"verdict": c["verdict"], "reason": c.get("verdict_reason")}
                for c in claims if c.get("verdict") not in (None, "unjudged") and c["id"] not in {t["id"] for t in targets}}
    verdicts.update(new)
    overall = "ok" if all(c["id"] in verdicts for c in claims) else ("partial" if verdicts else status)
    scored, counts = score_claims(claims, verdicts, overall)
    by_id = {c["id"]: c for c in scored}
    report.sections = [{**s, "claims": [by_id[c["id"]] for c in s["claims"]]} for s in report.sections]
    history = list((report.metrics or {}).get("judge_runs", [])) + [
        {"at": m.utcnow().isoformat() + "Z", "by": actor, "claims": len(targets), "judged": len(new), "status": status, **detail}]
    report.metrics = {**(report.metrics or {}), **counts, "judge_status": overall, "judge_runs": history}
    report.status = report_status(report.generator, counts["claims_flagged"], counts["claims_total"], overall)
    report.claims_supported, report.claims_flagged = counts["claims_supported"], counts["claims_flagged"]
    report.confidence, report.hallucination_rate = counts["confidence"], counts["hallucination_rate"]
    db.flush()
    audit.record(db, report.case_id, actor, role, "report_rejudged",
                 {"report_id": report.id, "claims": len(targets), "judged": len(new), "status": status,
                  "report_status": report.status, "confidence": report.confidence})
    left = sum(1 for c in scored if c["verdict"] == "unjudged")
    msg = f"Fact-checked {len(new)} of {len(targets)} claims." + (f" {left} still not judged; you can run it again." if left else "")
    return {"ok": True, "message": msg, "judged": len(new), "status": status}
