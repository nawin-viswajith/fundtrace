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
- [x] React UI: login, Overview, case queue, case workspace (7 tabs), trail graph, Network, Rules, AI Ops
- [x] Overview page: needs-attention list with next actions, golden-hour panel, SLA risk, recent activity
- [x] Outcome measurements from real activity (investigation time, first action, SLA, evidence completeness at decision, findings linked to sources, safeguards at 0)
- [x] Global case search in the top bar (case, transaction, UTR, account, customer)
- [x] Queue: age, next action, pagination
- [x] "Financial Intelligence" design: dark navy + teal by default, light theme available
- [x] Light and dark themes, mobile layout, loading, empty and error states
- [x] Queue SLA column shows the next open milestone
- [x] Frontend linting (ESLint, zero warnings)

### Telemetry and infrastructure
- [x] OpenTelemetry → Cloud Trace, structured logs, AI-call logs ready for Cloud Monitoring
- [x] Dockerfile, one-command `infra/deploy.sh`, Monitoring dashboard file
- [x] Scripts: Gemini model probe, live end-to-end run, BigQuery export
- [x] Spanner Graph adapter (production path)
- [x] gcloud CLI installed on the build laptop (`C:\tools\google-cloud-sdk`)

### Google Cloud (live)
- [x] Deployed: https://fundtrace-541805214490.asia-south1.run.app (Cloud Run, Cloud SQL MySQL, Cloud Storage, Secret Manager, Vertex AI)
- [x] Gemini models chosen by probe: 3.1 Pro (preview) for reports, 3.8 Flash for agent, evidence, judge; fallback chains
- [x] First live AI report: verified, 35 claims, 0 flagged, 0% hallucination, $0.20, ~3 min
- [x] Log-based metrics for AI calls and failures; Monitoring dashboard

### Deliverables
- [x] README, PLAN, progress notes, video script (`docs/DEMO_VIDEO.md`)
- [x] Pitch deck: 14 slides — `docs/FundTrace-deck.pdf` with live numbers and links (screenshots in the navy/teal theme)
- [x] GitHub repo created and pushed (private): https://github.com/nawin-viswajith/fundtrace

## ⬜ To do

### Google Cloud
- [ ] Tune prompts or speed up the fact-check step if needed (first live run: ~3 min end to end)

### Deliverables
- [ ] Fill the last deck placeholder: team name (cover and closing slides)
- [ ] Record the 3-minute video
- [ ] Make the GitHub repo **public**
- [ ] Submit on Hack2skill: deployed link, video, repo, deck PDF, theme

### Built on 2026-10-18
- [x] "Sign in with Google" button (Firebase Auth, loaded on demand; shown when FIREBASE_PROJECT_ID and FIREBASE_API_KEY are set)
- [x] MFA: authenticator app (TOTP) + recovery codes, per-role requirement (MFA_REQUIRED_ROLES), admin reset, Account security dialog
- [x] Field-level encryption (AES-256-GCM, Cloud KMS-wrapped data key, key rotation, start-up backfill)
- [x] DLP: built-in detectors + Cloud DLP for images/PDFs; masking in notes and LLM input; scan results on evidence
- [x] Ledger ingest: Pub/Sub push (OIDC-verified, dead-letter topic) + admin statement upload; ISO 20022 camt.053, CSV, JSON adapters
- [x] Evidence strength score per evidence item, with a sub-score per category and reasons
- [x] UI: light theme by default, square/flat design, decluttered screens
- [ ] Redeploy with the new infra/deploy.sh (creates the KMS key, Pub/Sub topic/subscription, DLP role); run it once and check the AI Ops security panel
- [ ] Re-run live evidence analysis with Gemini (prompt evidence-v3 adds relevance/origin labels) and check the scores
