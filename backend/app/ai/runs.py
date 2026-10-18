"""Investigations in the background, with real progress.

A full run (explore, read evidence, draft, fact-check) takes tens of seconds with live Gemini. Holding one HTTP
request open for that long was fragile (proxies and browsers give up) and the progress shown was only a guess.
Now the request creates the run and returns at once; a worker thread runs the pipeline with its own database
session and saves the steps after each one, and the page polls the run. Cloud Run keeps the CPU for the thread
because the service runs with CPU always allocated (see infra/deploy.sh).
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.ai import prompts
from app.db import session_scope
from app.telemetry import current_trace_id

log = logging.getLogger("fundtrace.runs")

STALE_AFTER = timedelta(minutes=15)  # a run still "running" after this was lost (instance stopped); show it as failed


def active_run(db: Session, case_id: str) -> m.AIRun | None:
    """The investigation still running for this case, if any (a second click joins it instead of starting another)."""
    run = db.scalars(select(m.AIRun).where(m.AIRun.case_id == case_id, m.AIRun.kind == "investigation", m.AIRun.status == "running")
                     .order_by(m.AIRun.started_at.desc())).first()
    if run is None or m.utcnow() - run.started_at > STALE_AFTER:
        return None
    return run


def start_background(db: Session, case: m.DisputeCase, actor: str, gateway=None) -> tuple[m.AIRun, threading.Thread | None]:
    """Create the run row, commit it so other instances can see it, and start the worker. Returns the run (and the
    thread, for tests). If a run is already going for this case, that one is returned and nothing new starts."""
    existing = active_run(db, case.id)
    if existing is not None:
        return existing, None
    run = m.AIRun(id="RUN-" + uuid.uuid4().hex[:10].upper(), case_id=case.id, kind="investigation", status="running",
                  trace_id=current_trace_id(), requested_by=actor,
                  prompt_versions={"report": prompts.REPORT_V, "judge": prompts.JUDGE_V}, steps=[])
    db.add(run)
    db.commit()
    t = threading.Thread(target=_work, args=(run.id, case.id, actor, gateway), name=f"investigation-{run.id}", daemon=True)
    t.start()
    return run, t


def _work(run_id: str, case_id: str, actor: str, gateway) -> None:
    from app.ai.investigator import run_investigation

    try:
        with session_scope() as db:
            case = db.get(m.DisputeCase, case_id)

            def publish(run: m.AIRun) -> None:
                db.commit()  # each finished step becomes visible to the polling page

            run_investigation(db, case, actor=actor, gateway=gateway, run_id=run_id, progress=publish)
    except Exception as exc:  # the run row says what happened; the page shows it
        log.exception("background investigation %s failed", run_id)
        with session_scope() as db:
            run = db.get(m.AIRun, run_id)
            if run is not None and run.status == "running":
                run.status, run.error, run.finished_at = "failed", f"{type(exc).__name__}: {exc}"[:1000], m.utcnow()


def run_view(db: Session, run: m.AIRun) -> dict:
    status = run.status
    if status == "running" and m.utcnow() - run.started_at > STALE_AFTER:
        status = "failed"
    report_id = db.scalar(select(m.Report.id).where(m.Report.run_id == run.id))
    end = run.finished_at or m.utcnow()
    return {"id": run.id, "case_id": run.case_id, "status": status, "steps": run.steps or [], "report_id": report_id,
            "error": "The run stopped before it finished. Please run it again." if status == "failed" and run.status == "running"
            else ("The investigation could not finish. Please run it again." if status == "failed" else None),
            "started_at": run.started_at.isoformat() + "Z", "elapsed_ms": int((end - run.started_at).total_seconds() * 1000)}
