# FundTrace

**Follow the money, show the proof, mark the guesses.**

FundTrace is an AI-assisted investigation workspace for bank payment disputes. It is our entry to the
Google Cloud AI Builder Cup 2026, BFSI track (*Intelligent Risk, Fraud & Financial Experiences*).

When a customer says *"I didn't make this ₹50,000 payment"*, an investigator has hours, not days,
before the money is gone. FundTrace does four things:

- It reconstructs the **observable downstream trail** of the disputed transaction from ledger records.
- It computes **how much of each onward transfer could, or must, be the disputed funds**.
- It shows **the evidence behind every fraud signal**.
- It has **Gemini write an investigation report** in which every sentence links to a source record.
  Hallucinations are checked, flagged and measured.

The investigator stays in charge. The AI never decides liability.

**Pitch deck:** [docs/FundTrace-deck.pdf](docs/FundTrace-deck.pdf) (sources in `docs/deck/`; re-render with `python docs/deck/render_pdf.py`).

> All data in this repository and in the deployed demo is **synthetic**. No real customer or bank data is used.

---

## What makes it different

| | What we built | Why it matters |
|---|---|---|
| **Traceable-amount ranges** | Every onward transfer gets a lower and upper bound of how much could be the disputed money. The bounds use four tracing conventions: clean-first (lowest intermediate balance), FIFO, pro-rata and tainted-first. | "Amounts add up" is not evidence. A positive lower bound is **derived** (balance arithmetic forces it). An upper bound alone is only **inferred**. |
| **Five provenance labels** | Every node, edge and report claim is *Confirmed*, *Derived*, *Inferred*, *Unknown* or *Contradictory*. | Inferred links are never shown as facts. |
| **Honest trail endpoints** | A trail stops for one of several reasons: *visibility ends* (another bank or cash), *merchant*, *high-activity hub*, *cycle*, *depth limit* or *result cap*. Each stop is explicit and expandable. | Missing data is shown as unknown, not as absent. |
| **Agentic, bounded AI** | A LangGraph agent with Gemini chooses which trail branches to explore using **fixed, parameter-checked tools**. It can never run free-form queries. | Real agency without open-ended data access. |
| **Hallucination defence** | 1. A deterministic validator checks the report: cited IDs exist, every ₹ amount and time matches the cited record, no "proves fraud" or "customer is liable" language, and flow-through claims are never marked verified.<br>2. One redraft with feedback.<br>3. A Gemini judge checks each claim against its cited records.<br>4. A **hallucination rate** and **confidence** are recorded on every report. | Measured trust instead of claimed trust. |
| **Evidence reconciled, not trusted** | Gemini reads receipts and screenshots (multimodal). **Code** then compares the amount, UTR and time with the ledger. Instructions embedded in documents are detected and ignored. | Catches the customer screenshot that shows ₹45,000 when the ledger says ₹50,000, and the prompt-injection attempt hidden in it. |
| **Golden-hour holds** | Visible downstream accounts that may still hold disputed funds become hold recommendations with an amount range. An investigator must approve each one. | Recovery depends on speed; the decision stays human. |
| **Hash-chained audit** | Every action is chained: `hash = sha256(prev_hash + event)`. The UI verifies the chain. | Tamper-evident accountability. |
| **AI Ops** | Tokens, cost, latency, error rate, hallucination rate and judge verdicts are tracked per call, node, case and day. The page also shows evaluation against ground truth and links to Cloud Trace. | Running AI responsibly in a bank. |

### Dimensions are kept separate on purpose

There is no single "trust score". The workspace shows six independent views:

- fraud-risk signals
- evidence completeness
- evidence consistency
- traceability coverage
- policy eligibility
- AI confidence

A case with incomplete evidence is neither fraudulent nor legitimate. It is incomplete.

---

## Architecture

```
 React (Vite, TS, React Flow) ──► FastAPI on Cloud Run ──► Cloud SQL for MySQL 8 (source of truth)
                                   │                     ├► Cloud Storage (evidence, write-once, SHA-256)
                                   │                     └► Secret Manager (DB URL, JWT secret)
                                   ├─ Deterministic core: ledger normalisation → time-ordered trace (NetworkX)
                                   │   → attribution → 12 rules → completeness / consistency / SLA / policy
                                   └─ LangGraph investigator ──► Gemini on Vertex AI
                                        gather → explore (tools) → evidence → draft → validate → judge → finalize
 OpenTelemetry → Cloud Trace · structured, redacted JSON logs → Cloud Logging → log-based metrics → Cloud Monitoring
```

