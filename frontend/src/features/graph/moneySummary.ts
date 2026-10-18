/* Plain-language summary of the money-tracing figures.

   The backend works out where the disputed money went with four tracing methods
   (METHOD_LABELS). They are named by convention, not by size: for money still in an
   account, "Clean money spent first" gives the HIGHEST figure. So a plain sentence never
   names a method — it uses the smallest and largest of the four values. */

import type { Attribution, AttributionMethod, BucketKey } from "../../types/api";
import { METHODS } from "../../lib/labels";
import { formatMoney } from "../../lib/format";

export interface Span {
  min: number;
  max: number;
}

/** Smallest and largest value across the four methods (missing values are ignored). */
export function spanOf(values: Partial<Record<AttributionMethod, number>> | null | undefined): Span {
  const vs = METHODS.map((m) => values?.[m]).filter((v): v is number => typeof v === "number" && !Number.isNaN(v));
  if (!vs.length) return { min: 0, max: 0 };
  return { min: Math.min(...vs), max: Math.max(...vs) };
}

/** "₹1,200", "up to ₹1,200" or "₹13,800–₹15,000". */
export function plainRange(s: Span, currency: string, { capital = false } = {}): string {
  if (s.min === s.max) return formatMoney(s.max, currency);
  if (s.min <= 0) return `${capital ? "Up" : "up"} to ${formatMoney(s.max, currency)}`;
  return `${formatMoney(s.min, currency)}–${formatMoney(s.max, currency)}`;
}

export const BUCKET_ORDER: BucketKey[] = [
  "residual_in_visible_accounts",
  "left_visibility",
  "reached_merchant_or_hub",
  "returned_to_payer",
  "beyond_trace_limits",
  "unaccounted",
];

/** What happened to that money, as the end of a sentence that starts with an amount. */
const BUCKET_SENTENCE: Record<BucketKey, string> = {
  residual_in_visible_accounts: "may still be in accounts at this bank and could be held",
  left_visibility: "has moved to other banks",
  reached_merchant_or_hub: "reached a merchant or a very busy account, where tracing stops",
  returned_to_payer: "came back to the customer's own account",
  beyond_trace_limits: "went further than this search looked",
  unaccounted: "could not be traced",
};

export interface BucketSummary {
  key: BucketKey;
  span: Span;
  sentence: string;
}

/** Non-zero destinations of the disputed money, largest first. */
export function summariseBuckets(att: Attribution): BucketSummary[] {
  const cur = att.currency;
  return BUCKET_ORDER.map((key) => {
    const span = spanOf(Object.fromEntries(METHODS.map((m) => [m, att.buckets?.[m]?.[key] ?? 0])));
    return { key, span, sentence: `${plainRange(span, cur, { capital: true })} ${BUCKET_SENTENCE[key]}.` };
  })
    .filter((b) => b.span.max > 0)
    .sort((a, b) => b.span.max - a.span.max || BUCKET_ORDER.indexOf(a.key) - BUCKET_ORDER.indexOf(b.key));
}

/** One or two plain sentences that answer "where is the money?". */
export function leadSentence(att: Attribution): string {
  if (!att.evaluable) return "We could not work out where the money went, because some of the data needed is missing. This is not the same as finding nothing.";
  const parts = summariseBuckets(att);
  if (!parts.length) return "The records do not show the disputed money moving anywhere yet.";
  return parts
    .slice(0, 3)
    .map((p) => p.sentence)
    .join(" ");
}

/** Plain explanation of each tracing method (shown inside "Show how this was worked out"). */
export const METHOD_EXPLAINED: Record<AttributionMethod, string> = {
  min: "Assumes each account spent its own money before the disputed money. This keeps the most disputed money in the first accounts and moves the least onward.",
  fifo: "Money leaves an account in the order it arrived — the oldest money goes out first.",
  pro_rata: "Every payment out carries the same mix of disputed and other money that the account held at that moment.",
  max: "Assumes the disputed money was spent before anything else. This moves the most disputed money onward.",
};
