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
| **Gemini proposes, the ledger proves** | On the Money trail tab, Gemini reads the trail and suggests hypotheses in plain language — a typology (fan-out, layering, round-trip, cash-out, mule reuse), a flow between two accounts, money still at this bank. Every hypothesis is immediately checked by **deterministic code** against the same attribution bounds and graph, never by the model, and comes back *Proven by the records*, *Possible*, *Ruled out by the records*, *Can't check*, or *Invented — rejected* if it names a record that does not exist. An investigator can also type a plain question ("Did at least ₹25,000 reach Sunil?"); Gemini only translates it into a check, and the answer sentence is written by code from the result. | The most "AI" part of the product is also the most rigorously checked: nothing the model proposes reaches the investigator unverified, and it never does the arithmetic. |
| **Five provenance labels** | Every node, edge and report claim is *Confirmed*, *Derived*, *Inferred*, *Unknown* or *Contradictory*. | Inferred links are never shown as facts. |
| **Honest trail endpoints** | A trail stops for one of several reasons: *visibility ends* (another bank or cash), *merchant*, *high-activity hub*, *cycle*, *depth limit* or *result cap*. Each stop is explicit and expandable. | Missing data is shown as unknown, not as absent. |
| **Agentic, bounded AI** | A LangGraph agent with Gemini chooses which trail branches to explore using **fixed, parameter-checked tools**. It can never run free-form queries. | Real agency without open-ended data access. |
| **Hallucination defence** | 1. A deterministic validator checks the report: cited IDs exist, every ₹ amount and time matches the cited record, no "proves fraud" or "customer is liable" language, and flow-through claims are never marked verified.<br>2. One redraft with feedback.<br>3. A Gemini judge checks each claim against its cited records.<br>4. A **hallucination rate** and **confidence** are recorded on every report. | Measured trust instead of claimed trust. |
| **Evidence reconciled, not trusted** | Gemini reads receipts and screenshots (multimodal). **Code** then compares the amount, UTR and time with the ledger. Instructions embedded in documents are detected and ignored. | Catches the customer screenshot that shows ₹45,000 when the ledger says ₹50,000, and the prompt-injection attempt hidden in it. |
| **Evidence strength scores** | Every analysed item gets a 0–100 score with a sub-score per category: ledger match, integrity, relevance, provenance, completeness, legibility. Gemini only labels what it sees; fixed weights in code turn the labels into numbers, and a contradiction with the ledger caps the score. Each sub-score lists its reasons. | Investigators see *why* a document is weak, and the score never doubles as a judgement of the customer. |
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
                                   │   → attribution → 15 rules → completeness / consistency / SLA / policy
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
  crypto.py   field-level encryption (AES-256-GCM, Cloud KMS-wrapped key, rotation, backfill)
  services/   graph_store · trace · attribution · rules · ledger · ledger_sources (camt.053/CSV/JSON) · ingest · scoring
              evidence_scoring · policy · workflow · network · storage · mfa · dlp · retention
              ml/ (behaviour model: features, Isolation Forest, synthetic hold-out evaluation)
  ai/         llm (Gemini gateway) · investigator (LangGraph) · tools · validator · facts_report · evidence · copilot · prompts · schemas · snapshot · pricing
  api/        auth (password, Firebase, MFA) · cases · ops · ingest (Pub/Sub push, statement upload)
  seed/       synthetic world S1–S10 + evidence files · loader
  eval/       evaluation harness (ground truth)
backend/tests/   159 tests: trace, attribution, rules, ledger, scenarios, validator, investigator, gateway, API, security/ingest, portal, recovery, calculation record, quality metrics
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
python -m pytest                      # 94 tests
python -m uvicorn app.main:app --port 8000      # seeds synthetic data on first start (SQLite)

