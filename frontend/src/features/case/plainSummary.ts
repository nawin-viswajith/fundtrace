/* Plain-language sentences for the case Overview, built only from the recorded case context.
   Nothing here decides the case: each sentence restates what the records and checks show. */
import { checklistLabel } from "../evidence/plainEvidence";
import type { BucketKey, CaseContext, SlaMilestone } from "../../types/api";
import { formatIST, formatMoney } from "../../lib/format";
import { METHODS } from "../../lib/labels";
import type { TabId } from "./workspace";

/** "Rahul K (synthetic)" -> "Rahul K". The app-wide banner already says the data is synthetic. */
export function displayName(label: string | null | undefined): string {
  return (label ?? "").replace(/\s*\(synthetic\)\s*$/i, "").trim();
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Remaining time in words: "8 days", "5 hours", "40 minutes". */
export function plainDuration(hours: number): string {
  const h = Math.abs(hours);
  if (h >= 48) return plural(Math.round(h / 24), "day");
  if (h >= 1) return plural(Math.round(h), "hour");
  return plural(Math.max(1, Math.round(h * 60)), "minute");
}

/** "₹1,200", "up to ₹1,200" (when it could be nothing) or "₹13,800–₹15,000". */
export function amountRange(lo: number, hi: number, currency: string): string {
  if (lo === hi) return formatMoney(hi, currency);
  if (lo <= 0) return `up to ${formatMoney(hi, currency)}`;
  return `${formatMoney(lo, currency)}–${formatMoney(hi, currency)}`;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Lowest and highest amount in one "where the money went" bucket across the four ways of counting. */
export function bucketRange(ctx: CaseContext, key: BucketKey): [number, number] {
  const vals = METHODS.map((m) => ctx.traceability.buckets?.[m]?.[key] ?? 0);
  return [Math.min(...vals), Math.max(...vals)];
}

const BUCKET_SENTENCE: Record<BucketKey, string> = {
  left_visibility: "has moved to other banks.",
  residual_in_visible_accounts: "may still be in accounts at this bank and could be held.",
  reached_merchant_or_hub: "reached a business or a very busy account, where tracing stops.",
  returned_to_payer: "came back to the customer's own account.",
  beyond_trace_limits: "went further than the trace looked.",
  unaccounted: "could not be traced.",
};
const BUCKET_ORDER: BucketKey[] = [
  "left_visibility",
  "residual_in_visible_accounts",
  "reached_merchant_or_hub",
  "returned_to_payer",
  "beyond_trace_limits",
  "unaccounted",
];

/** One sentence per place the money may be now, largest first in reading order. */
export function whereMoneyIs(ctx: CaseContext): string[] {
  const cur = ctx.case.currency;
  if (ctx.attribution && ctx.attribution.evaluable === false) return ["The money could not be traced from the records available."];
  const out: string[] = [];
  let ranged = false;
  for (const key of BUCKET_ORDER) {
    const [lo, hi] = bucketRange(ctx, key);
    if (hi <= 0) continue;
    if (lo !== hi) ranged = true;
    out.push(`${cap(amountRange(lo, hi, cur))} ${BUCKET_SENTENCE[key]}`);
  }
  if (out.length === 0) out.push("No onward movement of the money was found in the records.");
  if (ranged) out.push("Amounts are shown as ranges because the money mixed with other money in the same accounts.");
  if (ctx.traceability.truncated) out.push("The trace was cut short because there were too many records to follow.");
  return out;
}

/** "₹15,000 was sent by UPI from Victim X savings to Rahul K on 12 Oct 2026, 15:03 IST." */
export function whatHappened(ctx: CaseContext): string {
  const t = ctx.disputed_transaction;
  const amount = formatMoney(t?.amount_minor ?? ctx.case.amount_minor, t?.currency ?? ctx.case.currency);
  const payer = displayName(ctx.payer?.label);
  const from = payer ? `the customer's account (${payer})` : "the customer's account";
  const to = displayName(ctx.beneficiary?.label) || "another account";
  const ext = ctx.beneficiary?.data?.external ? ` at ${displayName(ctx.beneficiary.data.institution) || "another bank"}` : "";
  const channel = t?.channel ? ` by ${t.channel}` : "";
  const when = t?.occurred_at ? ` on ${formatIST(t.occurred_at)}` : "";
  const kind = ctx.case.category_label ? ` The customer disputes it as: ${ctx.case.category_label.toLowerCase()}.` : "";
  return `${amount} was sent${channel} from ${from} to ${to}${ext}${when}.${kind}`;
}

/** Plain statements about missing information. Empty when nothing is missing. */
export function whatIsMissing(ctx: CaseContext): string[] {
  const out: string[] = [];
  const req = ctx.completeness.items.filter((i) => i.required && i.status !== "present");
  const list = (items: typeof req) => items.map((i) => checklistLabel(i)).join("; ");
  const missing = req.filter((i) => i.status === "missing");
  const requested = req.filter((i) => i.status === "requested");
  const unread = req.filter((i) => i.status === "received_not_analysed");
  const other = req.filter((i) => !["missing", "requested", "received_not_analysed"].includes(i.status));
  if (missing.length) out.push(`${plural(missing.length, "required item")} ${missing.length === 1 ? "is" : "are"} missing: ${list(missing)}.`);
  if (requested.length) out.push(`${plural(requested.length, "item")} asked for but not received yet: ${list(requested)}.`);
  if (unread.length) out.push(`${plural(unread.length, "item")} received but not read yet: ${list(unread)}.`);
  if (other.length) out.push(`${plural(other.length, "item")} not complete: ${list(other)}.`);
  const nc = ctx.rules_summary.not_evaluable;
  if (nc) out.push(`${plural(nc, "warning-sign check")} could not be run because information is missing.`);
  const bad = ctx.consistency.contradictory;
  if (bad) out.push(`The records disagree with each other in ${plural(bad, "place")}.`);
  return out;
}

export function whatWeFound(ctx: CaseContext): string {
  const rs = ctx.rules_summary;
  if (!rs.triggered) return "No warning signs were found in the checks that could be run.";
  const high = rs.by_severity?.high ?? 0;
  return `${plural(rs.triggered, "warning sign")} found${high ? `, ${high} of them high concern` : ""}. These are reasons to look closer, not proof.`;
}

export interface NextStep {
  text: string;
  tab?: TabId;
  /** Scroll to an element on this tab instead of switching tab. */
  anchor?: string;
  cta?: string;
}

/** What to do next, from recorded state only (mirrors the queue's next-action logic). */
export function nextSteps(ctx: CaseContext): NextStep[] {
  const c = ctx.case;
  if (c.status === "resolved") return [{ text: "This case is closed. The decision and its reasons are on the Actions & audit tab.", tab: "audit", cta: "See the decision" }];
  const out: NextStep[] = [];
  const holds = (ctx.holds ?? []).filter((h) => h.status === "recommended").length;
  if (holds)
    out.push({
      text: `Decide on ${holds === 1 ? "the suggested hold" : `the ${holds} suggested holds`} below. Money may still be recoverable, so this is the most urgent step.`,
      anchor: "case-holds",
      cta: "Go to holds",
    });
  if (c.status === "new" || c.status === "triage")
    out.push({ text: "Check where the money went on the trail and take ownership of the case.", tab: "graph", cta: "Open the money trail" });
  const items = ctx.completeness.items.filter((i) => i.required);
  if (items.some((i) => i.status === "missing")) out.push({ text: "Ask for the missing evidence.", tab: "evidence", cta: "Open Evidence" });
  if (items.some((i) => i.status === "received_not_analysed")) out.push({ text: "Read the evidence that has arrived.", tab: "evidence", cta: "Open Evidence" });
  const rep = ctx.latest_report;
  if (!rep) out.push({ text: "Run the AI investigation to get a draft report you can check.", tab: "report", cta: "Open AI report" });
  else if (rep.review_status === "pending") out.push({ text: "Review the AI report and accept or correct each statement.", tab: "report", cta: "Open AI report" });
  if (c.status === "ready_for_review") out.push({ text: "Record the decision.", tab: "audit", cta: "Open Actions & audit" });
  if (out.length === 0) out.push({ text: "When the checks are done, move the case to Ready for review." });
  // One link per destination keeps the list short.
  const seen = new Set<string>();
  return out.filter((s) => {
    const k = s.tab ?? s.anchor ?? s.text;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

const MILESTONE_TEXT: Record<string, string> = {
  shadow_credit: "Give the customer a temporary credit (shadow credit)",
  resolution: "Resolve the case",
};

export function milestoneText(m: SlaMilestone): string {
  return MILESTONE_TEXT[m.key] ?? m.label;
}

/** The next deadline (or one already missed), in words. */
export function nextDeadline(ctx: CaseContext): { text: string; breached: boolean } | null {
  if (ctx.case.status === "resolved") return null;
  const ms = ctx.sla?.milestones ?? [];
  if (!ms.length) return null;
  const late = ms.filter((m) => m.breached || m.remaining_hours < 0);
  if (late.length) {
    const m = late[0];
    return { text: `Deadline missed: ${milestoneText(m)} was due ${formatIST(m.due_at, { dateOnly: true })}.`, breached: true };
  }
  const m = [...ms].sort((a, b) => a.remaining_hours - b.remaining_hours)[0];
  return { text: `${milestoneText(m)} by ${formatIST(m.due_at, { dateOnly: true })} (${plainDuration(m.remaining_hours)} left).`, breached: false };
}
