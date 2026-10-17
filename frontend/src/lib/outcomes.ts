/* Plain-language labels and formatting for outcome measurements, case age and activity. */
import type { Measurement, MeasurementKey } from "../types/api";
import { humanize } from "./format";

export interface MeasurementInfo {
  label: string;
  /** What `n` counts, singular / plural, e.g. "decided case". */
  basis: [string, string];
}

export const MEASUREMENT_INFO: Record<MeasurementKey, MeasurementInfo> = {
  median_investigation_hours: { label: "Median investigation time", basis: ["decided case", "decided cases"] },
  median_hours_to_first_action: { label: "Median time to first action", basis: ["case with an action", "cases with an action"] },
  median_hours_to_escalation: { label: "Median time to escalation", basis: ["escalated case", "escalated cases"] },
  decided_within_sla: { label: "Decided within SLA", basis: ["decided case", "decided cases"] },
  open_cases_past_sla: { label: "Open cases past SLA", basis: ["open case", "open cases"] },
  evidence_completeness_at_decision: { label: "Evidence complete at decision", basis: ["decided case", "decided cases"] },
  findings_linked_to_sources: { label: "Findings linked to sources", basis: ["report claim", "report claims"] },
  unsupported_claims_in_accepted_reports: { label: "Unsupported claims accepted", basis: ["accepted report", "accepted reports"] },
  automated_claim_rejections: { label: "Automated claim rejections", basis: ["decided case", "decided cases"] },
  investigator_actions_per_decided_case: { label: "Investigator actions per decided case", basis: ["decided case", "decided cases"] },
};

export const MEASUREMENT_GROUPS: { title: string; hint?: string; keys: MeasurementKey[] }[] = [
  {
    title: "Speed",
    keys: ["median_investigation_hours", "median_hours_to_first_action", "median_hours_to_escalation"],
  },
  {
    title: "Quality and compliance",
    keys: [
      "decided_within_sla",
      "open_cases_past_sla",
      "evidence_completeness_at_decision",
      "findings_linked_to_sources",
      "investigator_actions_per_decided_case",
    ],
  },
  {
    title: "Safeguards (target 0)",
    hint: "Both should stay at zero: the AI never declines a claim, and flagged findings need a human decision.",
    keys: ["automated_claim_rejections", "unsupported_claims_in_accepted_reports"],
  },
];

export const NOT_ENOUGH_DATA = "Not enough data yet";

function trimNumber(v: number, digits: number): string {
  const s = v.toFixed(digits);
  return s.includes(".") ? s.replace(/\.?0+$/, "") : s;
}

/** Hours: under 48 h shown in hours ("5.5 h", "36 h"); from 48 h shown in days ("6.0 d"). */
export function formatDurationHours(hours: number): string {
  if (hours >= 48) return `${(hours / 24).toFixed(1)} d`;
  if (hours < 10) return `${trimNumber(hours, 1)} h`;
  return `${Math.round(hours)} h`;
}

/**
 * The display value of a measurement, or null when there is not enough data.
 * Never returns a number for a measurement whose status is not "ok".
 */
export function formatMeasurement(m: Measurement | null | undefined): string | null {
  if (!m || m.status !== "ok" || m.value === null || !Number.isFinite(m.value)) return null;
  const v = m.value;
  switch (m.unit) {
    case "hours":
      return formatDurationHours(v);
    case "ratio":
      return `${Math.round(v * 100)}%`;
    case "count":
      return Math.round(v).toLocaleString("en-IN");
    case "actions":
      return trimNumber(v, 1);
    default:
      return String(v);
  }
}

/** "based on 1 decided case" / "based on 14 report claims". */
export function measurementBasis(key: MeasurementKey | string, n: number): string {
  const info = MEASUREMENT_INFO[key as MeasurementKey];
  const [one, many] = info?.basis ?? ["data point", "data points"];
  return `based on ${n.toLocaleString("en-IN")} ${n === 1 ? one : many}`;
}

/** Case age from reported time: "45 min", "5 h", "3 d". */
export function formatAge(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || Number.isNaN(hours) || hours < 0) return "—";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} min`;
  if (hours < 48) return `${Math.floor(hours)} h`;
  return `${Math.floor(hours / 24)} d`;
}

const ACTIVITY: Record<string, string> = {
  case_created: "Opened the case",
  case_assigned: "Assigned the case",
  category_changed: "Changed the category",
  status_changed: "Changed the status",
  note_added: "Added a note",
  decision_recorded: "Recorded a decision",
  evidence_uploaded: "Uploaded evidence",
  evidence_requested: "Requested evidence",
  evidence_received: "Received evidence",
  evidence_analysed: "Analysed evidence",
  evidence_viewed: "Viewed evidence",
  evidence_deletion_requested: "Requested evidence deletion",
  evidence_deletion_cancelled: "Cancelled evidence deletion",
  evidence_deleted: "Deleted evidence",
  report_generated: "Generated an investigation report",
  report_reviewed: "Reviewed the investigation report",
  report_exported: "Exported the report",
  copilot_question: "Asked the copilot",
  ai_classification: "Asked AI for a category",
  hold_requested: "Requested a hold",
  hold_declined: "Declined a hold",
  graph_expanded: "Expanded the trail graph",
  rules_evaluated: "Re-ran risk signals",
};

export function activityLabel(action: string): string {
  return ACTIVITY[action] ?? humanize(action);
}

/** Where a case's next action happens: the case workspace on the action's tab. */
export function caseActionHref(c: { id: string; next_action?: { tab: string } | null }): string {
  return c.next_action ? `/cases/${encodeURIComponent(c.id)}?tab=${encodeURIComponent(c.next_action.tab)}` : `/cases/${encodeURIComponent(c.id)}`;
}
