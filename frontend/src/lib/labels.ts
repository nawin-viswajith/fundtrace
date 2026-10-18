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
  confirmed: { label: "Recorded", meaning: "A payment in the bank's records (confirmed)", tone: "confirmed", strokeWidth: 2.25 },
  derived: { label: "Calculated", meaning: "Worked out from recorded payments (derived)", tone: "derived", strokeWidth: 1.5 },
  inferred: { label: "Possible link", meaning: "Possible, but not proven (inferred)", tone: "inferred", dash: "7 5", strokeWidth: 1.75 },
  unknown: { label: "Not known", meaning: "Not visible to this bank, or not checked yet", tone: "unknown", dash: "2 4", strokeWidth: 1.5 },
  contradictory: { label: "Records disagree", meaning: "Two sources say different things (contradictory)", tone: "contradictory", strokeWidth: 2.25 },
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
  triggered: { label: "Found", hint: "The warning sign was found in the records", tone: "triggered" },
  not_triggered: { label: "Not found", hint: "Checked against the records; the warning sign was not found", tone: "clear" },
  not_evaluable: {
    label: "Can't check — data missing",
    hint: "The data this rule needs is missing. This is not a negative finding.",
    tone: "missing",
  },
};

export function ruleStatusInfo(s: string) {
  return RULE_STATUS[s as RuleStatus] ?? { label: s, hint: "", tone: "missing" };
}

export const ENDPOINT_BADGE: Record<string, string> = {
  visibility_ends: "Left this bank",
  hub_paused: "Busy account — stopped here",
  merchant: "Merchant",
  depth_limit: "Trail stops (step limit)",
  funds_remain: "Money may still be here",
  cycle: "Money came back round",
  truncated: "Too many results",
  origin_unknown: "Source unknown",
};

export const ROLE_LABEL: Record<string, string> = {
  payer: "Customer (payer)",
  beneficiary: "Received the money",
  downstream: "Money moved on to",
  upstream: "Money came from",
  disputed: "Disputed payment",
  evidence: "Evidence",
  referenced: "Referenced",
};

export const BUCKET_LABELS: Record<string, { label: string; hint: string }> = {
  residual_in_visible_accounts: { label: "Still in accounts at this bank", hint: "Money that may still be in accounts we can see (and could be held)" },
  left_visibility: { label: "Sent to other banks", hint: "Moved to another bank; we can't see where it went from there" },
  reached_merchant_or_hub: { label: "Reached a merchant or busy account", hint: "Arrived at a business or very busy account, where tracing stops" },
  returned_to_payer: { label: "Came back to the customer", hint: "Returned to the customer's own account" },
  beyond_trace_limits: { label: "Beyond how far we looked", hint: "The search stopped at its step or time limit" },
  unaccounted: { label: "Not accounted for", hint: "Where this money ended up could not be worked out" },
};

export const METHOD_LABELS: Record<string, string> = {
  min: "Clean money spent first",
  fifo: "First in, first out",
  pro_rata: "Proportional mix",
  max: "Disputed money spent first",
};
export const METHODS = ["min", "fifo", "pro_rata", "max"] as const;

export const BASIS_LABELS: Record<string, { label: string; tone: Provenance; hint: string }> = {
  verified: { label: "From a record", tone: "confirmed", hint: "Stated directly by a bank record (verified)" },
  derived: { label: "Calculated", tone: "derived", hint: "Worked out from records by the system (derived)" },
  inferred: { label: "Possible, not proven", tone: "inferred", hint: "Possible, but the records do not establish it (inferred)" },
  unknown: { label: "Not known", tone: "unknown", hint: "The records do not show this" },
};

