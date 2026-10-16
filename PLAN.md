# FundTrace — Build Plan

AI-powered dispute investigation platform for the **Google Cloud AI Builder Cup 2026** (BFSI theme:
*Intelligent Risk, Fraud & Financial Experiences*).

- Plan date: 2026-10-17 · Submission deadline: **2026-10-18** (confirm exact time and timezone on the Hack2skill dashboard)
- Repo: fresh repository and fresh history. The hackathon rule is "only fresh projects built during the hackathon timeline" (Sept 7 – Oct 18, 2026), so no code or data is copied from the old `codequest_2025` app.
- Deliverables: deployed Cloud Run link · public GitHub repo · demo video under 3 minutes · deck as PDF

---

## 1. The differentiator

> **Follow the money, show the proof, mark the guesses.**
>
> Reconstruct a disputed transaction's *observable* downstream trail, show the evidence behind every
> fraud signal, and let Gemini write an investigator report in which every claim links to a source
> record, with verified facts clearly separated from inferred connections.

Every feature is judged against this statement. A feature either strengthens it or supports the
investigator workflow around it.

### How the build maps to the judging criteria

| Criterion | Weight | What earns the points |
|---|---|---|
| Technical merit & GenAI | 40% | LangGraph agent that explores the trail using fixed, limited tools; Gemini reads evidence images and PDFs and links them into the graph; cited report with deterministic and judge-based hallucination checks; cost, token, latency and trace telemetry per call; confidence from log-probabilities and claim verification |
| Problem alignment & impact | 25% | Speed of recovery in the "golden hour" (hold recommendations on downstream accounts); investigator time saved; India-first (₹, UPI/IMPS, regulatory SLA clocks, multilingual allegations) that generalises to any real-time payment rail worldwide |
| Innovation & creativity | 25% | Traceable-amount ranges (lowest intermediate balance, FIFO and pro-rata bounds) instead of "amounts add up"; five provenance labels on every node, edge and claim; hash-chained audit trail; evidence-to-ledger reconciliation on the graph; cross-case mule-ring signals |
| User experience | 10% | Time-layered graph synced with the timeline; click a citation to jump to the record; plain-language legend; loading, empty, partial and error states; keyboard accessible |

---

## 2. Non-negotiable principles

1. **Gemini never calculates.** Money, balances, attribution, rules, graph paths and validation are deterministic code. Gemini classifies, reads documents, explores through tools, synthesises and explains.
2. **If the LLM fails, the result is "Not analysed".** This covers being down, timeouts, invalid output and budget exhaustion. Never show a guessed score and never auto-change the case status.
3. **The AI only suggests.** Only an investigator can refund, decline, close, escalate or place a hold. No AI output can reject a claim or assign customer liability.
4. **Every material claim cites a record ID.** A claim that cites an unknown ID, or quotes a number or time that doesn't match the cited record, is flagged as a hallucination.
5. **No single opaque trust score.** Fraud-risk signals, evidence completeness, evidence consistency, traceability coverage, policy eligibility and AI confidence stay separate.
6. **Five provenance labels everywhere:** Confirmed · Derived · Inferred · Unknown · Contradictory. Inferred is never shown as Confirmed.
7. **Missing data is never a negative finding.** A rule without its data returns `not_evaluable`, not "clear".
8. **Untrusted text stays untrusted.** Customer allegations, notes and document contents are fenced as data in prompts, and instructions inside them are ignored.
9. **No open-ended queries.** No arbitrary SQL or graph queries reach the frontend or the LLM, only fixed, parameterised and limited tools.
10. **Every consequential action is audited**, with actor, time, trace ID and hash-chain link.
11. **Synthetic data only**, labelled `is_synthetic` and visibly marked in the UI. Nothing implies it came from a real bank.

---

## 3. Tech stack

