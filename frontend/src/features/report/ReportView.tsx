import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { ChevronRight, ExternalLink } from "lucide-react";
import type { Report, ReportDraft, ReportSection } from "../../types/api";
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
  /** Unsaved edits to this report: its sections are shown instead of the saved ones. */
  draft?: ReportDraft | null;
  /** The latest version can be edited (sections cleared or restored into the draft). */
  editable?: boolean;
  onSectionOp?: (op: "clear_section" | "restore_section", sectionKey: string) => void;
  opPending?: boolean;
  onRejudge?: () => void;
  rejudgePending?: boolean;
}

/** Fired (with a section key) to open that report section, e.g. when the case assistant links to it. */
export const OPEN_SECTION_EVENT = "ft:open-report-section";

type Tone = "good" | "warn" | "bad" | "none";

/** The collapsed row's outcome, in words (never colour alone). */
function sectionStatus(sec: ReportSection, factsOnly: boolean): { label: string; tone: Tone } {
  if (sec.cleared) return { label: "Cleared", tone: "none" };
  if (sec.claims.length === 0) return { label: "Empty", tone: "none" };
  const flagged = sec.claims.filter((c) => c.flagged || !c.valid).length;
  if (flagged) return { label: `${flagged} need${flagged === 1 ? "s" : ""} a check`, tone: "bad" };
  const unjudged = sec.claims.filter((c) => c.verdict === "unjudged").length;
  if (unjudged) return { label: `${unjudged} not fact-checked`, tone: "warn" };
  return { label: factsOnly ? "Built from records" : "All checked", tone: "good" };
}

/** One-line preview of the section for the collapsed row. */
function sectionLine(sec: ReportSection): string {
  if (sec.cleared) return "Cleared — will be left out when saved";
  if (sec.claims.length === 0) return "No statements";
  const first = sec.claims[0].text;
  return `${sec.claims.length} statement${sec.claims.length === 1 ? "" : "s"} · ${first}`;
}

/** The fact-check did not finish for some statements: say so plainly and offer to run just that step again. */
function JudgeNotice({ report, onRejudge, pending }: { report: Report; onRejudge?: () => void; pending?: boolean }) {
  const m = report.metrics;
  if (report.generator === "deterministic" || !m.judge_status || m.judge_status === "ok") return null;
  const unjudged = report.sections.flatMap((s) => s.claims).filter((c) => c.verdict === "unjudged").length;
  if (!unjudged) return null;
  return (
    <Note tone="warn">
      <strong>The fact-check did not finish for {unjudged} of {m.claims_total} statements</strong> ({humanize(m.judge_status)}). Confidence only
      counts statements that were fact-checked, so it is lower than it should be. You can run just the fact-check again — the rest of the
      investigation does not need to be repeated.{" "}
      {onRejudge && (
        <button type="button" className="btn btn-secondary btn-sm" onClick={onRejudge} disabled={pending}>
          {pending ? "Fact-checking…" : "Run fact-check again"}
        </button>
      )}
    </Note>
  );
}