# frontend (second terminal)
cd frontend
npm install
npm run dev                           # http://localhost:5173 (proxies /api to :8000)
```

Logins (synthetic demo; the password is also shown on the login page): `inv.asha`, `inv.ravi`
(investigators), `sup.meera` (supervisor), `admin`. Bank customers (customer portal): `cust.priya`,
`cust.kiran`, `cust.kabir`. Password for all: `Investigate@2026`.

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
8. **AI Ops and scale.** Cost per case, hallucination trend and evaluation results (94/94 deterministic checks, rule precision and recall 1.0 — measured on the scenarios we wrote), then the behaviour model's card and its synthetic hold-out (fresh random seeds, not our own scenarios), then the production architecture.

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

## Customer portal (raising a dispute)

Bank customers sign in with their own login (`cust.priya`, `cust.kiran`, `cust.kabir`) and land in a separate,
simpler portal at `/portal`. They can only see their own accounts, payments and disputes, and a customer login
gets 403 on every staff API.

They raise a dispute in one of two ways, and both use the same fixed options so every dispute maps cleanly into
the bank's case file:
- **Form:** a four-step wizard. 1) Pick the payment from your own recent payments. 2) What happened (six fixed
  reasons). 3) Details. 4) Check and submit.
- **Guided chat:** one question at a time, answered with buttons. Nothing is filed until the customer confirms
  the summary. The chat also offers **"Tell us in your own words"**: Gemini reads the customer's free-text story
  and suggests the payment and fixed answers, which the customer still confirms one by one with Yes / No buttons
  (declining any one drops back to the normal, fully manual question) — so the fixed-option integrity of the chat
  is unchanged either way. If AI can't read the story, the chat says so and continues step by step.

The questions:
- what happened (six fixed reasons)
- whether an OTP, PIN or password was shared (fraud reasons only)
- when the customer noticed
- whether a cyber-crime complaint was filed, with its number (fraud reasons only)
- how to contact them

The only free text is the customer's description. OTPs, PINs and card numbers typed into it are hidden
automatically.

The dispute becomes a normal **New** case in the bank's queue, linked to the customer, account and payment. The
reason maps to a category, and SLA deadlines and priority are computed straight away. Investigators see the
customer's answers under their statement, and the AI receives them as untrusted customer statements.

Customers follow their dispute in plain words (Received → Being investigated → Final review → Decided). They see
the bank's deadlines and anything the bank asked them for, and can upload files. They never see risk signals,
other accounts, staff notes, AI reports or decision rationales.

### Ask Demo Bank (customer assistant)

A Gemini-backed help assistant (`/portal/help`) answers banking and payments FAQs, fraud safety and scam
awareness, how disputes work here, and the signed-in customer's own dispute status — nothing else. Gemini
classifies each question into a fixed set of intents; code enforces the scope and refuses anything else with a
written reply and suggestions, never a bare "no". Answers are grounded in a curated set of help articles
(`backend/app/data/customer_help.yaml`); code retrieves the best-matching articles with a small BM25-style search
and passes only those to Gemini, which must cite the article ids it used. An answer that cites nothing valid,
talks about another customer's dispute, or asks for a secret is dropped for the best article's own summary
instead. Customer text is DLP-masked before it reaches Gemini, and a message that looks like an OTP, PIN or card
number gets a code-written warning. When AI is unavailable, over budget or fails, the assistant answers straight
from the help articles, labelled "From our help articles". The portal home also shows a deterministic **safety
check** (new payees, an unusually large payment, failed sign-ins, a new device) and a rotating scam-awareness tip,
computed from the customer's own data without any AI call.

## Ledger ingest

Ledger records arrive in two ways:
- **Pub/Sub push:** the `fundtrace-ledger` topic pushes to `/api/ingest/pubsub`. The push is signed with an OIDC token from a dedicated service account, and there is a dead-letter topic.
- **File upload:** an admin uploads a statement on the AI Ops page.

Supported formats: ISO 20022 **camt.053** bank statements, CSV, and FundTrace JSON. Every delivery is logged (new, merged, duplicate, rejected, cases re-assessed).

- **Duplicates are harmless.** A redelivered message changes nothing.
- **Reports from several systems become one payment.** The same payment reported by another source system is merged into the existing transaction, and any disagreement between the systems is kept.
- **Unknown counterparties never fail a delivery.** They become external placeholder accounts, and full account numbers are not stored.
- **Holds update at once.** Open cases whose trail window covers the new records are re-assessed immediately, so hold recommendations reflect onward transfers as they arrive.

```bash
cd backend
python -m scripts.publish_ledger --project P --format iso20022.camt.053 ../docs/samples/statement-camt053.xml
```

## Recovery, calculation records and quality checks

- **Shared-account recovery split** (Linked cases page). When several open disputes traced money into the same
  account, their hold suggestions can add up to more than the account holds. FundTrace shows the money actually
  there once and splits it pro rata between the cases, by money traced in or by amount disputed. Paise are rounded
  with the largest-remainder method so the parts add up exactly, and no case gets more than its own claim. A
  supervisor can record a split with a note; it is kept on file and never moves money.
- **Calculation record** (Money trail tab). Every attribution figure comes with a record: the four methods and their
  versions, the trace settings, every transaction and opening balance used, and checks on the arithmetic (money
  conserved, no negative balances, nothing counted twice, source systems agree, bounds in order, records complete).
  A SHA-256 fingerprint and a "recalculate" button show that the same inputs give the same result. The record can be
  downloaded as JSON (audited).
- **Reviewer and rule quality** (AI & system health page). How often investigators agree with the AI fact-check
  (agreement and Cohen's kappa, shown from 10 reviewed claims), and how often each warning sign appears on cases that
  were later declined, so supervisors can see which signs create review work without changing the outcome.
- **Three more warning signs:** R13 many payments in a short time, R14 first payment to this beneficiary (not applied
  to merchants or busy business accounts), R15 payments just below a review limit.

## Machine learning: a behaviour model, honestly measured

A judge who hears "precision and recall 1.0" should ask whether that was measured on scenarios the team wrote
itself — ours was. So alongside the 15 explainable rules there is one real, unsupervised model, and a less
circular way of testing both:

- **Behaviour model** (`backend/app/services/ml/`). A scikit-learn Isolation Forest scores every in-bank personal
  account 0–100 on how unlike the bank's other accounts it behaves (account age, how many different people pay
  in/out, how much of the money received leaves again within an hour, how fast, the biggest fan-out within two
  hours, how many one-time payers, devices used and shared with other accounts). No labels are used anywhere —
  the model has never been told which accounts are mules or victims. Merchants and high-activity accounts are
  measured but excluded from scoring (their patterns are normal business). Each score comes with up to three
  plain-language reasons (the account's value vs. the bank's typical value) and a model card (features,
  settings, limitations). It is fitted once per ledger state and cached in memory. **It is a separate signal, not
  a 16th rule:** it never changes a warning sign, priority, score or decision — "unusual" is never "fraud".
  Shown on a case's Warning signs tab for accounts on the money trail, and as a model card on the AI & system
  health page.
- **Hold-out evaluation** (`backend/app/services/ml/holdout.py`, `GET/POST /api/ops/ml*`). Rather than scoring the
  hand-written scenarios again, this builds fresh synthetic banks at several random seeds and adds disputes
  through the demo-data generator (a different code path from the scenarios), each in its own isolated in-memory
  database. It then measures, without using labels to train, how well the behaviour score ranks the accounts
  known to be mules (ROC-AUC, precision@k, mean with min/max over seeds — typically ROC-AUC ≈ 0.75–0.80, well
  above chance but far from the scenario-only 1.0), and measures the rules' detection by category with Wilson 95%
  confidence intervals. Labelled throughout as a **synthetic hold-out, not real-world performance**.

## Data schema (core tables)

| Table | Contents |
|---|---|
| `transactions` | Money as BIGINT minor units, status, channel, UTR reference and time. The `sources` field keeps every merged source record. |
| `accounts`, `institutions`, `devices`, `auth_events`, `customers` | The ledger world |
| `dispute_cases`, `case_notes`, `evidence_items`, `evidence_requests`, `holds` | The case workflow |
| `risk_flags`, `rule_versions` | Signals and versioned rule parameters |
| `ai_runs`, `ai_calls`, `reports` | Every AI run and call: tokens, cost, latency, snapshot hash, prompt and rule versions, claims and verdicts |
| `audit_events` | Hash-chained audit per case |
| `ingest_events` | One row per ledger delivery (Pub/Sub message or uploaded file) and its outcome |
| `recovery_allocations` | Recorded shared-account recovery splits (who recorded it, basis, shares, note) |
| `policies`, `eval_runs` | Synthetic policy library, ground truth and evaluation results |

## Security and privacy

**Implemented:**
- bcrypt password hashes; JWT in an httpOnly, SameSite=Strict, Secure cookie; login lockout
- **MFA**: authenticator-app codes (TOTP, RFC 6238) with replay protection and 10 single-use recovery codes.
  `MFA_REQUIRED_ROLES` makes it mandatory per role (those users enrol at sign-in). Admins can reset a lost device (audited).
- **Google sign-in** through Firebase Auth (optional). A verified email maps only to an existing user; roles are never granted automatically.
- **Field-level encryption**: customer names, account holder names, customer statements, notes, decision rationales and
  AI-extracted evidence values are encrypted (AES-256-GCM, bound to their column). On GCP the data key is wrapped by
  Cloud KMS (90-day key rotation); several data keys can be configured for rotation. Older plaintext rows are encrypted at start-up.
- **DLP scanning**: card numbers (Luhn), Aadhaar (Verhoeff), written-down OTPs/PINs, PAN, IFSC, email, phone and UPI ids.
  Card/Aadhaar/OTP values are masked in case notes before storage and in customer text before it reaches Gemini.
  Uploaded files are scanned (Cloud DLP reads images and PDFs when `DLP_BACKEND=gcp`); findings record types and counts, never values.
- Role-based and **case-level** authorisation. Another investigator's case returns 404, so case IDs cannot be probed.
- Validated inputs and server-side limits on trace depth, time window and node cap. ORM-only queries. No free-form query reaches the UI or the LLM.
- Uploads are type-sniffed against an allow-list, capped at 5 MB, hashed and stored write-once. Downloads go through an access-checked, audited route.
- Account numbers, emails, UPI IDs and IPs are redacted in logs. Error responses never include record contents.
- Customer and document text is fenced as untrusted in prompts. Prompt injection is detected, and the validator blocks injected conclusions.
- Linked cases expose only ID, status and category, never another customer's statement.

**Not implemented (prototype):**
- live connections to a real bank's systems. The ingest path is built for them: ISO 20022 camt.053, CSV and JSON
  adapters, Pub/Sub push with signed-token checks, idempotent redelivery, cross-source merging and placeholder
  accounts for unknown counterparties. A bank would publish its statement or switch feed to the ledger topic.
- scheduled evidence-retention runs (the retention flow exists; an admin runs it on demand)

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
5. Scheduled retention runs (an admin can run retention on demand today) and live bank connections on the ingest path.
