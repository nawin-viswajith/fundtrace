import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { Bot, Cpu, ExternalLink, Printer, ShieldCheck } from "lucide-react";
import type { Report } from "../../types/api";
import { api } from "../../api/endpoints";
import { useInvalidateCase } from "../../api/hooks";
import { Card, InlineError, Note, Time } from "../../components/Primitives";
import { Chip } from "../../components/Chip";
import { useToast } from "../../components/Toast";
import { REPORT_STATUS } from "../../lib/labels";
import { formatInt, formatMs, formatPct, formatUsd, humanize, shortHash } from "../../lib/format";
import { ClaimView } from "./ClaimView";
import { Citation } from "./Citation";
import { AgentActivity } from "./AgentActivity";

interface Props {
  report: Report;
  caseId: string;
  onShowOnGraph?: (id: string) => void;
  canEdit: boolean;
}

export function ReportStatusBanner({ report }: { report: Report }) {
  const s = REPORT_STATUS[report.status] ?? { label: humanize(report.status), tone: "neutral" as const };
  if (report.status === "facts_only")
    return (
      <Note tone="warn" icon={<Cpu size={16} />}>
        <strong>Generated without AI (Gemini unavailable) — every sentence built from records.</strong> AI-only items such as evidence reading
        and the fact-check judge show “Not analysed”.
      </Note>
    );
  return (
    <Note tone={s.tone === "good" ? "good" : s.tone === "bad" ? "bad" : "warn"} icon={<Bot size={16} />}>
      <strong>{s.label}.</strong>{" "}
      {report.status === "verified"
        ? "Every claim passed the deterministic checks and the fact-check judge."
        : report.status === "partially_verified"
          ? "Some claims were flagged by the checks or not supported by the judge — review them before relying on the report."
          : "Most claims could not be verified. Treat this draft with caution."}{" "}
      AI drafted it; code checked every citation, amount and time against the records.
    </Note>
  );
}

function Metric({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="metric" title={hint}>
      <span className="metric-label">{label}</span>
      <span className="metric-value num">{value}</span>
    </div>
  );
}

export function ReportMetrics({ report }: { report: Report }) {
  const m = report.metrics;
  const run = report.run;
  return (
    <div className="metric-grid">
      <Metric label="Claims" value={m.claims_total} />
      <Metric label="Supported" value={m.claims_supported} />
      <Metric label="Flagged" value={<span className={m.claims_flagged ? "bad-text" : ""}>{m.claims_flagged}</span>} />
      <Metric label="Hallucination rate" value={formatPct(m.hallucination_rate, 1)} hint="(invalid citations + number mismatches + unsupported + contradicted) ÷ claims" />
      <Metric label="Confidence" value={formatPct(m.confidence)} hint={m.confidence_note} />
      <Metric label="Cost" value={formatUsd(m.cost_usd)} />
      <Metric label="AI latency" value={formatMs(m.ai_latency_ms)} />
      <Metric label="Tokens in / out" value={`${formatInt(m.input_tokens)} / ${formatInt(m.output_tokens)}`} />
      <Metric label="AI calls · tool calls" value={`${m.ai_calls} · ${m.tool_calls}`} />
      <Metric label="Total run time" value={formatMs(run?.latency_ms)} />
    </div>
  );
}

