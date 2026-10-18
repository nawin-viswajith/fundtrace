import { CheckCircle2, CircleSlash, AlertTriangle } from "lucide-react";
import type { Report, RunStep } from "../../types/api";
import { Card } from "../../components/Primitives";
import { formatMs, humanize } from "../../lib/format";

const NODE_LABEL: Record<string, string> = {
  gather: "Gather records",
  explore: "Explore trail (agent + tools)",
  evidence: "Read evidence",
  draft: "Draft report",
  validate: "Check claims (code)",
  judge: "Fact-check (judge)",
  finalize: "Finalize",
};

function stepIcon(status: string) {
  if (status === "ok" || status === "passed") return <CheckCircle2 size={15} className="good-text" aria-hidden="true" />;
  if (status === "skipped" || status === "fallback") return <CircleSlash size={15} className="muted" aria-hidden="true" />;
  return <AlertTriangle size={15} className="warn-text" aria-hidden="true" />;
}

function stepDetail(s: RunStep): string {
  const skip = new Set(["node", "status", "ms"]);
  return Object.entries(s)
    .filter(([k, v]) => !skip.has(k) && v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${humanize(k).toLowerCase()}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" · ");
}

export function AgentActivity({ report }: { report: Report }) {
  const run = report.run;
  if (!run) return null;
  return (
    <Card title="What the AI did" subtitle="Each step of the investigation, in order. The AI can only use a fixed set of lookups.">
      <ol className="step-list">
        {run.steps.map((s, i) => (
          <li key={i} className={`step step-${s.status}`}>
            {stepIcon(s.status)}
            <div>
              <div className="step-head">
                <strong>{NODE_LABEL[s.node] ?? humanize(s.node)}</strong>
                <span className="muted small num">
                  {humanize(s.status)} · {formatMs(s.ms)}
                </span>
              </div>
              {stepDetail(s) && <p className="small muted">{stepDetail(s)}</p>}
            </div>
          </li>
        ))}
      </ol>
      <h4 className="h-sub">
        Tool calls ({run.tool_log.length})
      </h4>
      {run.tool_log.length === 0 ? (
        <p className="muted small">No tool calls — the agent did not explore (AI unavailable or not needed).</p>
      ) : (
        <div className="table-wrap">
          <table className="mini-table tool-table">
            <thead>
              <tr>
                <th scope="col">Tool</th>
                <th scope="col">Target</th>
                <th scope="col">Status</th>
                <th scope="col">Reason</th>
              </tr>
            </thead>
            <tbody>
              {run.tool_log.map((t, i) => (
                <tr key={i} className={t.status === "rejected" ? "row-rejected" : ""}>
                  <td className="mono">{t.tool}</td>
                  <td className="mono">{t.target_id}</td>
                  <td>
                    <span className={`chip chip-sm ${t.status === "ok" ? "chip-good" : t.status === "rejected" ? "chip-bad" : "chip-neutral"}`}>{t.status}</span>
                  </td>
                  <td className="small">
                    {t.reason}
                    {t.detail && <span className="cell-sub">{t.detail}</span>}
                    {t.status === "ok" && <span className="cell-sub">{t.new_records} new record(s){t.round ? ` · round ${t.round}` : ""}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="small muted">
        Prompts: {Object.entries(run.prompt_versions).map(([k, v]) => `${k} ${v}`).join(" · ")}
      </p>
    </Card>
  );
}
