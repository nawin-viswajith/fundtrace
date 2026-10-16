# Demo video script (target 2:50, hard limit 3:00)

Record at 1440×900, light theme, browser zoom 100%. Log in as `sup.meera` before recording; start on the case queue.
Before the take: in AI Ops, run **Reset demo data** (admin) so SLA clocks and the golden hour are live,
then run the AI investigation once on CASE-24051 and analyse its evidence, so the report exists if Gemini is slow during the take.

| Time | Screen | Narration (spoken) |
|---|---|---|
| 0:00–0:15 | Queue | "A customer says: I didn't make this ₹50,000 UPI payment. With real-time payments, that money can be three accounts away in minutes. FundTrace helps an investigator follow it — and be honest about what the records do and don't prove." |
| 0:15–0:30 | Open CASE-24051, Overview | "It's P1, and the system says why: high value, high-severity signals, and a golden hour — funds may still sit in a visible account. Six dimensions, deliberately separate. No black-box trust score." |
| 0:30–1:05 | Trail graph | "This is the trail rebuilt from ledger records, in time order. Fifty thousand to a nine-day-old account, then split: thirty thousand to C, twenty thousand to another bank — where our visibility ends, and we say so. Solid lines are confirmed records. Dashed lines are attribution: B already held ₹1,200, so balance arithmetic proves at least ₹28,800 of this transfer is the disputed money — that's derived. Where the ledger can't force it, we call it inferred." |
| 1:05–1:25 | Risk signals → Show on graph | "Every signal shows the facts that triggered it: four failed logins and an OTP from a device first seen on this account fourteen minutes earlier — the same device used on another victim's account. The beneficiary is in two other disputes. Signals prompt review; they are not proof." |
| 1:25–1:45 | Evidence (then CASE-24049 quickly) | "Gemini reads the customer's screenshot — but code does the comparison with the ledger. Here they match. In this other case, the screenshot says ₹45,000 against a ₹50,000 ledger record: a contradiction, on the graph. And the hidden note telling the AI to approve a refund? Detected and ignored." |
| 1:45–2:20 | AI report | "The LangGraph agent explores the trail with fixed tools, drafts a report with Gemini, and every claim cites a record — click one and you see it. A validator checks every ID, amount and time; a judge model fact-checks each claim. We measure it: claims, flags, hallucination rate, confidence, cost per case, and the trace in Cloud Trace. And a section on what this does not prove." |
| 2:20–2:40 | Overview → hold, Actions & audit | "The investigator decides: approve the hold on the account still holding funds, review the report, record the decision. Every step is in a hash-chained audit trail." |
| 2:40–2:55 | AI Ops, then architecture slide | "AI Ops tracks cost, latency, failures and hallucinations per call; our evaluation passes all 94 ground-truth checks. Built on Gemini on Vertex AI, LangGraph, Cloud Run and Cloud SQL — with a path to Spanner Graph and BigQuery for bank scale." |
| 2:55–3:00 | Title | "FundTrace: follow the money, show the proof, mark the guesses." |

Backup: if Gemini is unavailable during recording, show the facts-only report — it demonstrates the "Not analysed" principle — and cut to the pre-generated AI report.
