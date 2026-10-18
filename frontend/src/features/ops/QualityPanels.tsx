/* Two plain measurement panels for supervisors: do investigators agree with the AI fact-check, and how often do
   warning signs (rules) matter for the outcome. Numbers come only from recorded reviews and decisions; small samples
   show "Not enough data yet" instead of a number. */
import { Link } from "react-router-dom";
import { Card, EmptyState, ErrorState, LoadingBlock, Meter, Note } from "../../components/Primitives";
import { Chip } from "../../components/Chip";
import { formatInt, formatPct, humanize } from "../../lib/format";
import { NOT_ENOUGH_DATA } from "../../lib/outcomes";
import { useOpsQuality, type ReviewerAgreement, type RuleBurden, type RuleBurdenRow } from "./qualityApi";

const plural = (n: number, one: string, many: string) => `${formatInt(n)} ${n === 1 ? one : many}`;

/** Highest declined share first; rules without enough data follow, most often found first. */
export function sortByDeclinedShare(rows: RuleBurdenRow[]): RuleBurdenRow[] {
  return [...rows].sort((a, b) => {
    const an = a.status !== "ok" || a.declined_share === null;
    const bn = b.status !== "ok" || b.declined_share === null;
    if (an !== bn) return an ? 1 : -1;
    if (!an && a.declined_share !== b.declined_share) return (b.declined_share ?? 0) - (a.declined_share ?? 0);
    if (a.triggered !== b.triggered) return b.triggered - a.triggered;
    return a.rule_id.localeCompare(b.rule_id, undefined, { numeric: true });
  });
}

function Stat({ label, value, sub, empty }: { label: string; value: string | null; sub?: string; empty?: boolean }) {
  return (
    <div className="kpi" role="group" aria-label={label}>
      <span className="kpi-label">{label}</span>
      {value === null || empty ? <span className="q-nodata">{NOT_ENOUGH_DATA}</span> : <span className="kpi-value num">{value}</span>}
      {sub && <span className="kpi-sub">{sub}</span>}
    </div>
  );
}

export default function QualityPanels() {
  const q = useOpsQuality();
  if (q.isLoading) return <LoadingBlock label="Loading quality measurements" lines={6} />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load quality measurements" />;
  if (!q.data) return null;
  return (
    <>
      <AgreementPanel a={q.data.reviewer_agreement} />
      <RuleBurdenPanel b={q.data.rule_burden} />
    </>
  );
}

// ---------------------------------------------------------------------------- reviewer agreement