| Layer | Technology | Role |
|---|---|---|
| Frontend | React 18 + Vite + TypeScript, TanStack Query, React Router, **React Flow (`@xyflow/react`)**, Recharts | Investigator workspace, graph, AI Ops dashboard |
| API | Python 3.11, **FastAPI**, Pydantic v2, pydantic-settings | REST API, validation, role and case-level authorisation |
| Agents | **LangGraph** | Investigation pipeline: tool loop, retry with validator feedback, durable human-review gate |
| LLM | **Gemini on Vertex AI** via `google-genai` (`vertexai=True`) | Fast model for classification, extraction and judging; Pro model for the report. Model IDs come from config with a fallback chain. |
| Graph analysis | **NetworkX** | Time-ordered paths, cycles, hubs, components, communities (mule-ring signals) |
| Database | **Cloud SQL for MySQL 8** (SQLite for local dev and tests), **SQLAlchemy 2.0**, **Alembic** | Source of truth |
| Files | **Cloud Storage** (local folder in dev) | Evidence files, write-once, SHA-256 hashed |
| Auth | JWT in an httpOnly SameSite=Strict cookie with seeded users; **Firebase Auth / Identity Platform** as an optional provider | Roles: investigator, supervisor, admin |
| Secrets | **Secret Manager**, service account with least privilege | No keys in code; Vertex uses the service account's credentials |
| Telemetry | **OpenTelemetry** → **Cloud Trace**; JSON logs → **Cloud Logging** (trace-correlated, redacted); log-based metrics + **Cloud Monitoring** dashboard | End-to-end traceability |
| Deploy | **Cloud Run** (one container: API + built SPA), Cloud Build, Artifact Registry | `gcloud run deploy --source .` |
| Tests | pytest, Vitest + Testing Library | Unit, API, report-validator, evaluation |

**Production path, shown in the deck and partly scaffolded:**
- Pub/Sub → Dataflow ingest, with Datastream CDC → BigQuery for history, baselines and rule backtesting
- Spanner Graph for recent-transfer multi-hop serving, behind the same `GraphStore` interface
- Vertex AI Vector Search for policy retrieval

---

## 4. Build tiers

The base must be strong and fully functional before the wide scope is layered on. Each tier ends
with green tests and a deployable build.

### Tier 0: Base (strong, tested, deployable)
- Repo skeleton, config, DB layer, Alembic migration, Dockerfile, Cloud Run deploy script
- Data model (section 5) and **realistic synthetic scenarios** with ground truth (section 6)
- Ledger normalisation: integer minor units, duplicate source records, provenance
- **Trace engine**: time-ordered forward and backward trace, depth, window and node caps, cycle detection, hub pause, external-bank "visibility ends" endpoints, failed and reversed handling
- **Attribution**: lowest-intermediate-balance bounds (min/max), FIFO and pro-rata traceable amounts, multi-hop propagation, traceability coverage breakdown
- **Rules engine** with the full catalogue (section 8), `not_evaluable` handling, versioned config
- Scoring: completeness checklist, consistency checks, priority (P1–P4 with reasons), SLA clocks
- Case workflow state machine, notes, evidence requests, decisions, **hash-chained audit**
- Auth: seeded users, roles, case-level access checks
- **LLM gateway**: Gemini with timeout, schema validation, fallback chain, cost and token accounting, budget guard, `Not analysed` semantics
- **LangGraph investigator**: gather → explore (tools) → evidence → draft → validate → judge → retry → finalize; deterministic facts-only report when Gemini is unavailable
- REST API for everything above
- React app: login, case queue, case workspace (overview, graph, timeline, risk, evidence, report, audit), AI Ops page
- Tests for all of the above

### Tier 1: Differentiators (polish to demo quality)
- Gemini multimodal evidence reading (UPI receipt screenshots, bank statement PDFs) → reconciliation with ledger → evidence nodes on the graph (supports / contradicts)
- Hold recommendations on downstream accounts with traceable amount, approved by the investigator and audited
- Cross-case links: shared beneficiary and device across cases
- Click a citation to highlight it in the graph or open the record drawer; claim verdict chips
- Report confidence and hallucination panel on every report (claims, verified, unsupported, cost, latency, trace link)
- Evaluation harness: rules, trace and attribution against scenario ground truth; classification macro-F1; report hallucination rate. Results shown on the AI Ops page.

