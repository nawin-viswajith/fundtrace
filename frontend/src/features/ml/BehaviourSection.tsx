/* "Behaviour model (machine learning)": a separate signal from the rules, shown at the bottom of Warning signs.
   It scores accounts on the case's money trail by how unlike the bank's other accounts they behave, with plain
   reasons. It never changes a rule result, priority or decision — see the note and the model's own limitations. */
import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { EmptyState, ErrorState, LoadingBlock, Note } from "../../components/Primitives";
import { useCaseBehaviour, type BehaviourAccount } from "./api";

const BAND_TONE: Record<string, string> = { very_unusual: "bad", unusual: "warn", typical: "good" };

export function BehaviourSection({ caseId }: { caseId: string }) {
  const q = useCaseBehaviour(caseId);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <section className="ml-section" aria-labelledby="ml-section-title">
      <h3 id="ml-section-title" className="h-sub ml-section-title">
        Behaviour model (machine learning)
      </h3>
      <Note tone="info">
        <strong>Unusual is not fraud.</strong> This model has never been told which accounts are mules — it only
        learns what is common for this bank's accounts. Use it to decide where to look, not what to decide.
      </Note>
      {q.isLoading ? (
        <LoadingBlock label="Loading behaviour scores" lines={4} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load behaviour scores" />
      ) : !q.data || q.data.accounts.length === 0 ? (
        <EmptyState title="No accounts to score">There are no in-bank accounts on this case's money trail.</EmptyState>
      ) : (
        <>
          <p className="small muted">
            Compared with {q.data.model.accounts_scored.toLocaleString()} of the bank's other accounts (last{" "}
            {q.data.model.window_days} days, model {q.data.model.version}).
          </p>
          <ul className="ml-acc" aria-label="Account behaviour scores">
            {q.data.accounts.map((a) => (
              <BehaviourRow key={a.account_id} account={a} open={open.has(a.account_id)} onToggle={() => toggle(a.account_id)} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function BehaviourRow({ account: a, open, onToggle }: { account: BehaviourAccount; open: boolean; onToggle: () => void }) {
  const bodyId = `ml-body-${a.account_id}`;
  if (!a.scored) {
    return (
      <li className="ml-row ml-not-scored">
        <div className="ml-head ml-head-static">
          <span className="ml-name mono">{a.account_id}</span>
          <span className="ml-line small muted">{a.label}</span>
          <span className="small muted">{a.not_scored_reason}</span>
        </div>
      </li>
    );
  }
  const tone = BAND_TONE[a.band ?? "typical"] ?? "neutral";
  return (
    <li className={`ml-row ${open ? "is-open" : ""}`}>
      <button type="button" className="ml-head" aria-expanded={open} aria-controls={bodyId} onClick={onToggle}>
        <ChevronRight size={16} aria-hidden="true" className="ml-chevron" />
        <span className="ml-name mono">{a.account_id}</span>
        <span className="ml-line">{a.label}</span>
        <span className={`ml-score tone-${tone}`}>
          {a.score}
          <span className="ml-score-max">/100</span>
        </span>
        <span className={`ml-band tone-${tone}`}>{a.band_label}</span>
      </button>
      {open && (
        <div className="ml-body" id={bodyId}>
          <p className="small">{a.summary}</p>
          {a.no_single_reason ? (
            <p className="small muted">No single measure stands out — the score comes from several smaller differences together.</p>
          ) : (
            <ul className="fact-list">
              {a.reasons.map((r) => (
                <li key={r.key}>{r.text}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}
