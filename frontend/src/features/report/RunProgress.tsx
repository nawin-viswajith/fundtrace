import { CheckCircle2, Circle, Loader2 } from "lucide-react";
import type { InvestigationRun } from "../../types/api";

const STAGE_LABEL: Record<string, string> = {
  gather: "Gathering records",
  explore: "Exploring the trail",
  evidence: "Reading evidence",
  draft: "Drafting the report",
  validate: "Checking claims",
  judge: "Fact-checking",
  finalize: "Finishing up",
};
const ORDER = ["gather", "explore", "evidence", "draft", "validate", "judge", "finalize"];

function detail(step: InvestigationRun["steps"][number]): string | null {
  if (step.node === "explore") return `${(step.tool_calls as number) || 0} lookups`;
  if (step.node === "evidence" && ((step.analysed as number) || 0) > 0) return `${step.analysed as number} read`;
  if (step.node === "judge" && (step.judged as number) !== undefined) return `${step.judged as number} checked`;
  return null;
}

/** Real progress from a background run: each row turns green only once that step has actually finished. */
export function RunProgress({ run }: { run: InvestigationRun | null }) {
  if (!run) return null;
  const done = new Set(run.steps.map((s) => s.node));
  const current = run.status === "running" ? ORDER.find((k) => !done.has(k)) : null;
  return (
    <div className="run-progress" role="status" aria-live="polite">
      <ol className="run-steps">
        {ORDER.map((node) => {
          const step = run.steps.find((s) => s.node === node);
          const isCurrent = node === current;
          return (
            <li key={node} className={`run-step ${step ? "is-done" : ""} ${isCurrent ? "is-active" : ""}`}>
              {step ? (
                <CheckCircle2 size={16} aria-hidden="true" />
              ) : isCurrent ? (
                <Loader2 size={16} className="spin" aria-hidden="true" />
              ) : (
                <Circle size={16} aria-hidden="true" />
              )}
              <span>{STAGE_LABEL[node] ?? node}</span>
              {step && detail(step) && <span className="run-step-detail">{detail(step)}</span>}
            </li>
          );
        })}
      </ol>
      <p className="small muted">
        <span className="num">{Math.round(run.elapsed_ms / 1000)}</span> s elapsed.{" "}
        {run.status === "running" ? "Each step above turns green as it actually finishes." : run.status === "failed" ? run.error : "Finished."}
      </p>
    </div>
  );
}