### Tier 2: Wide scope
- **Policy engine and retrieval**: fresh policy library (YAML) with deterministic eligibility conditions; Gemini retrieves and cites clause IDs, validated against the library
- **Classification** with log-probability confidence and calibration on the labelled set
- **Case copilot (Q&A)**: investigator asks about the case; Gemini answers using fixed tools only; answers cited and validated
- **Rule editing**: supervisor edits rule parameters in the UI; new rule version; audited; re-evaluate case
- **Global mule-ring search**: NetworkX communities and components over the whole synthetic network; ring view; signals only
- **Multilingual intake**: allegations in Hindi or Tamil translated and summarised by Gemini (original kept; translation labelled AI-generated)
- **Report export** (PDF/print view) with access check and audit event
- **Firebase Auth / Identity Platform** login option with ID-token verification
- **Cloud Monitoring** dashboard JSON + log-based metrics (cost/day, hallucination rate, LLM error rate, p95 latency)
- Retention settings: evidence retention days, deletion request flow (audited)

### Tier 3: Production path (scaffold + deck)
- `GraphStore` adapter stub for Spanner Graph (GQL queries written, behind a flag)
- BigQuery export job for transactions and AI telemetry
- Pub/Sub ingest adapter interface (`LedgerSource`) for authorised bank integrations
- Architecture diagram and scale story in the deck

---

## 5. Data model (SQLAlchemy → MySQL)

Money is always `BIGINT amount_minor` + `currency`. All times are UTC.

| Table | Key columns |
|---|---|
| `users` | id, username, full_name, role, password_hash, is_active |
| `customers` | id, display_name, segment, preferred_language, is_synthetic |
| `institutions` | id, name, kind (`self` / `external`) |
| `accounts` | id, customer_id?, institution_id, kind (savings/current/wallet/merchant/external), masked_number, opened_at, opening_balance_minor, currency, is_synthetic |
| `devices` | id, fingerprint_hash, first_seen_at |
| `auth_events` | id, account_id, device_id?, ip_hash, event_type, outcome, occurred_at, source_system, source_record_id |
| `transactions` | id, source_system, source_record_id (unique pair), debit_account_id, credit_account_id, amount_minor, currency, status (posted/pending/failed/reversed), channel (UPI/IMPS/NEFT/CARD/…), reference (UTR/RRN)?, occurred_at, posted_at?, reversal_of_id?, device_id?, narrative, is_synthetic, ingested_at |
| `dispute_cases` | id, disputed_txn_id, customer_id, category, allegation (untrusted), allegation_language, status, priority, priority_reasons, owner_id?, reported_at, created_at, due_at, sla_policy, decision?, decision_rationale?, decided_by?, decided_at?, is_synthetic |
| `case_notes` | id, case_id, author_id, body, created_at |
| `evidence_items` | id, case_id, kind, filename, mime, sha256, storage_uri, size, uploaded_by, uploaded_at, analysis_status (`not_analysed` / `analysed` / `failed`), extracted (JSON), reconciliation (JSON) |
| `evidence_requests` | id, case_id, checklist_key, requested_from, status, note, requested_by, created_at |
| `holds` | id, case_id, account_id, amount_minor, basis (JSON: traceable range + citations), status (recommended/requested/declined), recommended_by (`ai`/user), approved_by?, created_at |
| `rule_versions` | id, rule_id, version, params (JSON), enabled, created_by, created_at |
| `risk_flags` | id, case_id, evaluation_id, rule_id, rule_version, severity, status (`triggered` / `not_triggered` / `not_evaluable`), facts, source_ids, params, limitations, suggested_step, evaluated_at |
| `ai_runs` | id, case_id, kind, status, trace_id, started_at, finished_at, models, prompt_versions, ruleset_version, snapshot_hash, snapshot (JSON), tool_log (JSON), totals (tokens, cost, latency), error |
| `ai_calls` | id, run_id?, case_id?, node, model, prompt_version, status (ok/error/timeout/invalid/budget), input_tokens, output_tokens, thinking_tokens, cost_usd, latency_ms, avg_logprob?, trace_id, error, created_at |
| `reports` | id, case_id, run_id, version, status (`verified` / `partially_verified` / `unverified` / `facts_only`), sections (JSON claims + citations + verdicts), metrics (JSON), claims_total, claims_supported, claims_flagged, hallucination_rate, confidence, review_status, reviewed_by?, review_note?, created_at |
| `policies` | id, version, title, category, effective_from, clauses (JSON), conditions (JSON) |
| `eval_runs` | id, kind, started_at, metrics (JSON), details (JSON) |
| `audit_events` | id (autoincrement), case_id?, actor, actor_role, action, details (JSON), trace_id, created_at, prev_hash, hash |