**Principle:** Gemini never calculates. Money, balances, attribution, rules, graph paths and validation
are deterministic code. Gemini classifies, reads documents, explores through tools, synthesises and explains.

**Production path** (designed, with adapters in the repo):
- Pub/Sub → Dataflow ingest, with Datastream CDC → BigQuery for history and rule back-testing (`scripts/export_bigquery.py`)
- Spanner Graph for multi-hop serving at bank scale, behind the same `GraphStore` interface (`services/spanner_graph_store.py`)

Each case's subgraph stays small even at bank scale, because traces are bounded by depth, time window and node caps.

### Repository

```
backend/app/
  services/   graph_store · trace · attribution · rules · ledger · scoring · policy · workflow · network · storage
  ai/         llm (Gemini gateway) · investigator (LangGraph) · tools · validator · facts_report · evidence · copilot · prompts · schemas · snapshot · pricing
  api/        auth · cases · ops
  seed/       synthetic world S1–S10 + evidence files · loader
  eval/       evaluation harness (ground truth)
backend/tests/   71 tests: trace, attribution, rules, ledger, scenarios, validator, investigator, gateway, API
frontend/        React app
infra/           deploy.sh (one command) · monitoring-dashboard.json
docs/            api-samples · PROGRESS.md
```

---

## Run locally

Requirements: Python 3.11+ and Node 20+.

```bash
# backend
cd backend
pip install -r requirements-dev.txt
python -m pytest                      # 71 tests
python -m uvicorn app.main:app --port 8000      # seeds synthetic data on first start (SQLite)

# frontend (second terminal)
cd frontend
npm install
npm run dev                           # http://localhost:5173 (proxies /api to :8000)
```

Logins (synthetic demo; the password is also shown on the login page): `inv.asha`, `inv.ravi`
(investigators), `sup.meera` (supervisor), `admin`. Password: `Investigate@2026`.

Without Google Cloud credentials the app still works fully. AI features show **"Not analysed"**, and
investigations produce a clearly labelled **facts-only report** built from records by code.

### Enable Gemini locally

```bash
gcloud auth application-default login
cd backend
python -m scripts.probe_gemini --project YOUR_PROJECT          # finds model ids that answer in your project
set GCP_PROJECT=YOUR_PROJECT
set GEMINI_FAST_MODELS=...
set GEMINI_PRO_MODELS=...
python -m scripts.live_e2e                                       # runs the whole AI pipeline on 3 demo cases
```

## Deploy to Google Cloud

```bash
PROJECT=your-project REGION=asia-south1 \
GEMINI_FAST_MODELS=gemini-2.5-flash GEMINI_PRO_MODELS=gemini-2.5-pro,gemini-2.5-flash \
./infra/deploy.sh
```

The script is idempotent. It does the following:
1. Enables the APIs.
2. Creates a least-privilege service account.
3. Creates Cloud SQL for MySQL 8 (utf8mb4).
4. Stores the DB URL and JWT secret in Secret Manager.
5. Creates a private evidence bucket.
6. Builds and deploys to Cloud Run (Alembic migrations run at start).
7. Creates log-based metrics and the Monitoring dashboard.
8. Prints the URL.

---

## Demo script (≈ 3 minutes)

1. **Queue.** `CASE-24051` is **P1**. The reasons are high value, high-severity signals, *golden hour* and SLA pressure.
2. **Overview.**
   - The customer statement is fenced as unverified.
   - The six dimensions are shown separately.
   - A hold recommendation on the downstream account is shown with a range.
3. **Trail graph.**
   - A → B ₹50,000 (B opened 9 days ago)
   - B → C ₹30,000 and B → D ₹20,000 (Other Bank: *visibility ends*)
   - C → E ₹12,000 (*visibility ends*)
   - Solid lines are confirmed; dashed lines are attribution.
   - Example: *"at least ₹28,800 of the ₹30,000 must be disputed funds — balance arithmetic"*.
4. **Risk signals.** Signals and the facts behind them:
   - rapid onward movement and split
   - 4 failed logins and an OTP from a device first used on this account 14 minutes earlier
   - the same device was used on another victim's account
   - the beneficiary appears in 2 other disputes
   - *Show on graph* highlights the records.
