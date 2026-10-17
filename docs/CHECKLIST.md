# FundTrace — Build Checklist

Status as of 2026-10-17. Testing items are excluded.

## ✅ Done

### Core engine
- [x] Data model and database migration (Cloud SQL for MySQL; SQLite locally)
- [x] Ledger cleanup: exact amounts, merging the same payment reported by several systems, source records kept
- [x] Time-ordered trail tracing, forward and backward
  - Labelled stops: other bank or cash ("visibility ends"), merchant, busy hub account, cycle, depth limit, result cap
- [x] Attribution ranges for each onward transfer (lower bound, FIFO, pro-rata, upper bound), with hold candidates
- [x] 12 fraud-signal rules; missing data returns "not evaluable", never "clear"
- [x] Separate scores: evidence completeness, consistency, traceability, priority (P1–P4 with reasons), SLA clocks
- [x] Policy library with eligibility checks
- [x] Synthetic data: 10 scenarios plus background activity and evidence files

### AI (Gemini on Vertex AI, LangGraph)
- [x] Gemini gateway: timeout, output-format checks, model fallback, cost and token tracking, budget limit, "Not analysed" on failure
- [x] Investigation pipeline: gather → explore (5 fixed tools) → read evidence → draft → validate → fact-check → finalize
- [x] Hallucination validator, plus a facts-only report built by code when Gemini is down
- [x] Evidence reading with the ledger comparison done by code; prompt-injection detection
- [x] Case Q&A copilot, category suggestion, Hindi translation
- [x] Hold recommendations that an investigator approves

### Workflow and security
- [x] Case statuses and actions: notes, evidence requests, holds, decisions, escalation, assignment
- [x] Tamper-evident audit trail with chain verification
- [x] Login with secure session cookie, roles, per-case access, lockout after failed logins
- [x] Firebase login (backend only)
- [x] Upload checks, logs with sensitive data hidden, uniform error format
- [x] Rule editing with versions
- [x] Mule-ring detection

- [x] Category-suggestion accuracy evaluation (accuracy, macro-F1); produces numbers once Gemini is connected
- [x] Evidence deletion and retention flow (request → supervisor approval → file removed, hash kept; admin retention run)

### API and UI
- [x] Full REST API
- [x] React UI: login, case queue, case workspace (7 tabs), trail graph, Network, Rules, AI Ops
- [x] Light and dark themes, mobile layout, loading, empty and error states
- [x] Queue SLA column shows the next open milestone
- [x] Frontend linting (ESLint, zero warnings)

### Telemetry and infrastructure
- [x] OpenTelemetry → Cloud Trace, structured logs, AI-call logs ready for Cloud Monitoring
- [x] Dockerfile, one-command `infra/deploy.sh`, Monitoring dashboard file
- [x] Scripts: Gemini model probe, live end-to-end run, BigQuery export
- [x] Spanner Graph adapter (production path)
- [x] gcloud CLI installed on the build laptop (`C:\tools\google-cloud-sdk`)

### Deliverables
- [x] README, PLAN, progress notes, video script (`docs/DEMO_VIDEO.md`)
- [x] Pitch deck: 14 slides — `docs/FundTrace-deck.pdf` plus the online version
- [x] GitHub repo created and pushed (private): https://github.com/nawin-viswajith/fundtrace

## ⬜ To do

### Needs GCP credentials
- [ ] Run `backend/scripts/probe_gemini.py` to choose the Gemini model IDs; add prices for any model not in the price table
- [ ] Run `infra/deploy.sh`: Cloud SQL, storage bucket, secrets, Cloud Run, log metrics, dashboard
- [ ] Tune prompts after the first live Gemini reports, if needed

### Deliverables
- [ ] Fill deck placeholders: team name, Cloud Run URL, repo URL, live hallucination rate, cost per case, run time
- [ ] Re-take the "No black-box trust score" screenshot (still shows the old "100%"), then re-render the PDF with `python docs/deck/render_pdf.py`
- [ ] Record the 3-minute video
- [ ] Make the GitHub repo **public**
- [ ] Submit on Hack2skill: deployed link, video, repo, deck PDF, theme

### In the plan but not built (optional)
- [ ] Firebase sign-in button in the UI (the backend endpoint exists)
- [ ] Pub/Sub ingest (only the adapter interface exists; otherwise deck-only)
