import { checklistLabel, checklistWhy } from "../evidence/plainEvidence";
import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { useWorkspace, type TabId } from "./workspace";
import { Meter } from "../../components/Primitives";
import { Chip } from "../../components/Chip";
import { BUCKET_LABELS, CHECKLIST_STATUS, ENDPOINT_BADGE, METHOD_LABELS, METHODS, POLICY_STATUS, REPORT_STATUS } from "../../lib/labels";
import { formatMoney, formatPct, humanize } from "../../lib/format";
import type { BucketKey, CaseContext } from "../../types/api";
import { amountRange, bucketRange, plural } from "./plainSummary";

type Tone = "good" | "warn" | "bad" | "neutral";

interface Dimension {
  id: string;
  /** Plain name shown on the row. */
  name: string;
  /** The technical name it replaces, kept for people who know the old wording. */
  aka: string;
  /** One plain line on the collapsed row. */
  summary: string;
  status: { label: string; tone: Tone };
  body: ReactNode;
}

const SEVERITY_TEXT: Record<string, string> = { high: "High concern", medium: "Medium concern", low: "Low concern" };

const RESULT_TEXT: Record<string, { label: string; tone: Tone }> = {
  consistent: { label: "Agrees", tone: "good" },
  matches: { label: "Agrees", tone: "good" },
  contradictory: { label: "Records disagree", tone: "bad" },
  contradicts: { label: "Records disagree", tone: "bad" },
  unverifiable: { label: "Can't check yet", tone: "neutral" },
};

/** How each way of counting treats mixed money, for money that moved *on* from an account. */
const METHOD_HELP: Record<(typeof METHODS)[number], string> = {
  min: "assumes the account holder's own money left first, so the least of the customer's money moved on.",
  fifo: "money leaves in the order it arrived.",
  pro_rata: "every payment out carries the same mix as the account balance.",
  max: "assumes the customer's money left first, so the most of it moved on.",
};

const BUCKETS: BucketKey[] = [
  "left_visibility",
  "residual_in_visible_accounts",
  "reached_merchant_or_hub",
  "returned_to_payer",
  "beyond_trace_limits",
  "unaccounted",
];

const toneClass = (t: Tone) => (t === "neutral" ? "tone-none" : `tone-${t}`);

function GoButton({ tab, children }: { tab: TabId; children: ReactNode }) {
  const { setTab } = useWorkspace();
  return (
    <button type="button" className="btn btn-secondary btn-sm dim-go" onClick={() => setTab(tab)}>
      {children}
    </button>
  );
}

function HowWorkedOut({ children, label = "Show how this was worked out" }: { children: ReactNode; label?: string }) {
  return (
    <details className="disclosure dim-how">
      <summary>{label}</summary>
      <div className="disclosure-body small">{children}</div>
    </details>
  );
}

/* ------------------------------------------------------------------ the six checks */

