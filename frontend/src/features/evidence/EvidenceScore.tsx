import type { DlpResult, EvidenceScore as Score } from "../../types/api";

export const BAND_LABEL: Record<Score["band"], string> = { strong: "Strong", moderate: "Moderate", weak: "Weak", very_weak: "Very weak" };

/** "AI label, scored by code" → "AI label, scored by the system". */
export function plainBasis(basis: string): string {
  if (basis === "code") return "checked by the system";
  return basis.replace(/\bcode\b/g, "the system");
}

export function scoreTone(v: number | null): "good" | "accent" | "warn" | "bad" | "none" {
  if (v === null) return "none";
  return v >= 75 ? "good" : v >= 50 ? "accent" : v >= 25 ? "warn" : "bad";
}

/** Compact overall figure for the evidence card header. */
export function ScoreBadge({ score }: { score: Score }) {
  return (
    <span className={`score-badge tone-${scoreTone(score.overall)}`} title={`Evidence strength ${score.overall}/100 — ${BAND_LABEL[score.band]}`}>
      <span className="num">{score.overall}</span>
      <span className="score-badge-band">{BAND_LABEL[score.band]}</span>
    </span>
  );
}

/** Evidence strength: overall score and one sub-score per category, each with its reasons. */
export function EvidenceScorePanel({ score }: { score: Score }) {
  return (
    <section className="ev-score" aria-label="Evidence strength">
      <div className="ev-score-head">
        <span className="ev-score-title">Evidence strength</span>
        <span className={`ev-score-total num tone-${scoreTone(score.overall)}`}>
          {score.overall}
          <span className="ev-score-of">/100</span>
        </span>
        <span className="ev-score-band">{BAND_LABEL[score.band]}</span>
      </div>
      {score.caps.length > 0 && (
        <p className="ev-score-cap small">
          Held down to {Math.min(...score.caps.map((c) => c.cap))} (it would be {score.uncapped}) because{" "}
          {score.caps.map((c) => c.reason.charAt(0).toLowerCase() + c.reason.slice(1)).join("; ")}.
        </p>
      )}
      <table className="ev-score-table">
        <caption className="sr-only">Sub-score per category</caption>
        <thead>
          <tr>
            <th scope="col">What was checked</th>
            <th scope="col" className="ta-r">Share of total</th>
            <th scope="col">Score out of 100</th>
          </tr>
        </thead>
        <tbody>
          {score.categories.map((c) => (
            <tr key={c.key} title={c.about}>
              <th scope="row">{c.label}</th>
              <td className="ta-r num muted">{c.weight}%</td>
              <td>
                {c.score === null ? (
                  <span className="muted small">Not assessed</span>
                ) : (
                  <span className="ev-bar-row">
                    <span
                      className="ev-bar"
                      role="meter"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={c.score}
                      aria-label={`${c.label} ${c.score} of 100`}
                    >
                      <span className={`ev-bar-fill tone-${scoreTone(c.score)}`} style={{ width: `${c.score}%` }} />
                    </span>
                    <span className="num ev-bar-value">{c.score}</span>
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <details className="disclosure">
        <summary>Why these scores</summary>
        <dl className="ev-reasons">
          {score.categories.map((c) => (
            <div key={c.key}>
              <dt>
                {c.label} <span className="muted small">· {plainBasis(c.basis)}</span>
              </dt>
              {c.reasons.map((r, i) => (
                <dd key={i}>{r}</dd>
              ))}
            </div>
          ))}
        </dl>
      </details>
      <p className="small muted">{score.note}</p>
    </section>
  );
}

/** Sensitive data found in the file (types and counts only — never the values). */
export function DlpLine({ dlp }: { dlp: DlpResult }) {
  if (dlp.status !== "scanned")
    return (
      <p className="small muted" title={dlp.note ?? undefined}>
        Personal-data check: not done for this file. Take care when copying anything from it.
      </p>
    );
  if (!dlp.findings.length)
    return (
      <p className="small muted" title={dlp.backend === "gcp" ? "Checked with Cloud DLP" : "Checked with built-in detectors"}>
        Personal-data check: nothing sensitive found.
      </p>
    );
  const restricted = dlp.findings.some((f) => f.masked_in_notes);
  return (
    <p className={`small dlp-line ${restricted ? "dlp-restricted" : ""}`}>
      <strong>{restricted ? "Contains restricted data" : "Contains personal data"}:</strong>{" "}
      {dlp.findings.map((f) => `${f.label}${f.count > 1 ? ` ×${f.count}` : ""}`).join(", ")}.
      {restricted && " Do not copy these values into notes or messages."}
    </p>
  );
}
