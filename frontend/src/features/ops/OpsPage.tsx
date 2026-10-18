import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ExternalLink, FlaskConical, RotateCcw } from "lucide-react";
import { api } from "../../api/endpoints";
import { useOpsCalls, useOpsEvals, useOpsMetrics } from "../../api/hooks";
import { useAuth, canSupervise } from "../auth/AuthProvider";
import { Card, EmptyState, ErrorState, InlineError, LoadingBlock, Note, Time } from "../../components/Primitives";
import { Chip } from "../../components/Chip";
import { SectionTitle } from "../../components/Domain";
import { Modal } from "../../components/Overlay";
import { useToast } from "../../components/Toast";
import { formatInt, formatMs, formatPct, formatUsd, humanize } from "../../lib/format";
import type { EvalRun, OpsMetrics } from "../../types/api";
import { CostPerDayChart, QualityTrendChart, VerdictChart } from "./charts";
import { IngestCard, SecurityCard, UsersCard } from "./AdminPanels";
import QualityPanels from "./QualityPanels";

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="kpi card">
      <span className="kpi-label">{label}</span>
      <span className="kpi-value num">{value}</span>
      {sub && <span className="kpi-sub">{sub}</span>}
    </div>
  );
}

export default function OpsPage() {
  const { user } = useAuth();
  const m = useOpsMetrics();
  const calls = useOpsCalls();
  const evals = useOpsEvals();
  return (
    <div className="page">
      <SectionTitle>AI and system health</SectionTitle>
      <p className="page-lede">How well the AI is working (accuracy, speed, cost), ledger deliveries and security settings. Last {m.data?.window_days ?? 14} days.</p>
      {m.isLoading ? (
        <LoadingBlock label="Loading AI metrics" lines={8} />
      ) : m.error ? (
        <ErrorState error={m.error} onRetry={() => m.refetch()} title="Couldn't load AI metrics" />
      ) : m.data ? (
        <OpsBody m={m.data} />
      ) : null}

      <Card title="Recent AI calls" subtitle="One row per model call, with its trace.">
        {calls.isLoading ? (
          <LoadingBlock lines={5} />
        ) : calls.error ? (
          <ErrorState error={calls.error} onRetry={() => calls.refetch()} />
        ) : !calls.data?.calls.length ? (
          <EmptyState title="No AI calls yet">Calls appear here when Gemini is used for an investigation, evidence reading or the copilot.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table table-compact">
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Node</th>
                  <th scope="col">Model</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="ta-r">Tokens in/out</th>
                  <th scope="col" className="ta-r">Cost</th>
                  <th scope="col" className="ta-r">Latency</th>
                  <th scope="col">Case</th>
                  <th scope="col">Trace</th>
                </tr>
              </thead>
              <tbody>
                {calls.data.calls.map((c) => (
                  <tr key={c.id}>
                    <td data-label="Time"><Time iso={c.created_at} seconds /></td>
                    <td data-label="Node" className="mono">{c.node}</td>
                    <td data-label="Model" className="mono small">{c.model}<span className="cell-sub">{c.prompt_version}</span></td>
                    <td data-label="Status">
                      <Chip tone={c.status === "ok" ? "good" : "bad"} size="sm">{c.status}</Chip>
                      {c.error && <span className="cell-sub">{c.error}</span>}
                    </td>
                    <td data-label="Tokens" className="ta-r num">{formatInt(c.input_tokens)} / {formatInt(c.output_tokens + c.thinking_tokens)}</td>
                    <td data-label="Cost" className="ta-r num">{formatUsd(c.cost_usd)}</td>
                    <td data-label="Latency" className="ta-r num">{formatMs(c.latency_ms)}</td>
                    <td data-label="Case">{c.case_id ? <Link to={`/cases/${c.case_id}`} className="link mono">{c.case_id}</Link> : "—"}</td>
                    <td data-label="Trace" className="mono small">
                      {c.trace_url ? (
                        <a href={c.trace_url} target="_blank" rel="noopener noreferrer" className="link">open <ExternalLink size={11} aria-hidden="true" /></a>
                      ) : c.trace_id ? c.trace_id.slice(0, 10) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <EvalSection runs={evals.data?.runs} loading={evals.isLoading} error={evals.error} retry={() => evals.refetch()} canRun={canSupervise(user)} />
      {canSupervise(user) && <QualityPanels />}
      {canSupervise(user) && <IngestCard canUpload={user?.role === "admin"} />}
      {canSupervise(user) && <SecurityCard />}
      {user?.role === "admin" && <UsersCard />}
      {user?.role === "admin" && <AdminCard />}
      {user?.role === "admin" && <RetentionCard />}
    </div>
  );
}

function OpsBody({ m }: { m: OpsMetrics }) {
  const t = m.totals;
  const q = m.quality;
  return (
    <div className="stack-lg ops-body">
      <div className="kpi-grid">
        <Kpi label="AI calls" value={formatInt(t.calls)} sub={`${formatInt(t.ok)} ok`} />
        <Kpi label="Error rate" value={formatPct(t.error_rate, 1)} />
        <Kpi label="Total cost" value={formatUsd(t.cost_usd)} sub={`${formatInt(t.input_tokens)} in · ${formatInt(t.output_tokens)} out tokens`} />
        <Kpi label="Mean cost per case" value={formatUsd(t.mean_cost_per_case_usd)} />
        <Kpi label="Mean hallucination rate" value={formatPct(q.mean_hallucination_rate, 1)} sub="AI reports only" />
        <Kpi label="Mean confidence" value={formatPct(q.mean_confidence)} sub="AI reports only" />
        <Kpi label="Reports" value={formatInt(t.reports)} sub={`${t.ai_reports} AI · ${t.facts_only_reports} facts-only`} />
      </div>

      <div className="two-col">
        <Card title="LLM configuration">
          <dl className="kv">
            <div className="kv-row"><dt>AI enabled</dt><dd><Chip tone={m.llm.enabled ? "good" : "neutral"} size="sm">{m.llm.enabled ? "Enabled" : "Disabled"}</Chip></dd></div>
            <div className="kv-row"><dt>Vertex project configured</dt><dd><Chip tone={m.llm.configured ? "good" : "warn"} size="sm">{m.llm.configured ? "Yes" : "No"}</Chip></dd></div>
            <div className="kv-row"><dt>Fast models</dt><dd className="mono small">{m.llm.fast_models.join(" → ")}</dd></div>
            <div className="kv-row"><dt>Pro models</dt><dd className="mono small">{m.llm.pro_models.join(" → ")}</dd></div>
            <div className="kv-row"><dt>Location</dt><dd className="mono small">{m.llm.location}</dd></div>
            <div className="kv-row"><dt>Daily budget</dt><dd className="num">{formatUsd(m.llm.daily_budget_usd)}</dd></div>
            <div className="kv-row"><dt>Per-case budget</dt><dd className="num">{formatUsd(m.llm.case_budget_usd)}</dd></div>
          </dl>
          {(!m.llm.enabled || !m.llm.configured) && (
            <Note tone="neutral">With AI unavailable, investigations produce clearly labelled facts-only reports and AI items show “Not analysed”.</Note>
          )}
        </Card>
        <Card title="Pricing table" subtitle={<>Version {m.pricing.version} · <a className="link" href={m.pricing.source} target="_blank" rel="noopener noreferrer">source</a></>}>
          <table className="mini-table">
            <thead>
              <tr><th scope="col">Model</th><th scope="col" className="ta-r">Input $/1M</th><th scope="col" className="ta-r">Output $/1M</th></tr>
            </thead>
            <tbody>
              {Object.entries(m.pricing.table).map(([k, v]) => (
                <tr key={k}><td className="mono small">{k}</td><td className="ta-r num">{v.input.toFixed(2)}</td><td className="ta-r num">{v.output.toFixed(2)}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <div className="chart-grid">
        <Card title="Cost per day (USD)">
          {m.per_day.length ? <CostPerDayChart data={m.per_day} /> : <EmptyState title="No AI spend in this window" />}
        </Card>
        <Card title="Hallucination rate and confidence per report">
          {q.hallucination_trend.length ? <QualityTrendChart data={q.hallucination_trend} /> : <EmptyState title="No reports yet" />}
          <p className="small muted">Facts-only reports are built by code, so their rates are trivially 0% / 100%; hover a point to see its generator.</p>
        </Card>
        <Card title="Claim verdict mix">
          {Object.keys(q.verdicts).length ? <VerdictChart verdicts={q.verdicts} /> : <EmptyState title="No verdicts yet" />}
          <p className="small muted">“System generated” = written by code from records (facts-only reports), not judged.</p>
        </Card>
      </div>

      <Card title="Per pipeline node">
        {m.nodes.length === 0 ? (
          <EmptyState title="No node activity" />
        ) : (
          <div className="table-wrap">
            <table className="table table-compact">
              <thead>
                <tr>
                  <th scope="col">Node</th>
                  <th scope="col" className="ta-r">Calls</th>
                  <th scope="col" className="ta-r">OK</th>
                  <th scope="col">Errors</th>
                  <th scope="col" className="ta-r">p50</th>
                  <th scope="col" className="ta-r">p95</th>
                  <th scope="col" className="ta-r">Tokens in/out</th>
                  <th scope="col" className="ta-r">Cost</th>
                  <th scope="col">Models</th>
                </tr>
              </thead>
              <tbody>
                {m.nodes.map((n) => {
                  const errs = Object.entries(n.errors).filter(([, v]) => v > 0);
                  return (
                    <tr key={n.node}>
                      <td data-label="Node" className="mono">{n.node}</td>
                      <td data-label="Calls" className="ta-r num">{n.calls}</td>
                      <td data-label="OK" className="ta-r num">{n.ok}</td>
                      <td data-label="Errors" className="small">{errs.length ? errs.map(([k, v]) => `${humanize(k)} ${v}`).join(" · ") : <span className="muted">none</span>}</td>
                      <td data-label="p50" className="ta-r num">{formatMs(n.p50_ms)}</td>
                      <td data-label="p95" className="ta-r num">{formatMs(n.p95_ms)}</td>
                      <td data-label="Tokens" className="ta-r num">{formatInt(n.input_tokens)} / {formatInt(n.output_tokens)}</td>
                      <td data-label="Cost" className="ta-r num">{formatUsd(n.cost_usd)}</td>
                      <td data-label="Models" className="mono small">{n.models.join(", ") || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function EvalSection({ runs, loading, error, retry, canRun }: { runs?: EvalRun[]; loading: boolean; error: unknown; retry: () => void; canRun: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const run = useMutation({
    mutationFn: api.runEval,
    onSuccess: async (r) => {
      toast.show(`Evaluation run #${r.id} complete`);
      await qc.invalidateQueries({ queryKey: ["ops"] });
    },
  });
  const latest = runs?.[0];
  const det = latest?.metrics.deterministic;
  const ai = latest?.metrics.ai;
  return (
    <Card
      title="Evaluation"
      subtitle="Scenario checks against synthetic ground truth: rule outcomes, endpoints, attribution bounds and money conservation."
      actions={
        canRun ? (
          <button type="button" className="btn btn-secondary" onClick={() => run.mutate()} disabled={run.isPending}>
            <FlaskConical size={15} aria-hidden="true" /> {run.isPending ? "Running…" : "Run evaluation"}
          </button>
        ) : undefined
      }
    >
      <InlineError error={run.error} />
      {loading ? (
        <LoadingBlock lines={4} />
      ) : error ? (
        <ErrorState error={error} onRetry={retry} />
      ) : !latest ? (
        <EmptyState title="No evaluation run yet">{canRun ? "Run an evaluation to score the pipeline." : "A supervisor can run an evaluation."}</EmptyState>
      ) : (
        <div className="stack">
          <p className="small muted">
            Run #{latest.id} {latest.started_at && <>· <Time iso={latest.started_at} /></>}
          </p>
          <div className="kpi-grid kpi-grid-sm">
            <Kpi label="Checks passed" value={det ? `${det.passed} / ${det.checks}` : "—"} />
            <Kpi label="Pass rate" value={formatPct(det?.pass_rate, 1)} />
            <Kpi label="Rule precision" value={formatPct(det?.rule_precision, 0)} />
            <Kpi label="Rule recall" value={formatPct(det?.rule_recall, 0)} />
            {ai && <Kpi label="AI claims supported" value={`${ai.claims_supported} / ${ai.claims_total}`} sub={`${ai.reports} AI report(s)`} />}
          </div>
          <div className="table-wrap">
            <table className="table table-compact">
              <thead>
                <tr><th scope="col">Scenario</th><th scope="col">Case</th><th scope="col" className="ta-r">Passed</th><th scope="col">Failed checks</th></tr>
              </thead>
              <tbody>
                {latest.details.map((d) => {
                  const failed = d.checks.filter((c) => !c.passed);
                  return (
                    <tr key={d.scenario + d.case_id}>
                      <td data-label="Scenario" className="mono">{d.scenario}</td>
                      <td data-label="Case"><Link className="link mono" to={`/cases/${d.case_id}`}>{d.case_id}</Link></td>
                      <td data-label="Passed" className="ta-r num">
                        <span className={d.passed === d.total ? "good-text" : "warn-text"}>{d.passed} / {d.total}</span>
                      </td>
                      <td data-label="Failed" className="small">
                        {failed.length ? failed.map((c) => `${c.check} (${c.detail})`).join("; ") : <span className="muted">none</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Card>
  );
}

function AdminCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const reset = useMutation({
    mutationFn: api.resetDemo,
    onSuccess: async () => {
      setOpen(false);
      await qc.invalidateQueries();
      toast.show("Demo data reset");
    },
  });
  return (
    <Card title="Admin" subtitle="Restore the synthetic demo dataset to its starting state.">
      <button type="button" className="btn btn-danger" onClick={() => setOpen(true)}>
        <RotateCcw size={15} aria-hidden="true" /> Reset demo data
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Reset demo data?"
        size="sm"
        description="This deletes all cases, reports, notes, evidence uploads and audit events, then reseeds the synthetic dataset. It cannot be undone."
        footer={
          <>
            <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
            <button type="button" className="btn btn-danger" onClick={() => reset.mutate()} disabled={reset.isPending}>
              {reset.isPending ? "Resetting…" : "Reset everything"}
            </button>
          </>
        }
      >
        <InlineError error={reset.error} />
      </Modal>
    </Card>
  );
}

function RetentionCard() {
  const qc = useQueryClient();
  const toast = useToast();
  const run = useMutation({
    mutationFn: (dryRun: boolean) => api.runRetention(dryRun),
    onSuccess: async (r) => {
      if (!r.dry_run) {
        await qc.invalidateQueries();
        toast.show(`${r.deleted} evidence file(s) deleted under the retention policy`);
      }
    },
  });
  const r = run.data;
  return (
    <Card title="Evidence retention" subtitle="Deletes evidence files of resolved cases decided longer ago than the retention period. Records and hashes stay in the audit trail.">
      <div className="inline-actions">
        <button type="button" className="btn btn-secondary" onClick={() => run.mutate(true)} disabled={run.isPending}>
          Check what is due (dry run)
        </button>
        {r && r.dry_run && r.eligible.length > 0 && (
          <button type="button" className="btn btn-danger" onClick={() => run.mutate(false)} disabled={run.isPending}>
            Delete {r.eligible.length} file(s)
          </button>
        )}
      </div>
      {r && (
        <p className="small muted" style={{ marginTop: 12 }}>
          Retention period {r.retention_days} days · cut-off <Time iso={r.cutoff} /> ·{" "}
          {r.dry_run ? `${r.eligible.length} file(s) due for deletion` : `${r.deleted} file(s) deleted`}
        </p>
      )}
      <InlineError error={run.error} />
    </Card>
  );
}