export const VERDICT_LABELS: Record<string, { label: string; tone: "good" | "warn" | "bad" | "neutral"; hint: string }> = {
  supported: { label: "Fact-check OK", tone: "good", hint: "The fact-check found the linked records support this sentence" },
  partial: { label: "Partly OK", tone: "warn", hint: "The linked records support only part of this sentence" },
  unsupported: { label: "Not supported", tone: "bad", hint: "The linked records do not support this sentence" },
  contradicted: { label: "Records disagree", tone: "bad", hint: "The linked records say something different" },
  unjudged: { label: "Not fact-checked yet", tone: "neutral", hint: "The fact-check did not run for this sentence; you can run it again" },
  system_generated: { label: "Built from records", tone: "neutral", hint: "Written by code directly from the records, not by AI" },
};

export const REPORT_STATUS: Record<string, { label: string; tone: "good" | "warn" | "bad" | "neutral" }> = {
  verified: { label: "Verified", tone: "good" },
  partially_verified: { label: "Partially verified", tone: "warn" },
  unverified: { label: "Unverified", tone: "bad" },
  facts_only: { label: "Facts only (no AI)", tone: "neutral" },
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

/** Plain-language names and value formats for rule thresholds (e.g. min_share 0.8 → "at least 80%"). */
const PARAM_INFO: Record<string, { label: string; format: (v: number) => string }> = {
  window_minutes: { label: "Time window", format: (v) => `${v} minutes` },
  window_hours: { label: "Time window", format: (v) => `${v} hours` },
  min_share: { label: "Share of the amount", format: (v) => `at least ${Math.round(v * 100)}%` },
  min_transfers: { label: "Onward transfers", format: (v) => `at least ${v}` },
  min_destinations: { label: "Different receiving accounts", format: (v) => `at least ${v}` },
  min_other_cases: { label: "Other disputes involving the account", format: (v) => `at least ${v}` },
  high_severity_cases: { label: "Disputes for high severity", format: (v) => `${v} or more` },
  min_failures: { label: "Failed sign-in attempts", format: (v) => `at least ${v}` },
  max_device_age_hours: { label: "Device first seen within", format: (v) => `${v} hours` },
  history_days: { label: "Device history checked", format: (v) => `${v} days` },
  lookback_days: { label: "Payment history checked", format: (v) => `${v} days` },
  min_history: { label: "Past payments needed to compare", format: (v) => `${v}` },
  multiple: { label: "Compared with the usual amount", format: (v) => `${v}× or more` },
  max_age_days: { label: "Account opened within", format: (v) => `${v} days` },
  min_other_accounts: { label: "Other accounts using the device", format: (v) => `at least ${v}` },
};

export function paramLabel(key: string): string {
  return PARAM_INFO[key]?.label ?? key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function formatParam(key: string, value: number): string {
  return PARAM_INFO[key] ? PARAM_INFO[key].format(value) : String(value);
}

/** Shares are stored as fractions (0.8) but people read percentages (80%). */
export const isShareParam = (key: string) => key.endsWith("_share");

/** Plain past-tense wording for audit-trail actions (falls back to the action name). */
const ACTIVITY: Record<string, string> = {
  case_created: "created the case",
  case_viewed: "opened the case",
  case_assigned: "changed who owns the case",
  status_changed: "changed the case status",
  note_added: "added a note",
  evidence_received: "received evidence",
  evidence_uploaded: "uploaded evidence",
  evidence_analysed: "had the AI read the evidence",
  evidence_viewed: "opened an evidence file",
  evidence_requested: "requested evidence",
  hold_requested: "approved a hold request",
  hold_declined: "declined a hold recommendation",
  category_changed: "changed the category",
  decision_recorded: "recorded the decision",
  report_generated: "ran the AI investigation",
  report_reviewed: "reviewed the AI report",
  report_exported: "printed or exported the AI report",
  report_rejudged: "re-ran the fact-check",
  report_draft_edited: "edited the AI report draft",
  report_draft_saved: "saved a new version of the AI report",
  report_draft_discarded: "discarded the AI report draft",
  assistant_message: "asked the case assistant",
  copilot_question: "asked about the case",
  rules_evaluated: "re-ran the risk checks",
  graph_expanded: "looked further along the money trail",
  login: "signed in",
};

export function activityLabel(action: string): string {
  return ACTIVITY[action] ?? action.replace(/_/g, " ");
}