5. **Evidence.** Analyse the customer's screenshot. Gemini extracts the amount and UTR, and code reconciles them with the ledger. Then switch to `CASE-24049`: the screenshot says ₹45,000, so a **contradiction** appears on the graph and the embedded instruction is flagged as ignored.
6. **AI report.**
   - Run the investigation and watch the agent steps and tool calls.
   - Every claim has citations; click one to see the record.
   - The header shows claims, flagged, hallucination rate, confidence, cost and trace.
   - There is a *Limitations* section.
7. **Decision.** Approve the hold with a note, review the report, record the decision with a rationale, then verify the audit chain.
8. **AI Ops and scale.** Cost per case, hallucination trend and evaluation results (94/94 deterministic checks, rule precision and recall 1.0), then the production architecture.

### Synthetic scenarios

| Case | Scenario | Exercises |
|---|---|---|
| CASE-24051 | Headline: account takeover, mule chain | trail, attribution, 9 signals, holds |
| CASE-24044 | Job scam, **Hindi** statement, mixed funds | attribution ranges diverge, translation |
| CASE-24031 / 24038 | Earlier victims of the same mule | shared beneficiary, mule ring |
| CASE-24047 | Marketplace (merchant/hub) | merchant endpoint, not-evaluable rules |
| CASE-24042 | Reversal then resend | reversal handling, R8 |
| CASE-24039 | Round-trip cycle | cycle detection |
| CASE-24049 | Screenshot contradicts ledger, prompt injection | evidence contradiction, injection defence |
| CASE-24033 | Ordinary subscription dispute | no false signals |
| CASE-24027 | No auth logs, reported late | not-evaluable ≠ clear, policy needs information |
| CASE-24045 | Two source systems disagree on amount | multi-source provenance, contradiction |

---

## Data schema (core tables)

| Table | Contents |
|---|---|
| `transactions` | Money as BIGINT minor units, status, channel, UTR reference and time. The `sources` field keeps every merged source record. |
| `accounts`, `institutions`, `devices`, `auth_events`, `customers` | The ledger world |
| `dispute_cases`, `case_notes`, `evidence_items`, `evidence_requests`, `holds` | The case workflow |
| `risk_flags`, `rule_versions` | Signals and versioned rule parameters |
| `ai_runs`, `ai_calls`, `reports` | Every AI run and call: tokens, cost, latency, snapshot hash, prompt and rule versions, claims and verdicts |
| `audit_events` | Hash-chained audit per case |
| `policies`, `eval_runs` | Synthetic policy library, ground truth and evaluation results |

## Security and privacy

**Implemented:**
- bcrypt password hashes; JWT in an httpOnly, SameSite=Strict, Secure cookie; login lockout
- Role-based and **case-level** authorisation. Another investigator's case returns 404, so case IDs cannot be probed.
- Validated inputs and server-side limits on trace depth, time window and node cap. ORM-only queries. No free-form query reaches the UI or the LLM.
- Uploads are type-sniffed against an allow-list, capped at 5 MB, hashed and stored write-once. Downloads go through an access-checked, audited route.
- Account numbers, emails, UPI IDs and IPs are redacted in logs. Error responses never include record contents.
- Customer and document text is fenced as untrusted in prompts. Prompt injection is detected, and the validator blocks injected conclusions.
- Linked cases expose only ID, status and category, never another customer's statement.

**Not implemented (prototype):**
- MFA
- KMS field-level encryption
- DLP scanning
- real bank integrations (the `LedgerSource` adapter interface is defined)
- automated evidence deletion (only the retention setting exists)

## Limitations

- Attribution is balance arithmetic over this bank's records. It cannot show who controlled funds, and it ends where visibility ends.
- Rules are signals for review with stated limitations. They are not a fraud model, and there is no labelled real-world data to train one.
- The policy library and SLA values are synthetic and modelled on public guidance. Verify them before any real use.
- AI token confidence (from average log-probability) is a coarse proxy. Report confidence comes from claim verification.
- AI cost uses list prices from the configured price table. Unpriced models are reported, never silently costed.

## Next steps after the MVP

1. Real-time ingest (Pub/Sub, Dataflow) and Spanner Graph serving for production volumes.
2. Cross-bank trail and hold requests through the national cyber-fraud reporting process.
3. Supervised models trained on investigator-labelled outcomes. The rules stay as explanations.
4. Investigator feedback loop on claim reviews, to tune prompts and the judge.
5. MFA, field-level encryption and retention automation.
