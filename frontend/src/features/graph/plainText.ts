/* Plain wording used only on the "Where the money went" (trail graph) screen. */

import type { GraphNode } from "../../types/api";
import { humanize } from "../../lib/format";

/** Names of the kinds of line on the map. */
export const RELATION_LABEL: Record<string, string> = {
  sent: "Paid out by",
  received_by: "Paid into",
  possible_onward_funding: "Possible onward payment",
  reversal_of: "Reverses an earlier payment",
  supports: "Evidence supports this",
  contradicts: "Evidence contradicts this",
  relates_to: "Evidence about this",
};

/** Filter chip wording for the same relations. */
export const RELATION_FILTER_LABEL: Record<string, string> = {
  sent: "Money paid out",
  received_by: "Money paid in",
  possible_onward_funding: "Possible onward payments",
  reversal_of: "Reversals",
  supports: "Evidence that supports",
  contradicts: "Evidence that contradicts",
  relates_to: "Other evidence links",
};

export function relationLabel(type: string): string {
  return RELATION_LABEL[type] ?? humanize(type);
}

export const DIRECTION_LABEL: Record<string, string> = {
  backward: "where the money came from",
  forward: "where the money went",
  both: "where the money came from and where it went",
  root: "the disputed payment",
};

export function directionLabel(d: string | null | undefined): string {
  return DIRECTION_LABEL[d ?? ""] ?? humanize(d ?? "");
}

export function windowLabel(hours: number): string {
  if (hours % 24 === 0) {
    const days = hours / 24;
    return days === 1 ? "24 hours" : `${days} days`;
  }
  return `${hours} hours`;
}

export const STATUS_LABEL: Record<string, string> = {
  posted: "Posted",
  pending: "Pending",
  failed: "Failed",
  reversed: "Reversed",
  failure: "Failed",
  success: "Succeeded",
};

export function statusLabel(s: string | null | undefined): string {
  return STATUS_LABEL[s ?? ""] ?? humanize(s ?? "");
}

/** Drop the "(synthetic)" marker the demo data carries on every name. */
export function cleanName(label: string | null | undefined): string {
  return (label ?? "").replace(/\s*\(synthetic\)/gi, "").trim();
}

/** A person-readable name for any record on the map, falling back to its id. */
export function nodeName(n: GraphNode | undefined, fallbackId: string): string {
  if (!n) return fallbackId;
  if (n.type === "account") return cleanName(n.label) || n.id;
  return cleanName(n.label) || n.id;
}