function AgreementPanel({ a }: { a: ReviewerAgreement }) {
  const ok = a.status === "ok" && a.agreement_rate !== null;
  const left = a.excluded.unjudged + a.excluded.system_generated + a.excluded.other + a.excluded.missing;
  const t = a.table;
  return (
    <Card
      title="Do investigators agree with the AI fact-check?"
      subtitle="Each claim an investigator marked accept or reject in a report review, compared with the AI fact-check verdict on the same claim."
      className="q-panel"
    >
      {a.reports === 0 ? (
        <EmptyState title="No reviewed reports yet">
          This fills in once investigators review report claims (accept or reject each one) on the case's AI report tab.
        </EmptyState>
      ) : (
        <div className="stack">
          <div className="kpi-grid kpi-grid-sm">
            <Stat
              label="Agreement"
              value={ok ? formatPct(a.agreement_rate, 0) : null}
              sub={ok ? `${formatInt(a.agreed)} of ${plural(a.claims_compared, "claim", "claims")}` : `${plural(a.claims_compared, "claim", "claims")} compared, needs at least ${a.min_claims}`}
            />
            <Stat
              label="Agreement beyond chance (kappa)"
              value={ok ? (a.kappa === null ? "—" : a.kappa.toFixed(2)) : null}
              sub={ok ? (a.kappa === null ? "Not computable" : humanize(a.kappa_label)) : undefined}
            />
            <Stat label="Reviewed reports" value={formatInt(a.reports)} />
            <Stat
              label="Claims left out"
              value={formatInt(left)}
              sub={`${formatInt(a.excluded.unjudged)} not fact-checked · ${formatInt(a.excluded.system_generated)} written by code`}
            />
          </div>

          <div className="q-split">
            <table className="mini-table q-matrix" aria-label="Investigator review against AI fact-check">
              <thead>
                <tr>
                  <th scope="col"><span className="sr-only">Investigator</span></th>
                  <th scope="col" className="ta-r">AI: supported or partly</th>
                  <th scope="col" className="ta-r">AI: unsupported or contradicted</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">Investigator accepted</th>
                  <td className="ta-r num q-agree">{formatInt(t.accept.supported)}</td>
                  <td className="ta-r num">{formatInt(t.accept.not_supported)}</td>
                </tr>
                <tr>
                  <th scope="row">Investigator rejected</th>
                  <td className="ta-r num">{formatInt(t.reject.supported)}</td>
                  <td className="ta-r num q-agree">{formatInt(t.reject.not_supported)}</td>
                </tr>
              </tbody>
            </table>
            <div className="q-explain small">
              <p><span className="q-key" aria-hidden="true" /> Shaded cells are agreement. The other two are claims where the investigator and the AI saw it differently.</p>
              <p><strong>Kappa</strong> — {a.kappa_note}</p>
              {ok && a.kappa === null && a.kappa_undefined_reason && <p className="muted">{a.kappa_undefined_reason}</p>}
            </div>
          </div>

          <p className="small muted">{a.note}</p>
          <Note tone="neutral">{a.does_not_mean}</Note>

          <div className="table-wrap">
            <table className="table table-compact" aria-label="Agreement per report">
              <thead>
                <tr>
                  <th scope="col">Case</th>
                  <th scope="col" className="ta-r">Report version</th>
                  <th scope="col">Review</th>
                  <th scope="col" className="ta-r">Claims compared</th>
                  <th scope="col" className="ta-r">Agreed</th>
                  <th scope="col" className="ta-r">Agreement</th>
                  <th scope="col" className="ta-r">Left out</th>
                </tr>
              </thead>
              <tbody>
                {a.per_report.map((r) => {
                  const st = REPORT_REVIEW[r.review_status];
                  return (
                    <tr key={r.report_id}>
                      <td data-label="Case"><Link className="link mono" to={`/cases/${r.case_id}?tab=report`}>{r.case_id}</Link></td>
                      <td data-label="Report version" className="ta-r num">v{r.version}</td>
                      <td data-label="Review"><Chip size="sm" tone={st?.tone ?? "neutral"}>{st?.label ?? humanize(r.review_status)}</Chip></td>
                      <td data-label="Claims compared" className="ta-r num">{formatInt(r.compared)}</td>
                      <td data-label="Agreed" className="ta-r num">{formatInt(r.agreed)} of {formatInt(r.compared)}</td>
                      <td data-label="Agreement" className="ta-r num">
                        {r.agreement === null ? <span className="muted small" title={`Shown from ${a.min_report_claims} compared claims`}>Too few claims</span> : formatPct(r.agreement, 0)}
                      </td>
                      <td data-label="Left out" className="ta-r num">{formatInt(r.excluded)}</td>
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

const REPORT_REVIEW: Record<string, { label: string; tone: "good" | "warn" | "bad" | "neutral" }> = {
  accepted: { label: "Accepted", tone: "good" },
  partial: { label: "Partly accepted", tone: "warn" },
  rejected: { label: "Rejected", tone: "bad" },
};

// ---------------------------------------------------------------------------- warning-sign burden

function RuleBurdenPanel({ b }: { b: RuleBurden }) {
  const rows = sortByDeclinedShare(b.rules);
  const rb = b.review_burden;
  const src = b.sources.decided;
  return (
    <Card
      title="Warning signs: how often do they matter?"
      subtitle="For decided cases: how often each warning sign was found, and whether the customer's claim was then upheld or declined."
      className="q-panel"
    >
      <div className="stack">
        {b.demo_note && <Note tone="warn"><strong>Demo figures.</strong> {b.demo_note}</Note>}
        <div className="kpi-grid kpi-grid-sm">
          <Stat
            label="Decided cases checked"
            value={formatInt(b.decided_cases)}
            sub={b.decided_cases_total > b.decided_cases ? `most recent ${formatInt(b.decided_cases)} of ${formatInt(b.decided_cases_total)}` : "upheld, partly upheld or declined"}
          />
          <Stat
            label="Warning signs per open case"
            value={rb.status === "ok" && rb.value !== null ? rb.value.toFixed(1) : null}
            sub={rb.status === "ok" ? `average over ${plural(rb.n, "open case", "open cases")}` : undefined}
          />
        </div>
        <p className="small muted">{rb.note}</p>

        {b.decided_cases === 0 ? (
          <EmptyState title="No decided cases yet">This fills in once cases are resolved with a decision (claim upheld, partly upheld or declined).</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table table-compact q-rules" aria-label="Warning signs in decided cases">
              <thead>
                <tr>
                  <th scope="col">Warning sign</th>
                  <th scope="col" className="ta-r">Found in decided cases</th>
                  <th scope="col" className="ta-r">Claim upheld</th>
                  <th scope="col" className="ta-r">Claim declined</th>
                  <th scope="col">Declined share</th>
                  <th scope="col" className="ta-r">Could not check</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.rule_id}>
                    <td data-label="Warning sign">
                      {r.name}
                      <span className="cell-sub mono">{r.rule_id}</span>
                    </td>
                    <td data-label="Found" className="ta-r num">
                      {formatInt(r.triggered)}
                      <span className="cell-sub">of {formatInt(r.evaluated)} checked</span>
                    </td>
                    <td data-label="Claim upheld" className="ta-r num">{formatInt(r.upheld)}</td>
                    <td data-label="Claim declined" className="ta-r num">{formatInt(r.declined)}</td>
                    <td data-label="Declined share">
                      {r.status === "ok" && r.declined_share !== null ? (
                        <div className="q-share">
                          <Meter value={r.declined_share} label={`${r.name}: ${formatPct(r.declined_share, 0)} declined`} />
                          <span className="num">{formatPct(r.declined_share, 0)}</span>
                        </div>
                      ) : (
                        <span className="q-nodata small" title={`Shown once the sign is found in ${b.min_cases_per_rule} decided cases`}>
                          {NOT_ENOUGH_DATA}
                        </span>
                      )}
                    </td>
                    <td data-label="Could not check" className="ta-r num">{formatInt(r.not_evaluable)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="q-foot small muted">
          <p>
            <strong>Declined share</strong> = claims declined ÷ decided cases where the sign was found (shown from {b.min_cases_per_rule} cases).
            Upheld includes partly upheld.
          </p>
          <ul>
            {b.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
          <p>
            {b.source_note} Decided cases: {formatInt(src.stored)} from a saved check, {formatInt(src.evaluated_now)} checked now
            {src.failed ? `, ${formatInt(src.failed)} could not be checked` : ""}.
          </p>
        </div>
      </div>
    </Card>
  );
}
