import { ArrowRight } from "lucide-react";
import { useWorkspace } from "./workspace";
import { Card, Meter } from "../../components/Primitives";
import { Chip, SeverityChip } from "../../components/Chip";
import { CHECKLIST_STATUS, ENDPOINT_BADGE, METHOD_LABELS, METHODS, POLICY_STATUS, REPORT_STATUS, RESULT_TONE } from "../../lib/labels";
import { formatPct, humanize } from "../../lib/format";

function GoLink({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" className="link-btn" onClick={onClick}>
      {label} <ArrowRight size={13} aria-hidden="true" />
    </button>
  );
}

export function DimensionCards() {
  const { ctx, setTab } = useWorkspace();
  const rs = ctx.rules_summary;
  const triggered = ctx.rules.filter((r) => r.status === "triggered");
  const missingRules = ctx.rules.filter((r) => r.status === "not_evaluable");
  const comp = ctx.completeness;
  const missingItems = comp.items.filter((i) => i.required && i.status !== "present");
  const cons = ctx.consistency;
  const tr = ctx.traceability;
  const pol = ctx.policy;
  const rep = ctx.latest_report;
  const polS = POLICY_STATUS[pol.overall] ?? { label: humanize(pol.overall), tone: "neutral" };

  return (
    <div className="dim-grid">
      {/* 1. Risk signals */}
      <Card className="dim-card" title="Risk signals" subtitle="Patterns found by deterministic rules" actions={<GoLink label="Details" onClick={() => setTab("risk")} />}>
        <div className="dim-stat-row">
          <div className="dim-stat">
            <span className="dim-num num">{rs.triggered}</span>
            <span className="dim-cap">triggered</span>
          </div>
          <div className="sev-counts" aria-label="Triggered by severity">
            <span className="sev-count sev-high">
              <span className="num">{rs.by_severity.high ?? 0}</span> high
            </span>
            <span className="sev-count sev-medium">
              <span className="num">{rs.by_severity.medium ?? 0}</span> medium
            </span>
            <span className="sev-count sev-low">
              <span className="num">{rs.by_severity.low ?? 0}</span> low
            </span>
          </div>
        </div>
        <ul className="dim-list">
          {triggered.slice(0, 6).map((r) => (
            <li key={r.rule_id}>
              <SeverityChip severity={r.severity} size="sm" /> <span>{r.name}</span>
            </li>
          ))}
          {triggered.length > 6 && <li className="muted">+{triggered.length - 6} more</li>}
        </ul>
        <p className="dim-foot">
          {rs.not_triggered} not triggered
          {missingRules.length > 0 && (
            <>
              {" "}
              · <span className="warn-text">{missingRules.length} not evaluable (data missing)</span>
            </>
          )}
        </p>
      </Card>

      {/* 2. Evidence completeness */}
      <Card className="dim-card" title="Evidence completeness" subtitle="Required items present" actions={<GoLink label="Evidence" onClick={() => setTab("evidence")} />}>
        <div className="dim-stat">
          <span className="dim-num num">
            {comp.present} <span className="dim-of">/ {comp.required}</span>
          </span>
          <span className="dim-cap">required items present</span>
        </div>
        <Meter value={comp.present} max={comp.required} label="Evidence completeness" tone="accent" />
        {missingItems.length > 0 ? (
          <ul className="dim-list dim-list-detail">
            {missingItems.map((i) => {
              const s = CHECKLIST_STATUS[i.status] ?? { label: humanize(i.status), tone: "neutral" };
              return (
                <li key={i.key}>
                  <div className="dim-li-head">
                    <span>{i.label}</span> <Chip tone={s.tone} size="sm">{s.label}</Chip>
                  </div>
                  <span className="muted small">{i.why_it_matters}</span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="muted small">All required items are present.</p>
        )}
        <p className="dim-foot">{comp.note}</p>
      </Card>

      {/* 3. Evidence consistency */}
      <Card className="dim-card" title="Evidence consistency" subtitle="Cross-source checks">
        <div className="tri-counts">
          <div className="tri tri-good">
            <span className="num">{cons.consistent}</span> consistent
          </div>
          <div className={`tri ${cons.contradictory ? "tri-bad" : "tri-zero"}`}>
            <span className="num">{cons.contradictory}</span> contradictory
          </div>
          <div className="tri tri-neutral">
            <span className="num">{cons.unverifiable}</span> unverifiable
          </div>
        </div>
        <ul className="dim-list dim-list-detail">
          {cons.checks.map((ch, i) => (
            <li key={i}>
              <div className="dim-li-head">
                <span>{ch.check}</span>
                <Chip tone={RESULT_TONE[ch.result] ?? "neutral"} size="sm">
                  {humanize(ch.result)}
                </Chip>
              </div>
              <span className="muted small">{ch.detail}</span>
            </li>
          ))}
        </ul>
      </Card>

      {/* 4. Traceability coverage */}
      <Card className="dim-card" title="Traceability coverage" subtitle="Share of the disputed amount whose position is accounted for" actions={<GoLink label="Trail" onClick={() => setTab("graph")} />}>
        <div className="dim-stat">
          <span className="dim-num num">
            {tr.coverage_range[0] === tr.coverage_range[1]
              ? formatPct(tr.coverage_range[0])
              : `${formatPct(tr.coverage_range[0])}–${formatPct(tr.coverage_range[1])}`}
          </span>
          <span className="dim-cap">coverage range across methods</span>
        </div>
        <table className="mini-table">
          <tbody>
            {METHODS.map((m) => (
              <tr key={m}>
                <th scope="row">{METHOD_LABELS[m]}</th>
                <td className="ta-r num">{formatPct(tr.coverage[m])}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="endpoint-row" aria-label="Trail endpoints">
          {Object.entries(tr.endpoints).length === 0 && <span className="muted small">No endpoints recorded</span>}
          {Object.entries(tr.endpoints).map(([k, n]) => (
            <Chip key={k} tone="neutral" size="sm">
              {ENDPOINT_BADGE[k] ?? humanize(k)}: <span className="num">{n}</span>
            </Chip>
          ))}
        </div>
        <p className="dim-foot">
          {tr.paths} path{tr.paths === 1 ? "" : "s"}
          {tr.truncated && <span className="warn-text"> · trace truncated</span>} · {tr.note}
        </p>
      </Card>

      {/* 5. Policy eligibility */}
      <Card className="dim-card" title="Policy eligibility" subtitle="Deterministic conditions on the policy library">
        <div className="dim-stat">
          <Chip tone={polS.tone}>{polS.label}</Chip>
          <span className="dim-cap">reported {pol.report_lag_working_days} working day(s) after the transaction</span>
        </div>
        <ul className="dim-list dim-list-detail">
          {pol.clauses.map((cl) => {
            const s = POLICY_STATUS[cl.status] ?? { label: humanize(cl.status), tone: "neutral" };
            return (
              <li key={cl.clause_id}>
                <div className="dim-li-head">
                  <code className="id-chip">{cl.clause_id}</code>
                  <Chip tone={s.tone} size="sm">
                    {s.label}
                  </Chip>
                </div>
                <span className="small">{cl.text}</span>
                {cl.needs.length > 0 && (
                  <span className="small warn-text">Needs: {cl.needs.join("; ")}</span>
                )}
              </li>
            );
          })}
        </ul>
        <p className="dim-foot">{pol.note}</p>
      </Card>

      {/* 6. AI confidence */}
      <Card className="dim-card" title="AI confidence" subtitle="From the latest report, never blended with risk" actions={<GoLink label="Report" onClick={() => setTab("report")} />}>
        {!rep ? (
          <div className="dim-empty">
            <p className="dim-num muted">Not analysed</p>
            <p className="muted small">No AI report yet. Run the AI investigation on the AI report tab.</p>
          </div>
        ) : (
          <>
            <div className="dim-stat">
              <span className="dim-num num">{formatPct(rep.confidence)}</span>
              <span className="dim-cap">
                {rep.claims_supported} of {rep.claims_total} claims supported after checks
              </span>
            </div>
            <div className="endpoint-row">
              <Chip tone={REPORT_STATUS[rep.status]?.tone ?? "neutral"} size="sm">
                {REPORT_STATUS[rep.status]?.label ?? rep.status}
              </Chip>
              <Chip tone={rep.claims_flagged ? "bad" : "neutral"} size="sm">
                {rep.claims_flagged} flagged
              </Chip>
              <Chip tone="neutral" size="sm">
                v{rep.version}
              </Chip>
            </div>
            {rep.status === "facts_only" && (
              <p className="small warn-text">Generated without AI (Gemini unavailable) — every sentence built from records by code.</p>
            )}
            <p className="dim-foot">Confidence = supported claims ÷ total claims, after deterministic checks and the fact-check judge.</p>
          </>
        )}
      </Card>
    </div>
  );
}
