# Build progress (resume notes)

Read PLAN.md first. This file tracks what is done and what is next, so work can resume after any interruption.

## Done (tests green: `cd backend && python -m pytest`)
- Config, DB layer, SQLAlchemy models (`backend/app/models.py`)
- Graph store interface + SQL + in-memory (`services/graph_store.py`)
- Time-ordered trace engine with endpoints, hubs, merchants, cycles, caps (`services/trace.py`)
- Attribution: min/fifo/pro_rata/max, conservation, holdable (`services/attribution.py`)
- 12 rules with not_evaluable semantics (`services/rules.py`)
- Ledger normalisation with multi-source merge (`services/ledger.py`)
- Scoring: completeness, consistency, traceability, SLA, priority (`services/scoring.py`)
- Policy library + eligibility (`data/policies.yaml`, `services/policy.py`)
- Security (bcrypt, JWT cookie, case-level access), hash-chained audit, telemetry
- Synthetic world S1–S10 + loader + evidence files (`seed/`)
- Evaluation harness vs ground truth (`eval/harness.py`) — 100% pass
- AI: pricing, Gemini gateway (+FakeGateway), schemas, prompts, snapshot

## Next (in order)
1. AI: validator, facts-only report, evidence analysis, LangGraph investigator, copilot, classify
2. Services: workflow/actions, network (mule rings)
3. API routers + main app (serves SPA), error shape
4. Tests: validator, investigator (fake LLM + LLM down), API auth/validation
5. Frontend (React+Vite+TS, React Flow): login, queue, workspace tabs, ops, network, rules
6. Dockerfile, infra/deploy.sh, .env.example, README, Alembic baseline
7. Waiting on user: GCP credentials → deploy + live Gemini test