---

## 6. Synthetic scenarios (with ground truth)

The scenarios are generated deterministically from a fixed seed and labelled **SYNTHETIC** everywhere.

| # | Scenario | What it exercises |
|---|---|---|
| S1 | **Headline demo:** Account A → B ₹50,000 (UPI). B had ₹1,200 before. Within 25 min B → C ₹30,000 and B → D ₹20,000. D is at an external bank. B opened 9 days ago. 4 failed logins on A from a new device 10 min before the transfer. | Rapid outflow, split, young beneficiary, auth anomaly, external endpoint, attribution near-full |
| S2 | **Mixed funds:** A2 → B2 ₹40,000; B2 also receives ₹60,000 salary-like credit 5 min later; B2 → C2 ₹70,000 | Attribution ranges diverge (min vs max vs pro-rata vs FIFO) |
| S3 | **Mule ring:** B (from S1) and B3 are beneficiaries in 3 other disputes; shared device across B, B3 and E3 | Shared beneficiary, shared device, community detection |
| S4 | **Hub:** funds reach a merchant settlement account with 300+ transfers | Hub pause, expansion on demand |
| S5 | **Reversal + resend:** transfer reversed, then a new transfer to a different beneficiary | Reversal pattern, reversed funds not propagated |
| S6 | **Cycle:** A6 → B6 → C6 → A6 | Cycle detection without infinite expansion |
| S7 | **Evidence contradiction:** customer screenshot shows ₹45,000 and a different UTR from the ledger's ₹50,000 | Contradictory evidence node |
| S8 | **Clean / genuine:** customer disputes a normal merchant payment; no signals | Non-triggering rules; no false narrative |
| S9 | **Missing data:** no auth logs available for the payer's channel | `not_evaluable`, completeness gaps, "missing ≠ negative" |
| S10 | **Duplicate source records** for one transaction from two systems | Normalisation dedupe, consistency check |
| bg | Background customers, ordinary activity (~2,000 txns) | Baselines, realistic noise |

Synthetic evidence files (PNG receipts and a text statement) are generated with a visible "SYNTHETIC" watermark.

---

## 7. Trace engine and attribution

**Trace (forward):** start at the disputed transaction T0 and its credit account.
1. Frontier item = (account, arrival_time, depth, path_accounts).
2. Fetch the account's outgoing transactions where `arrival_time < occurred_at ≤ T0 + window`, ordered by time, up to the per-account cap. Each hop must happen after the previous one; this is time-ordered tracing, not plain path finding.
3. Failed transactions are shown but never propagated. Reversed transactions are shown with their reversal and not propagated.
4. Stop and label at: external institution (**Unknown: visibility ends**, suggested action "request trail from receiving bank"), hub account (**paused: high-activity account**, expandable), depth cap, node cap (**truncated**, with reason), cycle (edge kept, no re-expansion, cycle reported).
5. **Backward** trace mirrors this using incoming transactions before T0.

**Graph shape:** account nodes, transaction nodes, evidence nodes, auth-event nodes, endpoint nodes.
- Edges: `sent` (account → txn) and `received_by` (txn → account) are **Confirmed** (ledger record).
- `reversal_of` is **Confirmed**; `associated_auth` (device + time window) is **Derived**.
- `possible_onward_funding` (txn → txn) is **Inferred**, and carries the attribution range.
- `supports` / `contradicts` (evidence → txn) are **Derived** or **Contradictory**.

