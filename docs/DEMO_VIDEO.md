# Demo video script (target 2:50, hard limit 3:00)

Record at 1440×900, light theme, browser zoom 100%, in two browser profiles: one signed in as `cust.priya`
(customer portal), one as `sup.meera` (bank view).

## Before the take (do this 30 minutes ahead, not just before)

1. **Fresh data.** As `admin`, open **AI & system health** and run **Reset demo data**. This restarts SLA clocks and
   the golden hour, and removes any payments dated after today.
2. **AI warm-up.** Run the AI investigation on **CASE-24051**. Open **Evidence** and analyse the receipt on CASE-24051
   and the screenshot on **CASE-24049**. Check that the report says **Verified**, and in **AI & system health → Recent
   AI calls** that the calls are `ok`. If you see `429 RESOURCE_EXHAUSTED`, Gemini 3.1 Pro is short of capacity: the
   gateway now retries it once and then uses Gemini 3.8 Flash, so just run it again.
3. **Proof file.** Keep a screenshot of a UPI payment (PNG) on the desktop to upload in the customer chat.
4. Close the case assistant panel and any open accordions.

| Time | Screen | Narration (spoken) |
|---|---|---|
| 0:00–0:10 | Customer portal home (Priya) | "Priya sees ₹50,000 leave her account that she never sent. With real-time payments, that money can be three accounts away in minutes." |
| 0:10–0:35 | Chat with our assistant → pick the payment → "I didn't make this payment" → OTP: No → Today → description → SMS → add the screenshot → Check your dispute → Submit | "She raises it in the bank's app. The assistant asks one question at a time and she taps answers, so every dispute lands mapped to the right account and payment. It asks for proof — she adds the bank's screenshot — checks the summary card and submits." |
| 0:35–0:45 | Bank view: Case queue → the new case at the top | "On the bank side it's already a case: customer, payment, category, SLA clocks and priority set. No re-keying." |
| 0:45–1:00 | CASE-24051 Overview: "At a glance", six separate checks | "This is the investigation for that kind of dispute. P1, and it says why. Six separate checks — warning signs, evidence, records, tracing, policy, AI — and deliberately no single trust score." |
| 1:00–1:25 | Money trail | "The trail is rebuilt from ledger records in time order: fifty thousand to a nine-day-old account, then split — thirty thousand to Sunil, twenty thousand to another bank, where our visibility ends, and we say so. Rahul already held ₹1,200, so balance arithmetic proves at least ₹28,800 of the transfer to Sunil is the disputed money. That's derived. Where the ledger can't force it, we say inferred." |
| 1:25–1:40 | Warning signs → open "Failed logins" | "Fifteen explainable warning signs. Each shows the records behind it: four failed logins, then an OTP from a device first seen fourteen minutes earlier — the same device as another victim's account. Signs prompt review; they are not proof." |
| 1:40–1:55 | Evidence (CASE-24049) | "Gemini reads the customer's screenshot, but code compares it with the ledger. Here the screenshot says ₹45,000 against a ₹50,000 record — a contradiction. And the hidden note telling the AI to approve the refund? Detected and ignored." |
| 1:55–2:20 | AI report (CASE-24051) | "A LangGraph agent explores the trail with fixed tools and Gemini writes the report. Every sentence cites a record. Code checks every ID, amount and time; a Gemini judge fact-checks each claim. Thirty-five claims, all confirmed, zero not backed by records — measured on every report, with its cost." |
| 2:20–2:35 | Linked cases → "Money recovered from shared accounts" | "Three disputes traced money into Rahul's account, and together their holds ask for ₹3,600 — but only ₹1,200 is there. FundTrace shows the money once and splits it fairly. Every figure has a calculation record anyone can recompute." |
| 2:35–2:50 | AI & system health | "And we run the AI responsibly: cost, latency and errors per call, 104 of 104 ground-truth checks, investigator agreement with the AI, and field encryption with Cloud KMS. All on Gemini, LangGraph and Cloud Run." |
| 2:50–3:00 | Title slide | "FundTrace: follow the money, show the proof, mark the guesses. The investigator decides." |

**Backup:** if Gemini fails during the take, the report is built "facts only" and says so — that shows the
"Not analysed" principle. Cut to the report generated in step 2.
