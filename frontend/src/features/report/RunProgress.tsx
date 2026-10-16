import { useEffect, useState } from "react";
import { CheckCircle2, Circle, Loader2 } from "lucide-react";

export const RUN_STAGES = [
  { key: "gather", label: "Gathering records", est: 2 },
  { key: "explore", label: "Exploring trail", est: 10 },
  { key: "evidence", label: "Reading evidence", est: 12 },
  { key: "draft", label: "Drafting", est: 25 },
  { key: "validate", label: "Checking claims", est: 4 },
  { key: "judge", label: "Fact-checking", est: 12 },
];

/** Stepped progress while the investigation request is in flight (the backend runs it synchronously). */
export function RunProgress({ running }: { running: boolean }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!running) return;
    setElapsed(0);
    const start = Date.now();
    const t = window.setInterval(() => setElapsed((Date.now() - start) / 1000), 500);
    return () => window.clearInterval(t);
  }, [running]);
  if (!running) return null;
  let acc = 0;
  let active = RUN_STAGES.length - 1;
  for (let i = 0; i < RUN_STAGES.length; i++) {
    acc += RUN_STAGES[i].est;
    if (elapsed < acc) {
      active = i;
      break;
    }
  }
  return (
    <div className="run-progress" role="status" aria-live="polite">
      <ol className="run-steps">
        {RUN_STAGES.map((s, i) => (
          <li key={s.key} className={`run-step ${i < active ? "is-done" : i === active ? "is-active" : ""}`}>
            {i < active ? (
              <CheckCircle2 size={16} aria-hidden="true" />
            ) : i === active ? (
              <Loader2 size={16} className="spin" aria-hidden="true" />
            ) : (
              <Circle size={16} aria-hidden="true" />
            )}
            <span>{s.label}</span>
          </li>
        ))}
      </ol>
      <p className="small muted">
        <span className="num">{Math.round(elapsed)}</span> s elapsed. With live Gemini this takes 30–90 seconds; the steps shown are estimates
        until the run finishes and reports what actually happened.
      </p>
    </div>
  );
}
