"""Investigations in the background: the request returns at once, the steps are saved as they finish."""
import threading
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient

from app import models as m
from app.ai import runs

PW = "Investigate@2026"


@asynccontextmanager
async def _noop_lifespan(app):
    yield


@pytest.fixture(scope="module")
def client(seeded):
    from app.main import create_app

    app = create_app()
    app.router.lifespan_context = _noop_lifespan
    with TestClient(app) as c:
        yield c


def _join_workers():
    for t in threading.enumerate():
        if t.name.startswith("investigation-"):
            t.join(timeout=60)


def test_background_run_publishes_steps_and_ends_with_a_report(client, db):
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"username": "sup.meera", "password": PW}).status_code == 200
    first = client.post("/api/cases/CASE-24045/investigate?background=true").json()
    assert first["status"] == "running" and first["id"].startswith("RUN-")
    _join_workers()
    done = client.get(f"/api/cases/CASE-24045/runs/{first['id']}").json()
    assert done["status"] == "awaiting_review" and done["report_id"]
    assert [s["node"] for s in done["steps"]][:3] == ["gather", "explore", "evidence"]  # real steps, in order
    assert done["steps"][-1]["node"] == "finalize"
    assert client.get("/api/cases/CASE-24045/runs/active").json() == {"run": None}
    rep = client.get(f"/api/reports/{done['report_id']}").json()
    assert rep["status"] == "facts_only"  # LLM disabled in tests
    assert client.get("/api/cases/CASE-24051/runs/" + first["id"]).status_code == 404  # a run belongs to its case


def test_second_click_joins_the_running_investigation(db, seeded):
    case = db.get(m.DisputeCase, "CASE-24042")
    run = m.AIRun(id="RUN-TESTACTIVE", case_id=case.id, kind="investigation", status="running", steps=[])
    db.add(run)
    db.flush()
    again, thread = runs.start_background(db, case, "sup.meera")
    assert again.id == "RUN-TESTACTIVE" and thread is None
    run.started_at = m.utcnow() - runs.STALE_AFTER * 2  # an instance stopped mid-run: shown as failed, not forever "running"
    assert runs.run_view(db, run)["status"] == "failed" and runs.active_run(db, case.id) is None
    db.rollback()
