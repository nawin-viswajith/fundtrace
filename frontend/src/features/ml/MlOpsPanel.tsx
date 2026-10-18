/* AI & system health: the behaviour model's card and its synthetic hold-out evaluation.
   A supervisor/admin can run a fresh hold-out on demand; everyone with staff access can see the last one. */
import type { ReactNode } from "react";
import { FlaskConical } from "lucide-react";
import { Card, EmptyState, ErrorState, InlineError, LoadingBlock, Note, Time } from "../../components/Primitives";
import { Chip } from "../../components/Chip";
import { formatInt, formatPct } from "../../lib/format";
import { useOpsMl, useRunMlEvaluation, type HoldoutMetrics } from "./api";

function pct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : formatPct(v, 0);
}

function rangeText(agg: { mean: number | null; min: number | null; max: number | null }): string {
  if (agg.mean === null) return "—";
  return `${pct(agg.mean)} (${pct(agg.min)}–${pct(agg.max)})`;
}

export default function MlOpsPanel({ canRun }: { canRun: boolean }) {
  const q = useOpsMl();
  const run = useRunMlEvaluation();

  if (q.isLoading) return <LoadingBlock label="Loading the behaviour model" lines={6} />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load the behaviour model" />;
  if (!q.data) return null;
  const { model_card: card, holdout, holdout_running } = q.data;

  return (
    <>
      <Card title="Behaviour model (machine learning)" subtitle={card.question} className="ml-card">
        <Note tone="info">
          A separate signal from the warning signs. It never changes a rule, priority, score or decision.{" "}
          <strong>Unusual is not fraud.</strong>
        </Note>
        <div className="kpi-grid kpi-grid-sm">
          <Kpi label="Accounts scored" value={formatInt(card.accounts_scored)} sub={`of ${card.window_days}-day ledger window`} />
          <Kpi label="Model" value={card.type} />
          <Kpi label="Trained" value={card.trained_at ? <Time iso={card.trained_at} seconds /> : "—"} />
          <Kpi label="Fit time" value={`${card.fit_seconds}s`} />
        </div>
        <dl className="kv">
          <div className="kv-row"><dt>Training data</dt><dd className="small">{card.training}</dd></div>
          <div className="kv-row"><dt>How the score works</dt><dd className="small">{card.how_scores_work}</dd></div>
          <div className="kv-row"><dt>How reasons work</dt><dd className="small">{card.how_reasons_work}</dd></div>
          <div className="kv-row"><dt>Contamination setting</dt><dd className="small">{card.contamination_note}</dd></div>
          <div className="kv-row"><dt>Not scored</dt><dd className="small">{card.accounts_not_scored.merchant} merchant, {card.accounts_not_scored.high_activity} high-activity accounts</dd></div>
        </dl>
        <h4 className="h-sub">Features (what it measures)</h4>
        <div className="table-wrap">
          <table className="table table-compact">
            <thead><tr><th scope="col">Measure</th><th scope="col">What it means</th><th scope="col">Bank's typical value</th></tr></thead>
            <tbody>
              {card.features.map((f) => (
                <tr key={f.key}>
                  <td data-label="Measure">{f.label}</td>
                  <td data-label="Meaning" className="small">{f.description}</td>
                  <td data-label="Typical" className="num">{f.typical ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h4 className="h-sub">Limitations</h4>
        <ul className="plain-list small muted">
          {card.limitations.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      </Card>

      <Card
        title="Behaviour model: hold-out evaluation"
        subtitle="Fresh synthetic worlds (different random seeds, isolated databases), never the live data. Synthetic hold-out, not real-world performance."
        actions={
          canRun ? (
            <button type="button" className="btn btn-secondary" onClick={() => run.mutate()} disabled={run.isPending || holdout_running}>
              <FlaskConical size={15} aria-hidden="true" /> {run.isPending || holdout_running ? "Running…" : "Run hold-out evaluation"}
            </button>
          ) : undefined
        }
      >
        <InlineError error={run.error} />
        {!holdout ? (
          <EmptyState title="No hold-out run yet">
            {canRun ? "Run the hold-out evaluation to score the behaviour model and rules on fresh synthetic worlds." : "A supervisor can run this."}
          </EmptyState>
        ) : (
          <HoldoutBody m={holdout.metrics} runId={holdout.id} startedAt={holdout.started_at} />
        )}
      </Card>
    </>
  );
}

function Kpi({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <div className="kpi card">
      <span className="kpi-label">{label}</span>
      <span className="kpi-value num">{value}</span>
      {sub && <span className="kpi-sub">{sub}</span>}
    </div>
  );
}

function HoldoutBody({ m, runId, startedAt }: { m: HoldoutMetrics; runId: number; startedAt: string }) {
  const det = m.rules.detection_fraud_with_trail;
  const alarm = m.rules.false_alarm_merchant_and_processing;
  return (
    <div className="stack">
      <p className="small muted">
        Run #{runId} · <Time iso={startedAt} /> · {m.seeds.length} seeds × {m.cases_per_seed} generated cases · {m.seconds}s
      </p>
      <h4 className="h-sub">Behaviour model: ranking fraud accounts (no labels used to train it)</h4>
      <div className="kpi-grid kpi-grid-sm">
        <Kpi label="ROC-AUC" value={rangeText(m.ml.roc_auc)} sub="mean (min–max over seeds)" />
        <Kpi label="Precision @ k" value={rangeText(m.ml.precision_at_k)} sub="k = number of fraud accounts" />
        <Kpi label="Precision @ 10" value={rangeText(m.ml.precision_at_10)} />
        <Kpi label="Found at 'unusual' or higher" value={rangeText(m.ml.recall_unusual_or_higher)} sub="of fraud accounts" />
        <Kpi
          label="Without account age"
          value={rangeText(m.ml_without_account_age.roc_auc)}
          sub="ROC-AUC with that one feature removed"
        />
      </div>
      <h4 className="h-sub">Warning signs: detection by category (demo-data generator, a different code path)</h4>
      <div className="kpi-grid kpi-grid-sm">
        <Kpi label="Fraud with a trail" value={pct(det.rate)} sub={`${det.k}/${det.cases} cases, 95% CI ${pct(det.ci95[0])}–${pct(det.ci95[1])}`} />
        <Kpi label="Merchant / processing-error" value={pct(alarm.rate)} sub={`${alarm.k}/${alarm.cases} false alarms, 95% CI ${pct(alarm.ci95[0])}–${pct(alarm.ci95[1])}`} />
      </div>
      <div className="table-wrap">
        <table className="table table-compact">
          <thead><tr><th scope="col">Category</th><th scope="col" className="ta-r">Cases</th><th scope="col" className="ta-r">With a high-concern sign</th><th scope="col">95% CI</th></tr></thead>
          <tbody>
            {m.rules.per_category.map((c) => (
              <tr key={c.category}>
                <td data-label="Category">{c.label}</td>
                <td data-label="Cases" className="ta-r num">{formatInt(c.cases)}</td>
                <td data-label="With a high sign" className="ta-r num">{c.with_high_signal} / {c.cases}</td>
                <td data-label="95% CI" className="small num">{pct(c.ci95[0])}–{pct(c.ci95[1])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h4 className="h-sub">Caveats</h4>
      <ul className="plain-list small muted">
        {m.caveats.map((c, i) => (
          <li key={i}>{c}</li>
        ))}
      </ul>
      <p className="small muted">
        <Chip tone="neutral" size="sm">{m.label}</Chip>
      </p>
    </div>
  );
}
