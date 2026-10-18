import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/endpoints";
import { keys, useInvalidateCase, useReport, useReportDraft, useReports } from "../../api/hooks";
import { errorMessage } from "../../api/client";
import { useWorkspace } from "../case/workspace";
import { Card, EmptyState, ErrorState, InlineError, LoadingBlock, Time } from "../../components/Primitives";
import { Chip } from "../../components/Chip";
import { useToast } from "../../components/Toast";
import { REPORT_STATUS } from "../../lib/labels";
import { formatPct, humanize } from "../../lib/format";
import type { InvestigationRun, ReportDraft } from "../../types/api";
import { ReportView } from "./ReportView";
import { RunProgress } from "./RunProgress";

const OP_TEXT: Record<string, string> = { clear_section: "Cleared", restore_section: "Restored", remove_claims: "Removed" };

export function ReportTab() {
  const { caseId, ctx, showOnGraph } = useWorkspace();
  const qc = useQueryClient();
  const toast = useToast();
  const invalidate = useInvalidateCase(caseId);
  const list = useReports(caseId);
  const [selected, setSelected] = useState<string | null>(null);
  const latestId = list.data?.reports[0]?.id ?? null;
  const current = selected ?? latestId;
  const isLatest = !!current && current === latestId;
  const rep = useReport(current);
  const draftQ = useReportDraft(isLatest ? current : null);
  const draft = isLatest ? (draftQ.data?.draft ?? null) : null;
  const [runId, setRunId] = useState<string | null>(null);

  useEffect(() => {
    if (selected && list.data && !list.data.reports.some((r) => r.id === selected)) setSelected(null);
  }, [list.data, selected]);

  // Rejoin a run that is still going if this tab is reopened, so the page never hides real progress.
  const activeQ = useQuery({
    queryKey: ["case", caseId, "run-active"],
    queryFn: () => api.investigationActive(caseId),
    enabled: !runId,
    staleTime: 0,
  });
  useEffect(() => {
    if (!runId && activeQ.data?.run?.status === "running") setRunId(activeQ.data.run.id);
  }, [activeQ.data, runId]);

  const start = useMutation({
    mutationFn: () => api.investigateStart(caseId),
    onSuccess: (r) => setRunId(r.id),
    onError: (e) => toast.show(errorMessage(e), "bad"),
  });
  const runQ = useQuery({
    queryKey: ["case", caseId, "run", runId],
    queryFn: () => api.investigationRun(caseId, runId as string),
    enabled: !!runId,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1200 : false),
  });
  const run: InvestigationRun | null = runQ.data ?? (runId ? ({ id: runId, case_id: caseId, status: "running", steps: [], report_id: null, error: null, started_at: "", elapsed_ms: 0 } as InvestigationRun) : null);
  const running = run?.status === "running";

  useEffect(() => {
    if (!run || run.status === "running") return;
    setRunId(null);
    if (run.status === "failed") {
      toast.show(run.error ?? "The investigation could not finish. Please run it again.", "bad");
      return;
    }
    if (run.report_id) {
      (async () => {
        const r = await api.report(run.report_id as string);
        qc.setQueryData(keys.report(r.id), r);
        setSelected(r.id);
        await invalidate();
        toast.show(r.status === "facts_only" ? "Facts-only report generated (AI unavailable)" : `Report v${r.version} generated: ${REPORT_STATUS[r.status]?.label ?? r.status}`);
      })();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.status, run?.id]);

  const op = useMutation({
    mutationFn: (v: { op: "clear_section" | "restore_section"; key: string }) => api.draftOp(current as string, v.op, v.key),
    onSuccess: (r) => {
      qc.setQueryData(keys.draft(current as string), { draft: r.draft });
      toast.show(r.summary, "neutral");
    },
    onError: (e) => toast.show(errorMessage(e), "bad"),
  });

  const save = useMutation({
    mutationFn: () => api.saveDraft(current as string),
    onSuccess: async (r) => {
      qc.setQueryData(keys.report(r.id), r);
      await qc.invalidateQueries({ queryKey: ["report"] });
      setSelected(r.id);
      await invalidate();
      toast.show(`Saved as version ${r.version}. Review it before recording a decision.`);
    },
    onError: (e) => toast.show(errorMessage(e), "bad"),
  });

  const discard = useMutation({
    mutationFn: () => api.discardDraft(current as string),
    onSuccess: async () => {
      qc.setQueryData(keys.draft(current as string), { draft: null });
      await invalidate();
      toast.show("Draft discarded; the report is unchanged.", "neutral");
    },
    onError: (e) => toast.show(errorMessage(e), "bad"),
  });

  const rejudge = useMutation({
    mutationFn: () => api.rejudge(current as string),
    onSuccess: async (r) => {
      qc.setQueryData(keys.report(r.report.id), r.report);
      await invalidate();
      toast.show(r.result.message, r.result.judged ? "good" : "neutral");
    },
    onError: (e) => toast.show(errorMessage(e), "bad"),
  });

  const onGraph = (id: string) => showOnGraph([id]);

  return (
    <div className="stack-lg">
      <Card
        title="AI investigation"
        subtitle="The AI gathers the records, follows the money, reads the evidence and writes a report. Every sentence links to the records it comes from, and each one is checked by code and fact-checked."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => start.mutate()} disabled={running || start.isPending || !ctx.can_edit}>
            {running || start.isPending ? "Investigating…" : latestId ? "Run again" : "Run AI investigation"}
          </button>
        }
      >
        <RunProgress run={run} />
        <InlineError error={start.error} />
        {list.data && list.data.reports.length > 0 && (
          <div className="version-picker">
            <span className="field-label">Versions</span>
            <div className="version-list" role="radiogroup" aria-label="Report version">
              {list.data.reports.map((r) => {
                const s = REPORT_STATUS[r.status] ?? { label: humanize(r.status), tone: "neutral" as const };
                const on = r.id === current;
                return (
                  <button
                    key={r.id}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    className={`version-btn ${on ? "is-active" : ""}`}
                    onClick={() => setSelected(r.id)}
                  >
                    <span className="strong">v{r.version}</span>
                    <Chip tone={s.tone} size="sm">
                      {s.label}
                    </Chip>
                    <span className="small muted">
                      <Time iso={r.created_at} /> · {r.claims_total} statements · confidence {formatPct(r.confidence)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </Card>

      {draft && (
        <DraftBar draft={draft} onSave={() => save.mutate()} onDiscard={() => discard.mutate()} busy={save.isPending || discard.isPending} canEdit={ctx.can_edit} />
      )}

      {list.isLoading ? (
        <LoadingBlock label="Loading reports" lines={6} />
      ) : list.error ? (
        <ErrorState error={list.error} onRetry={() => list.refetch()} title="Couldn't load reports" />
      ) : !current ? (
        <EmptyState title="No report yet">
          Run the AI investigation to draft a report. If the AI is unavailable, a facts-only report is built from the records instead — clearly
          labelled, and never a guess.
        </EmptyState>
      ) : rep.isLoading ? (
        <LoadingBlock label="Loading report" lines={10} />
      ) : rep.error ? (
        <ErrorState error={rep.error} onRetry={() => rep.refetch()} title="Couldn't load the report" />
      ) : rep.data ? (
        <ReportView
          report={rep.data}
          caseId={caseId}
          onShowOnGraph={onGraph}
          canEdit={ctx.can_edit}
          draft={draft}
          editable={ctx.can_edit && isLatest}
          onSectionOp={(o, key) => op.mutate({ op: o, key })}
          opPending={op.isPending}
          onRejudge={() => rejudge.mutate()}
          rejudgePending={rejudge.isPending}
        />
      ) : null}
    </div>
  );
}

function DraftBar({ draft, onSave, onDiscard, busy, canEdit }: { draft: ReportDraft; onSave: () => void; onDiscard: () => void; busy: boolean; canEdit: boolean }) {
  const viaAssistant = draft.changes.some((c) => c.via === "assistant");
  return (
    <section className="draft-bar" aria-label="Unsaved report changes">
      <div className="draft-bar-main">
        <span className="draft-tag">Draft — not saved</span>
        <span>
          <strong>
            {draft.changes.length} change{draft.changes.length === 1 ? "" : "s"}
          </strong>{" "}
          to version {draft.base_version}
          {viaAssistant ? " (some made with the case assistant)" : ""}. Statements: {draft.claims_before} → {draft.claims_after}. Save to create
          version {draft.base_version + 1}; the saved versions stay unchanged.
        </span>
        {canEdit && (
          <span className="draft-bar-actions">
            <button type="button" className="btn btn-primary btn-sm" onClick={onSave} disabled={busy}>
              Save as version {draft.base_version + 1}
            </button>
            <button type="button" className="btn btn-ghost btn-sm" onClick={onDiscard} disabled={busy}>
              Discard draft
            </button>
          </span>
        )}
      </div>
      <details className="disclosure">
        <summary>What changed</summary>
        <ol className="plain-list small">
          {draft.changes.map((c, i) => (
            <li key={i}>
              {OP_TEXT[c.op] ?? c.op} {c.section_key ? `“${humanize(c.section_key)}”` : c.claim_ids.join(", ")} · {c.by}
              {c.via === "assistant" ? " via the case assistant" : ""} · <Time iso={c.at} />
            </li>
          ))}
        </ol>
      </details>
    </section>
  );
}