Every node and edge carries `provenance`, `source_ids` and `event_time`.

**Attribution** (deterministic, per traced account, in global time order):
- Balance at window start = opening balance + posted history before it. External balances are unknown, so attribution stops there.
- For each debit, compute the disputed-fund portion under four methods:
  - **max** (tainted-first)
  - **min** (clean-first; this is the lowest intermediate balance bound)
  - **FIFO** (fund lots by arrival)
  - **pro-rata** (proportional)
- Each method's portion propagates into the next hop's account.
- Output per transaction: `{min, fifo, pro_rata, max}`.
- Output per endpoint: residual in visible accounts, amount that left visibility, amount that reached a hub, amount untraced.
- **Traceability coverage** = share of the disputed amount whose position at window end is accounted for, shown per method.
- Labelled **Derived**, with the explicit caveat that it does not prove the downstream funds *are* the disputed money.

---

## 8. Fraud-signal catalogue

Every rule returns: rule ID, name, version, severity, status, facts, source IDs, parameters and
thresholds, evaluated-at time, limitations, and suggested investigation step. Parameters are
versioned and editable by supervisors (Tier 2).

| ID | Signal | Fires when (default params) | Needs |
|---|---|---|---|
| R1 | Rapid onward movement | ≥ 80% of the received amount leaves the beneficiary within 60 min | Beneficiary's outgoing transactions |
| R2 | Split / fan-out | ≥ 2 outgoing transfers to ≥ 2 distinct accounts within 120 min, summing to ≥ 80% of the receipt | Same |
| R3 | Shared beneficiary across cases | An account in the trail is the beneficiary in ≥ 1 other dispute | Case links |
| R4 | Failed logins before success | ≥ 3 failed auth events within 30 min, then success, then the disputed transaction | Auth events |
| R5 | New device | Disputed transaction's device first seen < 24 h before | Device history |
| R6 | Unusual amount | Amount ≥ 5× the payer's 90-day median debit, with ≥ 5 prior debits | Payer history |
| R7 | Young beneficiary account | Beneficiary opened < 30 days before receipt | Account opened date |
| R8 | Reversal then resend | Reversal followed by a new debit from the same payer within 24 h | Status history |
| R9 | Evidence–ledger mismatch | Customer evidence amount, reference or time differs from the ledger | Analysed evidence |
| R10 | Shared device across accounts | The payer's or beneficiary's device is used by another account in a flagged trail | Device links |
| R11 | Exit to external institution | Disputed funds leave the bank's visibility within the window | Trail |

Rules are signals for review, never verdicts. The UI says so next to the flags.

---

## 9. Separate assessment dimensions

| Dimension | Computed as | Shown as |
|---|---|---|
| Fraud-risk signals | Triggered flags by severity | List with severity, no score |
| Evidence completeness | Required checklist items present ÷ required for the category | `5 / 8 required`, with the missing items and why they matter |
| Evidence consistency | Cross-source checks: consistent / contradictory / unverifiable | Counts with drill-down |
| Traceability coverage | Section 7 | % per method, plus an endpoint breakdown |
| Policy eligibility | Deterministic conditions on the policy library | Eligible / not eligible / needs information, with clause ID |
| AI confidence | Classification: probability from average log-probability. Report: supported claims ÷ total claims, after checks. | Per output, never blended with risk |

**Priority (P1–P4):** computed from amount band, highest triggered severity, residual funds still
in visible accounts (golden hour), SLA time remaining, and customer-protection flags. It always
comes with a list of reasons.

**SLA clocks:** per category and jurisdiction in config. For INR unauthorised electronic
transactions the config uses the RBI customer-liability circular timelines (shadow credit window
and resolution window); verify the values against the circular before the demo.

---

## 10. Case workflow

`new → triage → investigating → awaiting_evidence → ready_for_review → resolved | escalated`
(`escalated → investigating` and `resolved → investigating` reopen paths for supervisors)

