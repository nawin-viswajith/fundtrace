import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { Printer } from "lucide-react";
import { api } from "../../api/endpoints";
import { ErrorState, LoadingBlock, Time } from "../../components/Primitives";
import { ProvenanceLegend } from "../../components/Domain";
import { BASIS_LABELS, REPORT_STATUS, VERDICT_LABELS } from "../../lib/labels";
import { formatPct, formatUsd, humanize, shortHash } from "../../lib/format";

/** Clean, print-styled report. Loading it via /export records a report_exported audit event. */
export default function ReportPrint() {
  const { caseId = "", reportId = "" } = useParams();
  const q = useQuery({ queryKey: ["report-export", reportId], queryFn: () => api.exportReport(reportId), staleTime: Infinity });
  if (q.isLoading)
    return (
      <div className="print-page">
        <LoadingBlock label="Preparing report" lines={10} />
      </div>
    );
  if (q.error || !q.data)
    return (
      <div className="print-page">
        <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't export the report" />
      </div>
    );
  const r = q.data;
  const s = REPORT_STATUS[r.status]?.label ?? humanize(r.status);
  const cited = Object.keys(r.records).sort();
  return (
    <div className="print-page">
      <div className="print-toolbar no-print">
        <button type="button" className="btn btn-primary" onClick={() => window.print()}>
          <Printer size={16} aria-hidden="true" /> Print or save as PDF
        </button>
        <span className="muted small">This export was recorded in the case audit trail.</span>
      </div>
      <header className="print-head">
        <p className="print-synthetic">SYNTHETIC DEMO DATA — not real customers or bank records</p>
        <h1>
          FundTrace investigation report · {caseId} · v{r.version}
        </h1>
        <p>
          Status: <strong>{s}</strong> · Review: {humanize(r.review_status)} · Generated <Time iso={r.created_at} /> by {r.generator}
        </p>
        {r.status === "facts_only" && <p className="print-warn">Generated without AI (Gemini unavailable) — every sentence built from records.</p>}
        <p>
          Claims {r.metrics.claims_total} · supported {r.metrics.claims_supported} · flagged {r.metrics.claims_flagged} · hallucination rate{" "}
          {formatPct(r.metrics.hallucination_rate, 1)} · confidence {formatPct(r.metrics.confidence)} · cost {formatUsd(r.metrics.cost_usd)}
        </p>
        <p className="small">
          Snapshot {shortHash(r.snapshot_hash, 24)} · report {r.id}
          {r.trace_id ? ` · trace ${r.trace_id}` : ""}
        </p>
        <p className="small">AI output is a draft for investigator review. It does not decide the claim or assign liability.</p>
      </header>
      {r.sections.map((sec) => (
        <section key={sec.key} className="print-section">
          <h2>{sec.title}</h2>
          <ol>
            {sec.claims.map((c) => (
              <li key={c.id} className={c.flagged ? "print-flagged" : ""}>
                <span>{c.text}</span>{" "}
                <span className="print-meta">
                  [{BASIS_LABELS[c.basis]?.label ?? c.basis}; {VERDICT_LABELS[c.verdict]?.label ?? c.verdict}
                  {c.hallucination ? "; POSSIBLE HALLUCINATION" : ""}; cites {c.citations.join(", ") || "none"}]
                </span>
                {c.issues.length > 0 && <div className="print-issues">Issues: {c.issues.map((i) => `${i.code}: ${i.detail}`).join("; ")}</div>}
              </li>
            ))}
          </ol>
        </section>
      ))}
      <section className="print-section">
        <h2>Recommended actions (suggestions only)</h2>
        <ul>
          {r.recommended_actions.map((a, i) => (
            <li key={i}>
              {humanize(a.action_type)}: {a.description} [cites {a.citations.join(", ")}]
            </li>
          ))}
        </ul>
      </section>
      <section className="print-section">
        <h2>Cited records</h2>
        <table className="print-table">
          <tbody>
            {cited.map((id) => (
              <tr key={id}>
                <th scope="row">{id}</th>
                <td>
                  {Object.entries(r.records[id])
                    .map(([k, v]) => `${humanize(k)}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
                    .join(" · ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="print-section">
        <h2>Provenance labels</h2>
        <ProvenanceLegend showLines={false} />
      </section>
    </div>
  );
}