export function ReportView({ report, caseId, onShowOnGraph, canEdit }: Props) {
  const toast = useToast();
  const invalidate = useInvalidateCase(caseId);
  const [claims, setClaims] = useState<Record<string, "accept" | "reject">>(report.review?.claims ?? {});
  const [overall, setOverall] = useState<string>(report.review_status !== "pending" ? report.review_status : "");
  const [note, setNote] = useState(report.review?.note ?? "");
  useEffect(() => {
    setClaims(report.review?.claims ?? {});
    setOverall(report.review_status !== "pending" ? report.review_status : "");
    setNote(report.review?.note ?? "");
  }, [report.id, report.review, report.review_status]);

  const allClaims = useMemo(() => report.sections.flatMap((s) => s.claims), [report.sections]);
  const reviewed = Object.keys(claims).length;
  const rejected = Object.values(claims).filter((v) => v === "reject").length;

  const review = useMutation({
    mutationFn: () => api.reviewReport(report.id, { status: overall, claims, note }),
    onSuccess: async () => {
      toast.show(`Review saved: ${overall}`);
      await invalidate();
    },
  });

  const s = REPORT_STATUS[report.status] ?? { label: humanize(report.status), tone: "neutral" as const };
  const m = report.metrics;

  return (
    <div className="stack-lg report">
      <Card
        className="report-head"
        title={
          <span className="report-title">
            Investigation report v{report.version}
            <Chip tone={s.tone}>{s.label}</Chip>
            <Chip tone={report.review_status === "pending" ? "warn" : "neutral"} size="sm">
              Review: {humanize(report.review_status)}
            </Chip>
          </span>
        }
        subtitle={
          <>
            <Time iso={report.created_at} /> · generator <code>{report.generator}</code>
            {report.run?.models?.length ? <> · models {report.run.models.join(", ")}</> : null}
          </>
        }
        actions={
          <a className="btn btn-secondary btn-sm" href={`/cases/${caseId}/reports/${report.id}/print`} target="_blank" rel="noopener noreferrer">
            <Printer size={14} aria-hidden="true" /> Print / export
          </a>
        }
      >
        <ReportStatusBanner report={report} />
        <ReportMetrics report={report} />
        <p className="small muted confidence-note">
          <strong>Confidence:</strong> {m.confidence_note}
        </p>
        <div className="report-provenance small">
          <span>
            Snapshot hash <code title={report.snapshot_hash}>{shortHash(report.snapshot_hash, 16)}</code>
          </span>
          {report.run && (
            <span>
              Run <code>{report.run.id}</code> · ruleset <code>{report.run.ruleset_version}</code>
            </span>
          )}
          {report.trace_url ? (
            <a href={report.trace_url} target="_blank" rel="noopener noreferrer" className="link">
              Open trace <ExternalLink size={12} aria-hidden="true" />
            </a>
          ) : (
            report.trace_id && (
              <span>
                Trace <code>{shortHash(report.trace_id, 16)}</code>
              </span>
            )
          )}
          <span>
            Judge: {humanize(m.judge_status)} · draft attempts {m.draft_attempts} · validation {m.validation_passed ? "passed" : "found issues"}
          </span>
        </div>
        {m.notes.length > 0 && (
          <ul className="plain-list small report-notes">
            {m.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        )}
        {m.missing_sections.length > 0 && <Note tone="warn">Missing sections: {m.missing_sections.map(humanize).join(", ")}</Note>}
      </Card>

      <div className="report-grid">
        <div className="stack-lg">
          {report.sections.map((sec) => (
            <section key={sec.key} className="card report-section" aria-labelledby={`sec-${sec.key}`}>
              <h3 id={`sec-${sec.key}`} className="card-title">
                {sec.title}
              </h3>
              {sec.claims.length === 0 ? (
                <p className="muted small">No claims in this section.</p>
              ) : (
                <ol className="claim-list">
                  {sec.claims.map((c) => (
                    <ClaimView
                      key={c.id}
                      claim={c}
                      records={report.records}
                      onShowOnGraph={onShowOnGraph}
                      review={claims[c.id]}
                      reviewDisabled={!canEdit}
                      onReview={(v) =>
                        setClaims((prev) => {
                          const next = { ...prev };
                          if (v) next[c.id] = v;
                          else delete next[c.id];
                          return next;
                        })
                      }
                    />
                  ))}
                </ol>
              )}
            </section>
          ))}

          <Card title="Recommended actions" subtitle="Suggestions for the investigator. Nothing here is applied automatically.">
            {report.recommended_actions.length === 0 ? (
              <p className="muted small">No actions recommended.</p>
            ) : (
              <ul className="action-list">
                {report.recommended_actions.map((a, i) => (
                  <li key={i}>
                    <Chip tone="accent" size="sm">
                      {humanize(a.action_type)}
                    </Chip>
                    <span>{a.description}</span>
                    <span className="cite-list">
                      {a.citations.map((c) => (
                        <Citation key={c} id={c} record={report.records[c]} onShowOnGraph={onShowOnGraph} />
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {m.action_issues.length > 0 && (
              <Note tone="warn">
                {m.action_issues.map((x, i) => (
                  <p key={i}>
                    <code>{x.code}</code> on {x.action}: {x.detail}
                  </p>
                ))}
              </Note>
            )}
          </Card>
        </div>

        <div className="stack-lg report-side">
          <Card title="Review" subtitle="Your review is recorded in the audit trail and unlocks the decision without an override.">
            <p className="small">
              <span className="num">{reviewed}</span> of <span className="num">{allClaims.length}</span> claims reviewed ·{" "}
              <span className="num">{rejected}</span> rejected
            </p>
            <div className="btn-row">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={!canEdit}
                onClick={() => setClaims(Object.fromEntries(allClaims.map((c) => [c.id, c.flagged ? "reject" : "accept"])) as Record<string, "accept" | "reject">)}
              >
                Accept all unflagged
              </button>
              <button type="button" className="btn btn-ghost btn-sm" disabled={!canEdit} onClick={() => setClaims({})}>
                Clear
              </button>
            </div>
            <fieldset className="radio-group">
              <legend className="field-label">Overall</legend>
              {(["accepted", "partial", "rejected"] as const).map((v) => (
                <label key={v} className="radio">
                  <input type="radio" name={`overall-${report.id}`} checked={overall === v} onChange={() => setOverall(v)} disabled={!canEdit} />
                  <span>{v === "partial" ? "Partially accepted" : humanize(v)}</span>
                </label>
              ))}
            </fieldset>
            <label className="field">
              <span className="field-label">Note</span>
              <textarea className="textarea" rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} disabled={!canEdit} />
            </label>
            <InlineError error={review.error} />
            <button type="button" className="btn btn-primary btn-block" disabled={!overall || review.isPending || !canEdit} onClick={() => review.mutate()}>
              <ShieldCheck size={15} aria-hidden="true" /> {review.isPending ? "Saving…" : "Save review"}
            </button>
          </Card>
          <AgentActivity report={report} />
        </div>
      </div>
    </div>
  );
}