- Transitions are validated server-side. Resolving requires a decision, a rationale (≥ 20 chars) and a reviewed report or an override reason.
- Investigator actions: assign/claim, add note, request evidence, change status, approve or decline a hold recommendation, accept or reject report claims, record a decision (`uphold_claim` / `partial` / `decline_claim` / `refer`) with rationale, escalate.
- Every action writes an audit event (hash-chained: `hash = sha256(prev_hash + canonical event JSON)`); the UI verifies the chain.

---

## 11. AI pipeline (LangGraph)

```
gather_context [D] → explore [Gemini + fixed tools, ≤ 2 rounds, ≤ 6 calls]
  → analyse_evidence [Gemini multimodal → D reconciliation]
  → draft_report [Gemini Pro, structured JSON, cited claims]
  → validate [D] → judge [Gemini fast] → (retry draft once with validator feedback)
  → finalize [D: metrics, confidence, persist, audit] → awaiting human review (durable DB state)
```

- **Evidence snapshot:** every citable record (TXN, ACCT, EV, FLAG, AUTH, ATTR, POL, CASE) with a stable ID. The snapshot hash is saved with the report. Only snapshot IDs are valid citations.
- **Tools** (allow-listed, parameter-validated, limited): `expand_account`, `trace_backward`, `linked_cases`, `account_activity`, `device_links`. Each call is logged in `tool_log` with arguments, result size and duration.
- **Report sections:**
  1. Case overview
  2. Known facts
  3. Transaction trail
  4. Risk indicators
  5. Evidence supporting the claim
  6. Evidence contradicting or not establishing it
  7. Missing information
  8. Recommended next actions
  9. Limitations and uncertainty

  Each claim has `text`, `citations[]`, and `basis` (`verified` / `derived` / `inferred` / `unknown`).
- **Deterministic validator:**
  - citations present and in the snapshot
  - IDs mentioned in the text are cited
  - every amount, date and time in the text matches a cited record
  - `verified` basis requires a Confirmed record
  - flow-through language requires `inferred`
  - banned phrases ("proves fraud", "customer is liable", "definitely", "reject the claim", …)
  - all sections present
- **Judge (Gemini fast):** per claim against its cited records → `supported` / `partial` / `unsupported` / `contradicted`. If unavailable, the claim is marked `unjudged`.
- **Hallucination rate** = (invalid citations + number mismatches + unsupported + contradicted) ÷ claims.
- **Confidence** = supported ÷ claims (after validation), shown with its components.
- **Gemini unavailable:** a deterministic **facts-only report** is generated from the snapshot (clearly labelled), and all AI items show `Not analysed`.
- **Prompt-injection defence:** untrusted text is fenced, the system instruction says to treat it as data, and outputs are schema-validated. Tool arguments must reference snapshot IDs.

---

## 12. Telemetry, cost and traceability

- OpenTelemetry spans: HTTP request → LangGraph node → Gemini call / tool call. The `trace_id` is stored on every `ai_call`, `ai_run`, `report` and `audit_event`. The Cloud Trace link is shown in the UI.
- **Cost:** `usage_metadata` tokens (input, output, thinking) × versioned price table (config, with as-of date and source URL). Aggregated per call, node, run, case and day.
- **Budget guard:** daily and per-case USD caps. When exceeded, calls return `budget`, so items show `Not analysed`.
- **AI Ops page:**
  - calls, error / timeout / invalid rates
  - p50 / p95 latency per node
  - tokens and cost per case and per day
  - hallucination rate trend, judge verdict mix
  - evaluation results
  - model and prompt versions in use
- **Logs:** JSON, trace-correlated (`logging.googleapis.com/trace`), with account numbers, phone numbers, emails and IPs redacted.

---

