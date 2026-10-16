# Build progress (resume notes)

Read PLAN.md first. This file tracks what is done and what is next, so work can resume after any interruption.

## Done — backend (71 tests green: `cd backend && python -m pytest`)
- Data model, Alembic baseline migration (verified on local MySQL 9.2 and SQLite)
- Trace engine, attribution (min/fifo/pro_rata/max, conservation), 12 rules, ledger normalisation
- Scoring (completeness, consistency, traceability, SLA, priority), policy library + eligibility
- Security (bcrypt, JWT cookie, case-level access, login lockout), hash-chained audit, OTel + redacted JSON logs
- Synthetic world S1–S10 with ground truth stored at seed time; evaluation harness 94/94 on SQLite and MySQL
- AI: Gemini gateway (timeout, schema validation, fallback chain, budget, cost, structured logs), validator,
  facts-only report, evidence reading + deterministic reconciliation, LangGraph investigator (explore tools,
  retry with validator feedback, judge), copilot, classification (+ translation), hold recommendations
- API: auth (+ optional Firebase), cases, graph (filters, bounded expand), timeline, risk, evidence (upload/analyse/file),
  actions/workflow, audit verify, investigate/reports/review/export, ask, classify, rules (versioned edit), network rings,
  ops metrics/calls/evals, admin reset, healthz
- Infra: Dockerfile (Node build + Python), infra/deploy.sh (APIs, SA, Cloud SQL, secrets, GCS, Cloud Run, log metrics,
  dashboard), infra/monitoring-dashboard.json
- Scripts: scripts/probe_gemini.py (find working model ids), scripts/live_e2e.py (live AI pipeline check),
  scripts/export_bigquery.py; Spanner Graph adapter (production path)

- Frontend: React + Vite + TS + React Flow — every screen; 31 tests; reviewed via Playwright screenshots (light/dark/mobile)
- Pitch deck (14 slides, PDF download): https://claude.ai/artifact/SZwE4qvUMaCuxxJiGkRqSf — placeholders [__] for live
  Gemini metrics, [Team name], [Cloud Run URL], [GitHub repository]; re-shoot the "responsible" slide screenshot after the live run
- Screenshots in docs/screenshots/

## Next
1. Waiting on user: GCP credentials → `scripts/probe_gemini.py` → `infra/deploy.sh` → `scripts/live_e2e.py` → tune prompts

## Tomorrow's runbook (with GCP access)
0. gcloud CLI is installed at `C:	ools\google-cloud-sdk` (Git Bash: `export PATH=/c/tools/google-cloud-sdk/bin:$PATH`).
   Corporate TLS: if curl/gcloud hits revocation errors, use `curl --ssl-no-revoke`.
1. `gcloud auth login && gcloud auth application-default login` (or use Cloud Shell)
2. `cd backend && python -m scripts.probe_gemini --project <P>` → note GEMINI_*_MODELS
3. Local live test: set GCP_PROJECT + models, `python -m scripts.live_e2e`
4. `PROJECT=<P> REGION=asia-south1 GEMINI_FAST_MODELS=.. GEMINI_PRO_MODELS=.. ./infra/deploy.sh`
5. Open the URL, run the demo script in README, record the video
