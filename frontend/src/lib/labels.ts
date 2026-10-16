/* One place for the visual + plain-language vocabulary used across the app. */
import type { Provenance, RuleStatus, Severity } from "../types/api";

export interface ProvenanceStyle {
  label: string;
  meaning: string;
  /** CSS class suffix: prov-confirmed etc. */
  tone: Provenance;
  /** stroke-dasharray for graph edges (undefined = solid). */
  dash?: string;
  strokeWidth: number;
}

export const PROVENANCE: Record<Provenance, ProvenanceStyle> = {
  confirmed: { label: "Confirmed", meaning: "Backed by a ledger record", tone: "confirmed", strokeWidth: 2.25 },
  derived: { label: "Derived", meaning: "Calculated by code from confirmed records", tone: "derived", strokeWidth: 1.5 },
  inferred: { label: "Inferred", meaning: "Possible, not established", tone: "inferred", dash: "7 5", strokeWidth: 1.75 },
  unknown: { label: "Unknown", meaning: "Not visible or not yet analysed", tone: "unknown", dash: "2 4", strokeWidth: 1.5 },
  contradictory: { label: "Contradictory", meaning: "Sources disagree with each other", tone: "contradictory", strokeWidth: 2.25 },
};

export const PROVENANCE_ORDER: Provenance[] = ["confirmed", "derived", "inferred", "unknown", "contradictory"];

export function provenanceStyle(p: string | null | undefined): ProvenanceStyle {
  const key = (p ?? "unknown").toLowerCase().split(" ")[0] as Provenance;
  return PROVENANCE[key] ?? PROVENANCE.unknown;
}

export const SEVERITY: Record<Severity, { label: string }> = {
  high: { label: "High" },
  medium: { label: "Medium" },
  low: { label: "Low" },
};

export const RULE_STATUS: Record<RuleStatus, { label: string; hint: string; tone: string }> = {
  triggered: { label: "Triggered", hint: "The pattern was found in the records", tone: "triggered" },
  not_triggered: { label: "Not triggered", hint: "Checked against the records; the pattern was not found", tone: "clear" },
  not_evaluable: {
    label: "Not evaluable — data missing",
    hint: "The data this rule needs is missing. This is not a negative finding.",
    tone: "missing",
  },
};

export function ruleStatusInfo(s: string) {
  return RULE_STATUS[s as RuleStatus] ?? { label: s, hint: "", tone: "missing" };
}

export const ENDPOINT_BADGE: Record<string, string> = {
  visibility_ends: "Visibility ends",
  hub_paused: "High-activity",
  merchant: "Merchant",
  depth_limit: "Depth limit",
  funds_remain: "Funds may remain",
  cycle: "Cycle",
  truncated: "Result cap",
  origin_unknown: "Origin unknown",
};

export const ROLE_LABEL: Record<string, string> = {
  payer: "Payer",
  beneficiary: "Beneficiary",
  downstream: "Downstream",
  upstream: "Upstream",
  disputed: "Disputed",
  evidence: "Evidence",
  referenced: "Referenced",
};

export const BUCKET_LABELS: Record<string, { label: string; hint: string }> = {
  residual_in_visible_accounts: { label: "Still in visible accounts", hint: "Balance remaining in accounts at this bank at window end" },
  left_visibility: { label: "Left this bank's visibility", hint: "Sent to another institution; the trail continues there" },
  reached_merchant_or_hub: { label: "Reached merchant / hub", hint: "Arrived at a business or high-activity account" },
  returned_to_payer: { label: "Returned to payer", hint: "Came back to the customer's account" },
  beyond_trace_limits: { label: "Beyond trace limits", hint: "Depth, window or result caps stopped the trace" },
  unaccounted: { label: "Unaccounted", hint: "Position at window end could not be determined" },
};

export const METHOD_LABELS: Record<string, string> = {
  min: "Lower bound",
  fifo: "FIFO",
  pro_rata: "Pro-rata",
  max: "Upper bound",
};
export const METHODS = ["min", "fifo", "pro_rata", "max"] as const;

export const BASIS_LABELS: Record<string, { label: string; tone: Provenance; hint: string }> = {
  verified: { label: "Verified", tone: "confirmed", hint: "Stated directly by a confirmed record" },
  derived: { label: "Derived", tone: "derived", hint: "Calculated from records by code" },
  inferred: { label: "Inferred", tone: "inferred", hint: "Possible, not established" },
  unknown: { label: "Unknown", tone: "unknown", hint: "The records do not establish this" },
};

export const VERDICT_LABELS: Record<string, { label: string; tone: "good" | "warn" | "bad" | "neutral"; hint: string }> = {
  supported: { label: "Supported", tone: "good", hint: "The fact-check judge found the cited records support this claim" },
  partial: { label: "Partly supported", tone: "warn", hint: "The cited records support only part of the claim" },
  unsupported: { label: "Unsupported", tone: "bad", hint: "The cited records do not support the claim" },
  contradicted: { label: "Contradicted", tone: "bad", hint: "The cited records contradict the claim" },
  unjudged: { label: "Not judged", tone: "neutral", hint: "The fact-check judge was unavailable" },
  system_generated: { label: "Built from records", tone: "neutral", hint: "Written by code directly from the records, not by AI" },
};

export const REPORT_STATUS: Record<string, { label: string; tone: "good" | "warn" | "bad" | "neutral" }> = {
  verified: { label: "Verified", tone: "good" },
  partially_verified: { label: "Partially verified", tone: "warn" },
  unverified: { label: "Unverified", tone: "bad" },
  facts_only: { label: "Facts only", tone: "neutral" },
};

export const CHECKLIST_STATUS: Record<string, { label: string; tone: "good" | "warn" | "bad" | "neutral" }> = {
  present: { label: "Present", tone: "good" },
  missing: { label: "Missing", tone: "bad" },
  requested: { label: "Requested", tone: "warn" },
  received_not_analysed: { label: "Received — not analysed", tone: "warn" },
};

export const RESULT_TONE: Record<string, "good" | "warn" | "bad" | "neutral"> = {
  consistent: "good",
  matches: "good",
  contradictory: "bad",
  contradicts: "bad",
  unverifiable: "neutral",
};

export const STATUS_LABELS_FALLBACK: Record<string, string> = {
  new: "New",
  triage: "Triage",
  investigating: "Investigating",
  awaiting_evidence: "Awaiting evidence",
  ready_for_review: "Ready for review",
  escalated: "Escalated",
  resolved: "Resolved",
};

export const POLICY_STATUS: Record<string, { label: string; tone: "good" | "warn" | "bad" | "neutral" }> = {
  eligible: { label: "Eligible", tone: "good" },
  not_eligible: { label: "Not eligible", tone: "bad" },
  not_eligible_under_listed_clauses: { label: "Not eligible under listed clauses", tone: "bad" },
  needs_information: { label: "Needs information", tone: "warn" },
  conditions_met: { label: "Conditions met", tone: "good" },
  conditions_met_needs_information: { label: "Conditions met — needs information", tone: "warn" },
  conditions_not_met: { label: "Conditions not met", tone: "bad" },
  not_applicable: { label: "Not applicable", tone: "neutral" },
};

/** Record ids that can be located on the trail graph. */
export function isGraphId(id: string): boolean {
  return /^(TXN|ACC|EV)-/.test(id);
}