## 13. API (prefix `/api`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/login`, `/auth/logout`; GET `/auth/me` | Session |
| GET | `/cases?status=&priority=&owner=&q=` | Queue (access-filtered) |
| GET | `/cases/{id}` | Case with investigation context (dimensions, priority, SLA) |
| GET | `/cases/{id}/graph?direction=&depth=&window_hours=&status=&rel=` | Trail graph + attribution |
| POST | `/cases/{id}/graph/expand` | Expand a node (limited) |
| GET | `/cases/{id}/timeline` | Accessible chronological list |
| GET | `/cases/{id}/risk` · POST `/cases/{id}/risk/evaluate` | Flags |
| GET | `/cases/{id}/evidence` · POST `/cases/{id}/evidence` (upload) · POST `/cases/{id}/evidence/{ev}/analyse` | Evidence + checklist |
| POST | `/cases/{id}/investigate` · GET `/cases/{id}/reports` · GET `/reports/{id}` | AI investigation |
| POST | `/reports/{id}/review` | Accept / reject claims |
| POST | `/cases/{id}/actions` | Note, request evidence, status, assign, hold, decision, escalate |
| GET | `/cases/{id}/audit` · GET `/cases/{id}/audit/verify` | Audit trail + chain check |
| POST | `/cases/{id}/ask` | Case copilot (Tier 2) |
| GET/PUT | `/rules` | Rule catalogue / edit params (supervisor, Tier 2) |
| GET | `/network/rings` | Mule-ring signals (Tier 2) |
| GET | `/ops/metrics` · `/ops/calls` · `/ops/evals` | AI Ops |
| GET | `/healthz` | Health |

Errors use one shape, `{error: {code, message}}`, with no record contents in errors. Every case route checks case-level access.

---

## 14. Frontend

- **Login.** Demo credentials hint; SYNTHETIC banner.
- **Case queue.** Filters, priority chip with reasons tooltip, SLA countdown, owner, status.
- **Case workspace:**
  - Header: case ID, category, disputed transaction (amount, currency, status, reference), priority + reasons, SLA, owner, status, actions
  - **Overview:** allegation (fenced as customer-provided), the six dimension cards, missing-evidence checklist
  - **Graph:** React Flow, time-layered left-to-right layout; line style by provenance; width by amount; legend; filters (direction, depth, window, status, relationship); node and edge details drawer with source IDs; expand-on-click; attribution panel
  - **Timeline:** accessible table equivalent of the graph
  - **Risk:** flags with facts, thresholds, limitations, "show on graph"
  - **Evidence:** upload, analysis status, extracted fields vs ledger, checklist, request evidence
  - **Report:** generate; sections with claim chips (basis, verdict); click a citation to see the record; confidence and hallucination panel; review controls
  - **Actions & Audit:** decision form, hold approvals, notes, audit trail with chain verification
- **AI Ops dashboard.** Section 12.
- **Network** (Tier 2). Mule-ring view.
- **Rules** (Tier 2). Catalogue with edit form for supervisors.

Every view has loading, empty, partial-data and error states, keyboard focus order, and AA contrast.

---

## 15. Security and privacy

- bcrypt password hashes; JWT (HS256, secret from Secret Manager) in an httpOnly, Secure, SameSite=Strict cookie
- Roles: investigator (own and unassigned cases), supervisor (all cases, reassign, rules), admin (ops)
- Case-level access checks on every case, evidence and report route
- Input validation (Pydantic, enums, limits on depth, window and node caps); ORM-only queries
- Uploads: type allow-list (PNG/JPEG/PDF/TXT), 5 MB cap, SHA-256, stored outside web root, downloads through an access-checked route
- Log redaction filter; safe error messages
- Retention: `EVIDENCE_RETENTION_DAYS` config, deletion request action (audited)
- Not implemented for production (documented): MFA, KMS-managed field encryption, real bank integration auth, DLP scanning

---

## 16. Testing and evaluation

- **Unit:** normalisation (minor units, dedupe), trace (time order, cycles, hubs, external, failed and reversed, caps, empty), attribution (all four methods on S1/S2, conservation of money), every rule (triggers, non-triggers, not evaluable), scoring, workflow transitions, audit chain
- **AI:** validator catches made-up IDs, wrong amounts and banned phrases; fake-LLM pipeline end-to-end; LLM-down produces `Not analysed` and a facts-only report; schema-invalid output handling; budget guard
- **API:** auth required, case-level access denied for other investigators, input validation (bad depth, unknown IDs), error shape
- **Frontend:** component tests for graph legend and provenance styling, report citation chips, empty and error states
- **Evaluation harness** (`python -m app.eval`): scenario ground truth → rule precision and recall, trace endpoint accuracy, attribution correctness, classification macro-F1, report hallucination rate. Stored in `eval_runs` and shown on AI Ops.

