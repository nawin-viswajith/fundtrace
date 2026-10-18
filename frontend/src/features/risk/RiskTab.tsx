import { useState } from "react";
import { ChevronRight, Eye, RefreshCw } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { useRisk, useInvalidateCase } from "../../api/hooks";
import { api } from "../../api/endpoints";
import { useWorkspace } from "../case/workspace";
import { EmptyState, ErrorState, InlineError, LoadingBlock, Note } from "../../components/Primitives";
import { IdChip } from "../../components/Domain";
import { useToast } from "../../components/Toast";
import { formatParam, isGraphId, paramLabel } from "../../lib/labels";
import type { RuleResult } from "../../types/api";

const STATUS_ORDER: Record<string, number> = { triggered: 0, not_evaluable: 1, not_triggered: 2 };
const SEV_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };
const STATUS_TEXT: Record<string, { label: string; tone: string }> = {
  triggered: { label: "Found", tone: "bad" },
  not_evaluable: { label: "Can't check — data missing", tone: "warn" },
  not_triggered: { label: "Not found", tone: "good" },
};
const SEVERITY_TEXT: Record<string, string> = { high: "High concern", medium: "Medium concern", low: "Low concern" };

export function RiskTab() {
  const { caseId } = useWorkspace();
  const q = useRisk(caseId);
  const invalidate = useInvalidateCase(caseId);
  const toast = useToast();
  const [open, setOpen] = useState<Set<string>>(new Set());
  const evalM = useMutation({
    mutationFn: () => api.evaluateRisk(caseId),
    onSuccess: async (r) => {
      await invalidate();
      toast.show(`Checks run again: ${r.summary.triggered} found, ${r.summary.not_evaluable} could not be checked`);
    },
  });

  if (q.isLoading) return <LoadingBlock label="Loading risk signals" lines={8} />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load risk signals" />;
  const d = q.data;
  if (!d) return null;
  const rules = [...d.rules].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9) || (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9),
  );
  const allOpen = rules.length > 0 && rules.every((r) => open.has(r.rule_id));
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="stack-lg">
      <Note tone="info">
        <strong>These are warning signs to look at, not proof.</strong> Open a row to see what was found and what to do next. “Can't check”
        means information was missing — it does not mean the case is fine.
      </Note>
      <div className="risk-toolbar">
        <span className="small">
          <strong className="num">{d.summary.triggered}</strong> found · <span className="num">{d.summary.not_evaluable}</span> could not be
          checked · <span className="num">{d.summary.not_triggered}</span> not found
        </span>
        <span className="risk-toolbar-actions">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(allOpen ? new Set() : new Set(rules.map((r) => r.rule_id)))}>
            {allOpen ? "Collapse all" : "Expand all"}
          </button>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => evalM.mutate()} disabled={evalM.isPending}>
            <RefreshCw size={14} aria-hidden="true" className={evalM.isPending ? "spin" : ""} /> {evalM.isPending ? "Checking…" : "Run checks again"}
          </button>
        </span>
      </div>
      <InlineError error={evalM.error} />
      {rules.length === 0 ? (
        <EmptyState title="No checks were run">The rule catalogue returned no results for this case.</EmptyState>
      ) : (
        <ul className="risk-acc" aria-label="Warning signs">
          {rules.map((r) => (
            <RiskRow key={r.rule_id} rule={r} open={open.has(r.rule_id)} onToggle={() => toggle(r.rule_id)} />
          ))}
        </ul>
      )}
      <p className="small muted">
        Rule settings version <code>{d.ruleset_version}</code>. Supervisors can change the settings on the Rules page.
      </p>
    </div>
  );
}

/** One-line plain summary shown on the collapsed row. */
function headline(r: RuleResult): string {
  if (r.status === "not_evaluable") return r.missing_fields.length ? `Missing: ${r.missing_fields[0]}` : "Required information was not available.";
  const facts = r.facts.map((f) => f.text);
  const met = facts.find((t) => /^Threshold met/i.test(t));
  return met ?? facts[facts.length - 1] ?? "";
}

export function RiskRow({ rule: r, open, onToggle }: { rule: RuleResult; open: boolean; onToggle: () => void }) {
  const { showOnGraph } = useWorkspace();
  const graphIds = r.source_ids.filter(isGraphId);
  const st = STATUS_TEXT[r.status] ?? { label: r.status, tone: "neutral" };
  const bodyId = `risk-body-${r.rule_id}`;
  return (
    <li className={`risk-row risk-${r.status} ${open ? "is-open" : ""}`}>
      <button type="button" className="risk-head" aria-expanded={open} aria-controls={bodyId} onClick={onToggle}>
        <ChevronRight size={16} aria-hidden="true" className="risk-chevron" />
        <span className="risk-name">{r.name}</span>
        <span className="risk-line">{headline(r)}</span>
        <span className={`risk-sev sev-${r.severity}`}>{SEVERITY_TEXT[r.severity] ?? r.severity}</span>
        <span className={`risk-status tone-${st.tone}`}>{st.label}</span>
      </button>
      {open && (
        <div className="risk-body" id={bodyId}>
          <div className="risk-cols">
            <section>
              <h4 className="h-sub">What we found</h4>
              {r.facts.length > 0 ? (
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
              ) : (
                <p className="small muted">No details recorded.</p>
              )}
              {r.status === "not_evaluable" && (
                <Note tone="warn">
                  <strong>Information missing:</strong> {r.missing_fields.length ? r.missing_fields.join("; ") : "required inputs were not available"}.
                  This is not a sign the case is fine.
                </Note>
              )}
            </section>
            <section>
              <h4 className="h-sub">What to do next</h4>
              <p className="small">{r.suggested_step}</p>
              {graphIds.length > 0 && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => showOnGraph(r.source_ids)}>
                  <Eye size={14} aria-hidden="true" /> Show on the money trail
                </button>
              )}
              {Object.keys(r.params).length > 0 && (
                <>
                  <h4 className="h-sub">Settings used</h4>
                  <dl className="param-list">
                    {Object.entries(r.params).map(([k, v]) => (
                      <div key={k}>
                        <dt>{paramLabel(k)}</dt>
                        <dd className="num">{typeof v === "number" ? formatParam(k, v) : String(v)}</dd>
                      </div>
                    ))}
                  </dl>
                </>
              )}
              {r.limitations.length > 0 && (
                <>
                  <h4 className="h-sub">What this does not tell you</h4>
                  <ul className="plain-list small muted">
                    {r.limitations.map((l, i) => (
                      <li key={i}>{l}</li>
                    ))}
                  </ul>
                </>
              )}
              <p className="small muted mono">
                {r.rule_id} · version {r.version}
              </p>
            </section>
          </div>
        </div>
      )}
    </li>
  );
}
