import { AlertOctagon, Check, X } from "lucide-react";
import type { Claim, SnapshotRecord } from "../../types/api";
import { BasisChip, VerdictChip } from "../../components/Chip";
import { Citation } from "./Citation";
import { humanize } from "../../lib/format";

/** What each automatic check means, in plain words (the code stays in the tooltip). */
const ISSUE_TEXT: Record<string, string> = {
  invalid_citation: "Links to a record that is not in the case records",
  invented_id: "Mentions a record that does not exist",
  missing_citation: "No record is linked to this sentence",
  number_mismatch: "An amount does not match the linked records",
  time_mismatch: "A time does not match the linked records",
  basis_upgrade: "Says more than the records show",
  banned_phrase: "Draws a conclusion only a person may make",
};

interface ClaimViewProps {
  claim: Claim;
  records: Record<string, SnapshotRecord>;
  onShowOnGraph?: (id: string) => void;
  review?: "accept" | "reject" | undefined;
  onReview?: (v: "accept" | "reject" | undefined) => void;
  reviewDisabled?: boolean;
  strictCitations?: boolean;
}

export function ClaimView({ claim, records, onShowOnGraph, review, onReview, reviewDisabled, strictCitations = true }: ClaimViewProps) {
  const flagged = claim.flagged || !claim.valid;
  const cls = `claim ${flagged ? "is-flagged" : ""} ${claim.hallucination ? "is-hallucination" : ""} ${review === "reject" ? "is-rejected" : ""}`;
  return (
    <li className={cls} data-testid={`claim-${claim.id}`}>
      <div className="claim-body">
        <p className="claim-text">
          <span className="claim-id mono" aria-label={`Claim ${claim.id}`}>
            {claim.id}
          </span>{" "}
          {claim.text}
        </p>
        <div className="claim-meta">
          <BasisChip basis={claim.basis} />
          <VerdictChip verdict={claim.verdict} />
          {claim.hallucination && (
            <span className="chip chip-bad chip-sm" title="Possible hallucination: a linked record, amount or time does not match the case records">
              <AlertOctagon size={12} aria-hidden="true" /> May be wrong
            </span>
          )}
          {flagged && !claim.hallucination && <span className="chip chip-warn chip-sm">Needs a check</span>}
          <span className="cite-list" aria-label="Linked records">
            {claim.citations.length === 0 ? (
              <span className="muted small">no linked records</span>
            ) : (
              claim.citations.map((c) => <Citation key={c} id={c} record={records[c]} onShowOnGraph={onShowOnGraph} strict={strictCitations} />)
            )}
          </span>
        </div>
        {claim.issues.length > 0 && (
          <ul className="issue-list" aria-label="What the automatic checks found">
            {claim.issues.map((iss, i) => (
              <li key={i} className={`issue issue-${iss.severity ?? "error"}`} title={iss.code}>
                <strong>{ISSUE_TEXT[iss.code] ?? humanize(iss.code)}.</strong> {iss.detail}
              </li>
            ))}
          </ul>
        )}
        {claim.verdict_reason && claim.verdict !== "system_generated" && claim.verdict !== "supported" && (
          <p className="small muted">Fact-check: {claim.verdict_reason}</p>
        )}
      </div>
      {onReview && (
        <div className="claim-review" role="group" aria-label={`Review claim ${claim.id}`}>
          <button
            type="button"
            className={`rv-btn rv-accept ${review === "accept" ? "is-on" : ""}`}
            aria-pressed={review === "accept"}
            disabled={reviewDisabled}
            onClick={() => onReview(review === "accept" ? undefined : "accept")}
            title="Accept this sentence"
          >
            <Check size={14} aria-hidden="true" />
            <span className="sr-only">Accept</span>
          </button>
          <button
            type="button"
            className={`rv-btn rv-reject ${review === "reject" ? "is-on" : ""}`}
            aria-pressed={review === "reject"}
            disabled={reviewDisabled}
            onClick={() => onReview(review === "reject" ? undefined : "reject")}
            title="Reject this sentence"
          >
            <X size={14} aria-hidden="true" />
            <span className="sr-only">Reject</span>
          </button>
        </div>
      )}
    </li>
  );
}

export function sectionLabel(key: string, title?: string) {
  return title || humanize(key);
}