---

## 17. Deployment (GCP)

1. Project + region (`asia-south1` or `asia-southeast1`); enable Run, SQL Admin, Vertex AI, Storage, Secret Manager, Cloud Build, Artifact Registry, Trace, Logging, Monitoring
2. Cloud SQL MySQL 8 instance + database + user (password in Secret Manager)
3. GCS bucket for evidence (uniform access, no public access)
4. Service account with roles: `aiplatform.user`, `cloudsql.client`, `storage.objectAdmin` (bucket-scoped), `secretmanager.secretAccessor`, `cloudtrace.agent`, `logging.logWriter`
5. `gcloud run deploy --source .` with `--add-cloudsql-instances`, env vars and secrets
6. Startup runs Alembic migrations and seeds synthetic data when `SEED_ON_START=true`
7. Verify Gemini model IDs available in the region and set `GEMINI_FAST_MODELS` / `GEMINI_PRO_MODELS` (fallback chains)

`infra/deploy.sh` scripts steps 1–6.

---

## 18. Schedule

| When | Work |
|---|---|
| Oct 17 AM | Tier 0 backend: skeleton, models, synthetic data, trace + attribution, rules, scoring, workflow, audit, auth, with tests |
| Oct 17 PM | LLM gateway, LangGraph investigator, validator/judge, telemetry; API complete. Frontend scaffold, queue and workspace in parallel. |
| Oct 17 night | GCP setup + first Cloud Run deploy; Tier 1 differentiators; evaluation harness |
| Oct 18 AM | Tier 2 features in priority order: policy/classification → copilot → rule editing → mule rings → multilingual → export → Firebase Auth → Monitoring |
| Oct 18 PM | Hardening, full test run, README, deck PDF, 3-minute video, final deploy, **submit with buffer** |

If time runs short, Tier 2 items are dropped from the end of the list. Tier 0 and Tier 1 are not dropped.

---

## 19. Demo script (≈ 3 minutes)

1. **Problem (20s):** real-time payment fraud moves money in minutes; investigators trace by hand across statements; recovery depends on speed.
2. **Open S1 (20s):** P1 priority with reasons; SLA clock; six separate dimensions, no black-box score.
3. **Graph (40s):** A → B ₹50,000 → C ₹30,000 / D ₹20,000 (external: visibility ends). Solid = confirmed, dashed = inferred. Attribution: "up to ₹X traceable to C under every method".
4. **Signals (20s):** rapid onward movement and split highlighted on the graph with facts and thresholds; auth anomaly; young beneficiary; shared beneficiary across cases.
5. **Evidence (20s):** upload the customer's screenshot → Gemini extracts the UTR and amount → reconciled to the ledger (or a red contradiction in S7).
6. **AI report (40s):** generate; agent tool calls visible; click a claim to see its record; "14 claims · 14 verified · 0 unsupported · $0.0x · trace"; "What this does not prove" section.
7. **Human decision (20s):** approve the hold on C, record a decision with rationale, audit chain verified.
8. **Ops + scale (20s):** AI Ops (cost, hallucination, latency, evals); production architecture (Pub/Sub, BigQuery, Spanner Graph).

---

## 20. Open items and risks

| Item | Owner | Status |
|---|---|---|
| GCP project ID, region, billing; `gcloud` on the build machine | Team | **Needed** |
| Exact submission time and timezone | Team | **Needed** |
| Gemini model IDs available in the chosen region (2.5 family is past its earliest retirement date; 3.x family listed) | Build | Verify at deploy; fallback chain in config |
| Price table values | Build | From the Vertex pricing page, with as-of date |
| RBI SLA values | Team | Verify against the circular |
| Risk: Cloud SQL provisioning time | Build | Start early; SQLite fallback for the demo is not acceptable for submission, so provision on Oct 17 |
| Risk: Vertex quota or availability during the demo | Build | Facts-only report path + recorded video as backup |