function riskSignals(ctx: CaseContext): Dimension {
  const rs = ctx.rules_summary;
  const triggered = ctx.rules.filter((r) => r.status === "triggered");
  const missing = ctx.rules.filter((r) => r.status === "not_evaluable");
  const high = rs.by_severity?.high ?? 0;
  const parts = [rs.triggered ? `${rs.triggered} found${high ? `, ${high} high concern` : ""}` : "None found"];
  if (missing.length) parts.push(`${missing.length} could not be checked`);
  parts.push(`${rs.not_triggered} not found`);
  return {
    id: "risk",
    name: "Warning signs",
    aka: "Risk signals",
    summary: parts.join(" · "),
    status: rs.triggered ? { label: plural(rs.triggered, "sign") + " found", tone: "bad" } : { label: "None found", tone: "good" },
    body: (
      <>
        <p>The system checks the bank's records for patterns often seen in fraud. A sign found is a reason to look closer, not proof.</p>
        {triggered.length > 0 && (
          <>
            <h3 className="h-sub">Found</h3>
            <ul className="dim-plain-list">
              {triggered.map((r) => (
                <li key={r.rule_id}>
                  <span className={`risk-sev sev-${r.severity} dim-sev`}>{SEVERITY_TEXT[r.severity] ?? humanize(r.severity)}</span>
                  <span>{r.name}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        {missing.length > 0 && (
          <>
            <h3 className="h-sub">Could not be checked (information missing)</h3>
            <ul className="dim-plain-list">
              {missing.map((r) => (
                <li key={r.rule_id}>
                  <span className={`risk-sev sev-${r.severity} dim-sev`}>{SEVERITY_TEXT[r.severity] ?? humanize(r.severity)}</span>
                  <span>
                    {r.name}
                    {r.missing_fields.length > 0 && <span className="muted"> — needs {r.missing_fields.join("; ")}</span>}
                  </span>
                </li>
              ))}
            </ul>
            <p className="small warn-text">“Could not be checked” does not mean the case is fine.</p>
          </>
        )}
        <p className="small muted">{plural(rs.not_triggered, "other check")} found nothing.</p>
        <GoButton tab="risk">See every warning sign</GoButton>
      </>
    ),
  };
}

function evidenceCompleteness(ctx: CaseContext): Dimension {
  const comp = ctx.completeness;
  const required = comp.items.filter((i) => i.required);
  const notPresent = required.filter((i) => i.status !== "present");
  const present = comp.items.filter((i) => i.status === "present");
  const still = comp.required - comp.present;
  const summary =
    still > 0
      ? `${comp.present} of ${comp.required} required items received · still needed: ${notPresent[0] ? checklistLabel(notPresent[0]) : ""}${notPresent.length > 1 ? ` and ${notPresent.length - 1} more` : ""}`
      : `All ${comp.required} required items received`;
  return {
    id: "evidence",
    name: "Evidence received",
    aka: "Evidence completeness",
    summary,
    status: still > 0 ? { label: `${still} still needed`, tone: "warn" } : { label: "Complete", tone: "good" },
    body: (
      <>
        <p>
          <strong className="num">
            {comp.present} of {comp.required}
          </strong>{" "}
          required items are in the case file.
        </p>
        <Meter value={comp.present} max={comp.required} label="Required evidence received" tone="accent" />
        {notPresent.length > 0 && (
          <>
            <h3 className="h-sub">Still needed</h3>
            <ul className="dim-list dim-list-detail">
              {notPresent.map((i) => {
                const s = CHECKLIST_STATUS[i.status] ?? { label: humanize(i.status), tone: "neutral" };
                return (
                  <li key={i.key}>
                    <div className="dim-li-head">
                      <span>{checklistLabel(i)}</span> <Chip tone={s.tone} size="sm">{s.label}</Chip>
                    </div>
                    <span className="muted small">Why it matters: {checklistWhy(i)}</span>
                  </li>
                );
              })}
            </ul>
          </>
        )}
        {present.length > 0 && (
          <details className="disclosure dim-how">
            <summary>Show the {plural(present.length, "item")} already received</summary>
            <ul className="plain-list small disclosure-body">
              {present.map((i) => (
                <li key={i.key}>{checklistLabel(i)}</li>
              ))}
            </ul>
          </details>
        )}
        <p className="small muted">{comp.note}</p>
        <GoButton tab="evidence">Open Evidence</GoButton>
      </>
    ),
  };
}

function evidenceConsistency(ctx: CaseContext): Dimension {
  const cons = ctx.consistency;
  return {
    id: "consistency",
    name: "Do the records agree?",
    aka: "Evidence consistency",
    summary: `${cons.consistent} agree · ${cons.contradictory} disagree · ${cons.unverifiable} can't be checked yet`,
    status: cons.contradictory
      ? { label: "Records disagree", tone: "bad" }
      : cons.consistent
        ? { label: "No disagreements", tone: "good" }
        : { label: "Not checked yet", tone: "neutral" },
    body: (
      <>
        <p>We compare what the customer and their documents say with the bank's own records, and the bank's systems with each other.</p>
        {cons.checks.length === 0 ? (
          <p className="small muted">No comparisons could be made yet.</p>
        ) : (
          <ul className="dim-list dim-list-detail">
            {cons.checks.map((ch, i) => {
              const r = RESULT_TEXT[ch.result] ?? { label: humanize(ch.result), tone: "neutral" as Tone };
              return (
                <li key={i}>
                  <div className="dim-li-head">
                    <span>{ch.check}</span>
                    <Chip tone={r.tone} size="sm">
                      {r.label}
                    </Chip>
                  </div>
                  <span className="muted small">{ch.detail}</span>
                </li>
              );
            })}
          </ul>
        )}
      </>
    ),
  };
}

function traceability(ctx: CaseContext): Dimension {
  const tr = ctx.traceability;
  const cur = ctx.case.currency;
  const [lo, hi] = tr.coverage_range;
  const pct = lo === hi ? formatPct(lo) : `${formatPct(lo)}–${formatPct(hi)}`;
  const amount = formatMoney(ctx.attribution?.disputed_amount_minor ?? ctx.case.amount_minor, cur);
  const ends = Object.entries(tr.endpoints);
  const endText = ends.map(([k, n]) => `${(ENDPOINT_BADGE[k] ?? humanize(k)).toLowerCase()} (${n})`).join(", ");
  const full = lo >= 0.999;
  const buckets = BUCKETS.map((k) => ({ k, r: bucketRange(ctx, k) })).filter((b) => b.r[1] > 0);
  return {
    id: "trace",
    name: "Tracing the money",
    aka: "Traceability coverage",
    summary: `We can see where ${pct} of the ${amount} went${endText ? ` · trails end: ${endText}` : ""}`,
    status: full ? { label: "All accounted for", tone: "good" } : { label: `${pct} accounted for`, tone: "warn" },
    body: (
      <>
        <p>
          We followed the money from the customer's account through the bank's records. We can say where <strong className="num">{pct}</strong>{" "}
          of the {amount} is now.
        </p>
        {buckets.length > 0 && (
          <>
            <h3 className="h-sub">Where the money is now</h3>
            <ul className="dim-list dim-list-detail">
              {buckets.map(({ k, r }) => (
                <li key={k}>
                  <div className="dim-li-head">
                    <span>{BUCKET_LABELS[k]?.label ?? humanize(k)}</span>
                    <span className="num strong">{amountRange(r[0], r[1], cur)}</span>
                  </div>
                  <span className="muted small">{BUCKET_LABELS[k]?.hint}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        <h3 className="h-sub">Where the trails end</h3>
        {ends.length === 0 ? (
          <p className="small muted">No trail ends were recorded.</p>
        ) : (
          <ul className="plain-list small">
            {ends.map(([k, n]) => (
              <li key={k}>
                {ENDPOINT_BADGE[k] ?? humanize(k)}: <span className="num strong">{n}</span> {n === 1 ? "trail" : "trails"}
              </li>
            ))}
          </ul>
        )}
        {tr.truncated && <p className="small warn-text">The trace was cut short because there were too many records to follow.</p>}
        <HowWorkedOut>
          <p>
            When the money lands in an account that already holds other money, the records can't say which rupees moved on. So the system counts it
            four ways and shows the range from lowest to highest:
          </p>
          <ul className="plain-list">
            {METHODS.map((m) => (
              <li key={m}>
                <strong>{METHOD_LABELS[m]}</strong> — {METHOD_HELP[m]}
              </li>
            ))}
          </ul>
          <div className="table-wrap">
            <table className="mini-table dim-method-table">
              <thead>
                <tr>
                  <th scope="col">Way of counting</th>
                  <th scope="col" className="ta-r">
                    Accounted for
                  </th>
                  <th scope="col" className="ta-r">
                    Left this bank
                  </th>
                  <th scope="col" className="ta-r">
                    Still at this bank
                  </th>
                </tr>
              </thead>
              <tbody>
                {METHODS.map((m) => (
                  <tr key={m}>
                    <th scope="row">{METHOD_LABELS[m]}</th>
                    <td className="ta-r num">{formatPct(tr.coverage[m])}</td>
                    <td className="ta-r num">{formatMoney(tr.buckets?.[m]?.left_visibility ?? 0, cur)}</td>
                    <td className="ta-r num">{formatMoney(tr.buckets?.[m]?.residual_in_visible_accounts ?? 0, cur)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            {plural(tr.paths, "trail")} followed. {tr.note}
          </p>
          {ctx.attribution?.caveat && <p className="muted">{ctx.attribution.caveat}</p>}
        </HowWorkedOut>
        <GoButton tab="graph">Open the money trail</GoButton>
      </>
    ),
  };
}

function policy(ctx: CaseContext): Dimension {
  const pol = ctx.policy;
  const polS = POLICY_STATUS[pol.overall] ?? { label: humanize(pol.overall), tone: "neutral" as Tone };
  const days = pol.report_lag_working_days;
  return {
    id: "policy",
    name: "Bank policy check",
    aka: "Policy eligibility",
    summary: `Reported ${plural(days, "working day")} after the payment · ${polS.label.toLowerCase()}`,
    status: { label: polS.label, tone: polS.tone },
    body: (
      <>
        <p>
          The system compares the dates and the type of dispute with the bank's policy. It cannot decide who was at fault — facts listed as “still
          needed” must be established by you.
        </p>
        <p className="small">
          The customer reported this <strong className="num">{plural(days, "working day")}</strong> after the payment.
        </p>
        <ul className="dim-list dim-list-detail">
          {pol.clauses.map((cl) => {
            const s = POLICY_STATUS[cl.status] ?? { label: humanize(cl.status), tone: "neutral" as Tone };
            return (
              <li key={cl.clause_id}>
                <div className="dim-li-head">
                  <span className="small">{cl.text}</span>
                  <Chip tone={s.tone} size="sm">
                    {s.label}
                  </Chip>
                </div>
                {cl.needs.length > 0 && <span className="small warn-text">Still needed: {cl.needs.join("; ")}</span>}
              </li>
            );
          })}
        </ul>
        <HowWorkedOut label="Show policy references and how this was worked out">
          <ul className="plain-list">
            {pol.clauses.map((cl) => {
              const s = POLICY_STATUS[cl.status] ?? { label: humanize(cl.status), tone: "neutral" };
              return (
                <li key={cl.clause_id}>
                  <code className="id-chip">{cl.clause_id}</code> {s.label}
                  {cl.reasons.length > 0 && <span className="muted"> — {cl.reasons.join("; ")}</span>}
                </li>
              );
            })}
          </ul>
          <p className="muted">{pol.note}</p>
        </HowWorkedOut>
      </>
    ),
  };
}

function aiReport(ctx: CaseContext): Dimension {
  const rep = ctx.latest_report;
  const base = { id: "ai", name: "AI report check", aka: "AI confidence" };
  if (!rep)
    return {
      ...base,
      summary: "No AI report yet",
      status: { label: "Not run yet", tone: "neutral" },
      body: (
        <>
          <p>No AI report has been written for this case yet. Run the AI investigation on the AI report tab to get a draft you can check.</p>
          <GoButton tab="report">Open AI report</GoButton>
        </>
      ),
    };
  const st = REPORT_STATUS[rep.status] ?? { label: humanize(rep.status), tone: "neutral" as Tone };
  if (rep.status === "facts_only")
    return {
      ...base,
      summary: "The latest report was built from the records without AI, so there is nothing to score",
      status: { label: "No AI used", tone: "neutral" },
      body: (
        <>
          <p>The AI was not available, so the latest report (version {rep.version}) was written by the system directly from the records. Every sentence comes from a record.</p>
          <GoButton tab="report">Open AI report</GoButton>
        </>
      ),
    };
  return {
    ...base,
    summary: `${rep.claims_supported} of ${rep.claims_total} statements in the AI report are backed by records${rep.claims_flagged ? ` · ${rep.claims_flagged} flagged for you to check` : ""}`,
    status: { label: st.label, tone: st.tone },
    body: (
      <>
        <p>
          This is about how far the AI's report can be trusted — not about the customer. It is never mixed with the warning signs.
        </p>
        <p>
          <strong className="num">
            {rep.claims_supported} of {rep.claims_total}
          </strong>{" "}
          statements are backed by records ({formatPct(rep.confidence)}).{" "}
          {rep.claims_flagged > 0 ? (
            <span className="bad-text">{plural(rep.claims_flagged, "statement")} flagged for you to check.</span>
          ) : (
            <span className="muted">No statements flagged.</span>
          )}
        </p>
        <HowWorkedOut>
          <p>
            Score = statements backed by records ÷ all statements ({formatPct(rep.confidence)}), after the system's own checks and an independent AI
            fact-check. Report version {rep.version}.
          </p>
        </HowWorkedOut>
        <GoButton tab="report">Open AI report</GoButton>
      </>
    ),
  };
}

/* ------------------------------------------------------------------ accordion */

export function DimensionCards() {
  const { ctx } = useWorkspace();
  const dims = [riskSignals(ctx), evidenceCompleteness(ctx), evidenceConsistency(ctx), traceability(ctx), policy(ctx), aiReport(ctx)];
  const [open, setOpen] = useState<Set<string>>(new Set());
  const allOpen = dims.every((d) => open.has(d.id));
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <>
      <div className="dim-toolbar">
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOpen(allOpen ? new Set() : new Set(dims.map((d) => d.id)))}>
          {allOpen ? "Close all" : "Open all"}
        </button>
      </div>
      <ul className="risk-acc dim-acc" aria-label="Six separate checks">
        {dims.map((d) => {
          const isOpen = open.has(d.id);
          const bodyId = `dim-body-${d.id}`;
          return (
            <li key={d.id} className={`risk-row dim-row dim-row-${d.status.tone} ${isOpen ? "is-open" : ""}`}>
              <button type="button" className="risk-head dim-head" aria-expanded={isOpen} aria-controls={bodyId} onClick={() => toggle(d.id)}>
                <ChevronRight size={16} aria-hidden="true" className="risk-chevron" />
                <span className="risk-name">{d.name}</span>
                <span className="risk-line">{d.summary}</span>
                <span className={`risk-status ${toneClass(d.status.tone)}`}>{d.status.label}</span>
              </button>
              {isOpen && (
                <div className="risk-body dim-body" id={bodyId}>
                  {d.body}
                  <p className="dim-aka small muted">Also called “{d.aka}”.</p>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}
