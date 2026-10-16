import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, FileSearch2 } from "lucide-react";
import { api } from "../../api/endpoints";
import { keys, useInvalidateCase, useMeta, useReport, useReports } from "../../api/hooks";
import { errorMessage } from "../../api/client";
import { useWorkspace } from "../case/workspace";
import { Card, EmptyState, ErrorState, InlineError, LoadingBlock, Time } from "../../components/Primitives";
import { Chip } from "../../components/Chip";
import { useToast } from "../../components/Toast";
import { REPORT_STATUS } from "../../lib/labels";
import { formatPct, humanize } from "../../lib/format";
import { ReportView } from "./ReportView";
import { RunProgress } from "./RunProgress";
import { ClassifyPanel, CopilotBox } from "./CopilotPanels";

export function ReportTab() {
  const { caseId, ctx, showOnGraph } = useWorkspace();
  const qc = useQueryClient();
  const toast = useToast();
  const meta = useMeta();
  const invalidate = useInvalidateCase(caseId);
  const list = useReports(caseId);
  const [selected, setSelected] = useState<string | null>(null);
  const latestId = list.data?.reports[0]?.id ?? null;
  const current = selected ?? latestId;
  const rep = useReport(current);

  useEffect(() => {
    if (selected && list.data && !list.data.reports.some((r) => r.id === selected)) setSelected(null);
  }, [list.data, selected]);

  const run = useMutation({
    mutationFn: () => api.investigate(caseId),
    onSuccess: async (r) => {
      qc.setQueryData(keys.report(r.id), r);
      setSelected(r.id);
      await invalidate();
      toast.show(r.status === "facts_only" ? "Facts-only report generated (AI unavailable)" : `Report v${r.version} generated: ${REPORT_STATUS[r.status]?.label ?? r.status}`);
    },
    onError: (e) => toast.show(errorMessage(e), "bad"),
  });

  const onGraph = (id: string) => showOnGraph([id]);

  return (
    <div className="stack-lg">
      <Card
        title="AI investigation"
        subtitle="An agent gathers the records, explores the trail with fixed tools, reads evidence and drafts a report. Code then checks every citation, amount and time; a judge fact-checks each claim."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => run.mutate()} disabled={run.isPending || !ctx.can_edit}>
            <Bot size={16} aria-hidden="true" /> {run.isPending ? "Investigating…" : latestId ? "Run again" : "Run AI investigation"}
          </button>
        }
      >
        <RunProgress running={run.isPending} />
        <InlineError error={run.error} />
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
                      <Time iso={r.created_at} /> · {r.claims_total} claims · conf. {formatPct(r.confidence)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </Card>

      {list.isLoading ? (
        <LoadingBlock label="Loading reports" lines={6} />
      ) : list.error ? (
        <ErrorState error={list.error} onRetry={() => list.refetch()} title="Couldn't load reports" />
      ) : !current ? (
        <EmptyState title="No report yet" icon={<FileSearch2 size={22} />}>
          Run the AI investigation to draft a cited report. If Gemini is unavailable, a facts-only report is built from the records instead —
          clearly labelled, and never a guess.
        </EmptyState>
      ) : rep.isLoading ? (
        <LoadingBlock label="Loading report" lines={10} />
      ) : rep.error ? (
        <ErrorState error={rep.error} onRetry={() => rep.refetch()} title="Couldn't load the report" />
      ) : rep.data ? (
        <ReportView report={rep.data} caseId={caseId} onShowOnGraph={onGraph} canEdit={ctx.can_edit} />
      ) : null}

      <div className="two-col">
        <CopilotBox caseId={caseId} records={rep.data?.records ?? {}} onShowOnGraph={onGraph} />
        <ClassifyPanel caseId={caseId} currentCategory={ctx.case.category} categories={meta.data?.categories} canEdit={ctx.can_edit} />
      </div>
    </div>
  );
}
