/* "AI ideas about where the money went — checked against the bank's records" (Money trail tab).

   Gemini proposes; the ledger proves. Every card shows a plain-language idea, who suggested it (the
   AI or the system's fixed detectors when AI is unavailable), and its checks with the verdict the
   deterministic verifier reached — never a number or a verdict written by the AI itself. */

import { useState, type FormEvent } from "react";
import { Bot, Cpu, RefreshCw, Search } from "lucide-react";
import { IdList } from "../../components/Domain";
import { ErrorState, Note, Spinner } from "../../components/Primitives";
import { errorMessage } from "../../api/client";
import {
  TYPOLOGY_LABELS,
  VERDICT_HINTS,
  VERDICT_LABELS,
  useAskLedger,
  useHypotheses,
  useRunHypotheses,
  type CheckResult,
  type Hypothesis,
  type Verdict,
} from "./api";

export function VerdictChip({ verdict }: { verdict: Verdict }) {
  return (
    <span className={`verdict-chip verdict-chip-${verdict}`} title={VERDICT_HINTS[verdict]}>
      {VERDICT_LABELS[verdict]}
    </span>
  );
}

function CheckRow({ check }: { check: CheckResult }) {
  return (
    <li className="hyp-check">
      <div className="hyp-check-head">
        <VerdictChip verdict={check.verdict} />
        <span className="small">{check.claim}</span>
      </div>
      <p className="small muted">{check.summary}</p>
      {check.figures.length > 0 && (
        <dl className="hyp-figures">
          {check.figures.map((f, i) => (
            <div key={i}>
              <dt>{f.label}</dt>
              <dd className="num">{f.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {check.record_ids.length > 0 && (
        <div className="hyp-ids">
          <IdList ids={check.record_ids} />
        </div>
      )}
    </li>
  );
}

function HypothesisCard({ h }: { h: Hypothesis }) {
  return (
    <li className={`hyp-card hyp-card-${h.verdict}`}>
      <div className="hyp-card-head">
        <span className={`hyp-source hyp-source-${h.source}`}>
          {h.source === "ai" ? <Bot size={13} aria-hidden="true" /> : <Cpu size={13} aria-hidden="true" />}
          {h.source === "ai" ? "Suggested by AI (Gemini)" : "Suggested by the system (AI unavailable)"}
        </span>
        <VerdictChip verdict={h.verdict} />
      </div>
      <p className="hyp-statement">{h.statement}</p>
      <p className="small muted">{h.rationale}</p>
      <p className="muted small">Pattern: {TYPOLOGY_LABELS[h.typology] ?? h.typology}</p>
      {h.verdict === "invented" && h.invented_ids.length > 0 && (
        <Note tone="bad">
          This idea mentions {h.invented_ids.join(", ")}, which is not in this case's records. It is rejected, not hidden.
        </Note>
      )}
      {h.checks.length > 0 && (
        <ul className="hyp-checks" aria-label="Checks on this idea">
          {h.checks.map((c, i) => (
            <CheckRow key={i} check={c} />
          ))}
        </ul>
      )}
    </li>
  );
}

function AskTheLedger({ caseId }: { caseId: string }) {
  const [question, setQuestion] = useState("");
  const ask = useAskLedger(caseId);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (q.length < 3) return;
    ask.mutate(q);
  };

  return (
    <div className="ask-ledger">
      <h4 className="plain-sub">Ask the ledger</h4>
      <p className="small muted">
        Type a plain question about the disputed money, for example "Did at least 25,000 reach Sunil?" or "Is any of the money still at this
        bank?". AI turns it into a check; the bank's records answer it.
      </p>
      <form onSubmit={onSubmit} className="ask-ledger-form">
        <label htmlFor="ask-ledger-input" className="sr-only">
          Your question
        </label>
        <input
          id="ask-ledger-input"
          type="text"
          className="input"
          placeholder="Did at least ₹25,000 reach Sunil?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          minLength={3}
          maxLength={300}
        />
        <button type="submit" className="btn btn-secondary btn-sm" disabled={ask.isPending || question.trim().length < 3}>
          <Search size={14} aria-hidden="true" />
          {ask.isPending ? "Checking…" : "Ask"}
        </button>
      </form>
      <div aria-live="polite" className="ask-ledger-result">
        {ask.error != null && <Note tone="bad">Could not ask the ledger: {errorMessage(ask.error)}</Note>}
        {ask.data && (
          <div className={`ask-ledger-answer ask-ledger-answer-${ask.data.status}`}>
            {ask.data.verdict && <VerdictChip verdict={ask.data.verdict} />}
            <p>{ask.data.answer}</p>
            {ask.data.checks.length > 0 && (
              <ul className="hyp-checks">
                {ask.data.checks.map((c, i) => (
                  <CheckRow key={i} check={c} />
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function HypothesesSection({ caseId }: { caseId: string }) {
  const q = useHypotheses(caseId);
  const run = useRunHypotheses(caseId);

  const hasRun = q.data && q.data.status !== "none";
  const hyps = q.data?.hypotheses ?? [];

  return (
    <section className="hyp-section" aria-labelledby="hyp-heading">
      <header className="plain-intro">
        <h3 id="hyp-heading" className="plain-intro-title">
          AI ideas about where the money went — checked against the bank's records
        </h3>
        <p className="small muted">
          Gemini suggests ideas about the disputed money's path. It never states an amount as fact: every idea is then checked by the bank's
          own calculation, which proves, allows, rules out, or rejects it as invented.
        </p>
      </header>

      <div className="hyp-toolbar">
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => run.mutate()} disabled={run.isPending || q.isLoading}>
          <RefreshCw size={14} aria-hidden="true" />
          {run.isPending ? "Running…" : hasRun ? "Run again" : "Run"}
        </button>
        {q.data?.generated_at && <span className="muted small">Last run from the records as they were then.</span>}
        {q.data?.status === "ai_unavailable" && (
          <span className="muted small">AI was not available{q.data.reason ? ` (${q.data.reason})` : ""}; showing the system's own ideas.</span>
        )}
      </div>

      <div aria-live="polite">
        {q.isLoading && <Spinner label="Loading ideas about the money trail" />}
        {q.error != null && <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load hypotheses" />}
        {run.error != null && <Note tone="bad">Could not run the AI ideas: {errorMessage(run.error)}</Note>}
        {!q.isLoading && q.error == null && !hasRun && (
          <p className="small muted">No ideas have been generated for this case yet. Select "Run" to ask Gemini, or to see the system's ideas if AI is unavailable.</p>
        )}
        {hyps.length > 0 && (
          <ul className="hyp-list">
            {hyps.map((h, i) => (
              <HypothesisCard key={i} h={h} />
            ))}
          </ul>
        )}
      </div>

      <AskTheLedger caseId={caseId} />
    </section>
  );
}
