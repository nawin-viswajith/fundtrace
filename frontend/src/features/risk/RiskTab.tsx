import { Eye, RefreshCw, Info } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { useRisk, useInvalidateCase } from "../../api/hooks";
import { api } from "../../api/endpoints";
import { useWorkspace } from "../case/workspace";
import { Card, EmptyState, ErrorState, InlineError, LoadingBlock, Note } from "../../components/Primitives";
import { RuleStatusChip, SeverityChip } from "../../components/Chip";
import { IdChip } from "../../components/Domain";
import { useToast } from "../../components/Toast";
import { isGraphId } from "../../lib/labels";
import { humanize } from "../../lib/format";
import type { RuleResult } from "../../types/api";

const STATUS_ORDER: Record<string, number> = { triggered: 0, not_evaluable: 1, not_triggered: 2 };
const SEV_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };

export function RiskTab() {
  const { caseId } = useWorkspace();
  const q = useRisk(caseId);
  const invalidate = useInvalidateCase(caseId);
  const toast = useToast();
  const evalM = useMutation({
    mutationFn: () => api.evaluateRisk(caseId),
    onSuccess: async (r) => {
      await invalidate();
      toast.show(`Rules re-evaluated: ${r.summary.triggered} triggered, ${r.summary.not_evaluable} not evaluable`);
    },
  });

  if (q.isLoading) return <LoadingBlock label="Loading risk signals" lines={8} />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load risk signals" />;
  const d = q.data;
  if (!d) return null;
  const rules = [...d.rules].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) || (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9),
  );

  return (
    <div className="stack-lg">
      <div className="tab-intro">
        <Note tone="info" icon={<Info size={15} />}>
          <strong>Signals prompt review; they are not proof.</strong> Each card shows the facts behind the signal, the thresholds used, and what the
          rule cannot tell you. “Not evaluable” means the data was missing — never that the case is clear.
        </Note>
        <div className="tab-intro-actions">
          <span className="muted small">
            Ruleset <code>{d.ruleset_version}</code> · {d.summary.triggered} triggered · {d.summary.not_triggered} not triggered ·{" "}
            {d.summary.not_evaluable} not evaluable
          </span>
          <button type="button" className="btn btn-secondary" onClick={() => evalM.mutate()} disabled={evalM.isPending}>
            <RefreshCw size={15} aria-hidden="true" className={evalM.isPending ? "spin" : ""} /> {evalM.isPending ? "Evaluating…" : "Re-evaluate rules"}
          </button>
        </div>
      </div>
      <InlineError error={evalM.error} />
      {rules.length === 0 ? (
        <EmptyState title="No rules evaluated">The rule catalogue returned no results for this case.</EmptyState>
      ) : (
        <div className="rule-grid">
          {rules.map((r) => (
            <RuleCard key={r.rule_id} rule={r} />
          ))}
        </div>
      )}
    </div>
  );
}

export function RuleCard({ rule: r }: { rule: RuleResult }) {
  const { showOnGraph } = useWorkspace();
  const graphIds = r.source_ids.filter(isGraphId);
  return (
    <Card
      as="article"
      className={`rule-card rule-${r.status}`}
      title={
        <span className="rule-title">
          {r.name}
        </span>
      }
      subtitle={
        <span className="mono small">
          {r.rule_id} · v{r.version}
        </span>
      }
      actions={
        <span className="rule-chips">
          <SeverityChip severity={r.severity} size="sm" />
          <RuleStatusChip status={r.status} size="sm" />
        </span>
      }
    >
      {r.facts.length > 0 && (
        <section>
          <h4 className="h-sub">Facts</h4>
          <ul className="fact-list">
            {r.facts.map((f, i) => (
              <li key={i}>
                <span>{f.text}</span>
                {f.source_ids.length > 0 && (
                  <span className="id-list">
                    {f.source_ids.map((s) => (
                      <IdChip key={s} id={s} />
                    ))}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {r.status === "not_evaluable" && (
        <Note tone="warn">
          <strong>Data missing:</strong> {r.missing_fields.length ? r.missing_fields.join("; ") : "required inputs were not available"}. This is
          not a negative finding.
        </Note>
      )}
      {Object.keys(r.params).length > 0 && (
        <section>
          <h4 className="h-sub">Thresholds</h4>
          <dl className="param-list">
            {Object.entries(r.params).map(([k, v]) => (
              <div key={k}>
                <dt>{humanize(k)}</dt>
                <dd className="num">{String(v)}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}
      {r.limitations.length > 0 && (
        <section>
          <h4 className="h-sub">What this does not tell you</h4>
          <ul className="plain-list small muted">
            {r.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </section>
      )}
      <div className="rule-foot">
        <p className="small">
          <strong>Suggested step:</strong> {r.suggested_step}
        </p>
        {graphIds.length > 0 && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => showOnGraph(r.source_ids)}>
            <Eye size={14} aria-hidden="true" /> Show on graph
          </button>
        )}
      </div>
    </Card>
  );
}
