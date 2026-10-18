import type { TimelineItem } from "../../types/api";
import { humanize } from "../../lib/format";

const AUTH_TITLE: Record<string, string> = {
  "login success": "Signed in",
  "login failure": "Failed sign-in attempt",
  "otp success": "One-time password (OTP) accepted",
  "otp failure": "One-time password (OTP) rejected",
};

/** Where this payment sits on the trail. */
export const TRAIL_ROLE: Record<string, string> = {
  forward: "Money moved on (where it went)",
  backward: "Earlier money (where it came from)",
};

/** Swap account ids for names ("₹50,000 UPI Priya N → Rahul K") and plain sign-in wording. */
export function plainTitle(it: Pick<TimelineItem, "kind" | "title">, names: Map<string, string>): string {
  if (it.kind === "auth_event") return AUTH_TITLE[it.title.toLowerCase()] ?? humanize(it.title);
  return it.title.replace(/\bACC-[A-Z0-9]+\b/g, (id) => names.get(id) ?? id);
}