export function ReportStatusBanner({ report }: { report: Report }) {
  const s = REPORT_STATUS[report.status] ?? { label: humanize(report.status), tone: "neutral" as const };
  if (report.status === "facts_only")
    return (
      <Note tone="warn">
        <strong>Written without AI — every sentence was built directly from the case records.</strong> The AI was not available, so AI-only
        steps such as reading evidence and the fact-check show “Not analysed”.
      </Note>
    );
  return (
    <Note tone={s.tone === "good" ? "good" : s.tone === "bad" ? "bad" : "warn"}>
      <strong>{s.label}.</strong>{" "}
      {report.status === "verified"
        ? "Every sentence was checked against the records and passed."
        : report.status === "partially_verified"
          ? "Some sentences need a check before you rely on the report — they are marked below."
          : "Many sentences could not be confirmed. Treat this report with caution."}{" "}
      The AI wrote it; the system checked every linked record, amount and time against the case records.
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
  return (
    <div className="metric-grid">
      <Metric label="Statements" value={m.claims_total} hint="Sentences in the report, each linked to the records it comes from" />
      {report.status === "facts_only" ? (
        <Metric label="Built from records by code" value={m.claims_supported} hint="No AI was used, so there was nothing to fact-check" />
      ) : (
        <Metric label="Confirmed by fact-check" value={m.claims_supported} />
      )}
      <Metric label="Need attention" value={<span className={m.claims_flagged ? "bad-text" : ""}>{m.claims_flagged}</span>} hint="Statements flagged by the checks or not supported by the fact-check" />
      <Metric label="Not backed by records" value={formatPct(m.hallucination_rate, 1)} hint="Hallucination rate: (invalid citations + number mismatches + unsupported + contradicted) ÷ statements" />
      <Metric label="Confidence" value={formatPct(m.confidence)} hint={m.confidence_note} />
    </div>
  );
}

export function RunMetrics({ report }: { report: Report }) {
  const m = report.metrics;
  const run = report.run;
  return (
    <div className="metric-grid">
      <Metric label="Cost" value={formatUsd(m.cost_usd)} />
      <Metric label="AI latency" value={formatMs(m.ai_latency_ms)} />
      <Metric label="Tokens in / out" value={`${formatInt(m.input_tokens)} / ${formatInt(m.output_tokens)}`} />
      <Metric label="AI calls · tool calls" value={`${m.ai_calls} · ${m.tool_calls}`} />
      <Metric label="Total run time" value={formatMs(run?.latency_ms)} />
    </div>
  );
}

export function ReportView({ report, caseId, onShowOnGraph, canEdit, draft, editable, onSectionOp, opPending, onRejudge, rejudgePending }: Props) {
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
  const sections = draft?.sections ?? report.sections;
  const needCheck = sections.flatMap((s) => s.claims).filter((c) => c.flagged || !c.valid).length;
  const unjudgedAll = sections.flatMap((s) => s.claims).filter((c) => c.verdict === "unjudged").length;
  // Sections start collapsed; the case assistant can ask for one to open (see CaseAssistant focusSection).
  const [open, setOpen] = useState<Set<string>>(new Set());
  useEffect(() => setOpen(new Set()), [report.id]);
  useEffect(() => {
    const h = (e: Event) => {
      const key = (e as CustomEvent<string>).detail;
      setOpen((prev) => new Set(prev).add(key));
    };
    window.addEventListener(OPEN_SECTION_EVENT, h);
    return () => window.removeEventListener(OPEN_SECTION_EVENT, h);
  }, []);
  const allOpen = sections.length > 0 && sections.every((s) => open.has(s.key));
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
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
            <Time iso={report.created_at} /> · {report.generator === "deterministic" ? "built from the records (no AI)" : "written by AI"}
          </>
        }
        actions={
          <a className="btn btn-secondary btn-sm" href={`/cases/${caseId}/reports/${report.id}/print`} target="_blank" rel="noopener noreferrer">
            Print / export
          </a>
        }
      >
        <ReportStatusBanner report={report} />
        <JudgeNotice report={report} onRejudge={canEdit ? onRejudge : undefined} pending={rejudgePending} />
        <ReportMetrics report={report} />
        <p className="small muted confidence-note">
          <strong>Confidence:</strong> {m.confidence_note}
        </p>
        {m.missing_sections.length > 0 && <Note tone="warn">Missing sections: {m.missing_sections.map(humanize).join(", ")}</Note>}
        <details className="disclosure report-run-details">
          <summary>Technical details (cost, time taken, AI models)</summary>
          <div className="disclosure-body">
            <RunMetrics report={report} />
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
                Generator <code>{report.generator}</code>
                {report.run?.models?.length ? <> · models {report.run.models.join(", ")}</> : null}
              </span>
              <span>
                Fact-check: {humanize(m.judge_status)} · draft attempts {m.draft_attempts} · checks {m.validation_passed ? "passed" : "found issues"}
              </span>
            </div>
            {m.notes.length > 0 && (
              <ul className="plain-list small report-notes">
                {m.notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            )}
          </div>
        </details>
      </Card>

      <div className="report-grid">
        <div className="stack-lg">
          <div className="report-acc-toolbar">
            <span className="small">
              <strong>{sections.length} sections</strong> · {needCheck > 0 ? `${needCheck} statement${needCheck === 1 ? "" : "s"} need a check` : "no statements need a check"}
              {unjudgedAll > 0 ? ` · ${unjudgedAll} not fact-checked yet` : ""}. Open a section to read and review it.
            </span>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(allOpen ? new Set() : new Set(sections.map((s) => s.key)))}>
              {allOpen ? "Close all" : "Open all"}
            </button>
          </div>
          <ul className="risk-acc report-acc" aria-label="Report sections">
            {sections.map((sec) => {
              const st = sectionStatus(sec, report.status === "facts_only");
              const isOpen = open.has(sec.key);
              const done = sec.claims.filter((c) => claims[c.id]).length;
              return (
                <li key={sec.key} id={`report-section-${sec.key}`} className={`risk-row report-row tone-row-${st.tone} ${isOpen ? "is-open" : ""}`}>
                  <button type="button" className="risk-head" aria-expanded={isOpen} aria-controls={`report-body-${sec.key}`} onClick={() => toggle(sec.key)}>
                    <ChevronRight size={16} aria-hidden="true" className="risk-chevron" />
                    <span className="risk-name">{sec.title}</span>
                    <span className="risk-line">{sectionLine(sec)}</span>
                    <span className="risk-sev">{sec.claims.length > 0 && !sec.cleared ? `${done} of ${sec.claims.length} reviewed` : ""}</span>
                    <span className={`risk-status tone-${st.tone}`}>{st.label}</span>
                  </button>
                  {isOpen && (
                    <div className="risk-body report-body" id={`report-body-${sec.key}`}>
                      {editable && onSectionOp && (sec.cleared || sec.claims.length > 0) && (
                        <div className="report-body-actions">
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            disabled={opPending}
                            onClick={() => onSectionOp(sec.cleared ? "restore_section" : "clear_section", sec.key)}
                          >
                            {sec.cleared ? "Restore this section" : "Clear this section (draft)"}
                          </button>
                        </div>
                      )}
                      {sec.cleared ? (
                        <p className="muted small">
                          {draft ? "Cleared in the draft. It will be removed when you save the draft." : "Cleared by an investigator in this version."}
                        </p>
                      ) : sec.claims.length === 0 ? (
                        <p className="muted small">No statements in this section.</p>
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
                    </div>
                  )}
                </li>
              );
            })}
          </ul>

          <Card title="Suggested next steps" subtitle="Suggestions only. Nothing here happens unless you do it.">
            {report.recommended_actions.length === 0 ? (
              <p className="muted small">No actions recommended.</p>
            ) : (
              <ul className="action-list">
                {report.recommended_actions.map((a, i) => (
                  <li key={i}>
                    <Chip tone="neutral" size="sm">
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
          <Card title="Your review" subtitle="Mark sentences as right (✓) or wrong (✗), choose an overall result and save. A saved review is needed before you record the decision.">
            <p className="small">
              <span className="num">{reviewed}</span> of <span className="num">{allClaims.length}</span> sentences reviewed ·{" "}
              <span className="num">{rejected}</span> rejected
            </p>
            <div className="btn-row">
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                disabled={!canEdit}
                onClick={() => setClaims(Object.fromEntries(allClaims.map((c) => [c.id, c.flagged ? "reject" : "accept"])) as Record<string, "accept" | "reject">)}
              >
                Accept all that passed the checks
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
              {review.isPending ? "Saving…" : "Save review"}
            </button>
          </Card>
          <AgentActivity report={report} />
        </div>
      </div>
    </div>
  );
}
