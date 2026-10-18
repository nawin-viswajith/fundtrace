/* Plain wording for the Evidence tab. The backend sends short technical labels
   ("Ledger record of the disputed transaction", "Allegation amount vs ledger");
   these maps give the version shown on screen and fall back to the original. */

import type { ChecklistItem, EvidenceItem, Reconciliation } from "../../types/api";
import { humanize } from "../../lib/format";

const CHECKLIST_PLAIN: Record<string, { label: string; why: string }> = {
  customer_allegation: {
    label: "Customer's statement of the dispute",
    why: "Says what the customer is claiming. Without it, nothing can be checked.",
  },
  disputed_txn_record: {
    label: "Bank's record of the disputed payment",
    why: "The official amount, time, accounts and payment reference (UTR).",
  },
  auth_logs: {
    label: "Sign-in records around the payment",
    why: "Shows how the customer's banking session was signed in to — failed attempts, OTP and device.",
  },
  device_record: {
    label: "Device used for the payment",
    why: "Shows whether the payment came from the customer's usual phone or a new one.",
  },
  customer_evidence: {
    label: "Customer's proof (receipt, screenshot or statement)",
    why: "Lets us compare what the customer shows with the bank's record.",
  },
  cyber_complaint_ack: {
    label: "National cyber-fraud complaint acknowledgement",
    why: "Needed before other banks can be asked to hold money.",
  },
  beneficiary_kyc: {
    label: "Details of the account that received the money (KYC, opening date)",
    why: "Who controls the receiving account helps show whether it is a mule account.",
  },
  receiving_bank_trail: {
    label: "Records from the bank that received the money",
    why: "This bank cannot see what happens after money leaves for another bank.",
  },
  merchant_response: {
    label: "Merchant's reply or proof of delivery",
    why: "Needed to weigh up a dispute with a merchant.",
  },
  scam_communication: {
    label: "Messages or calls used in the scam",
    why: "Shows how the customer was tricked.",
  },
};

export function checklistLabel(item: Pick<ChecklistItem, "key" | "label">): string {
  return CHECKLIST_PLAIN[item.key]?.label ?? item.label;
}
export function checklistWhy(item: Pick<ChecklistItem, "key" | "why_it_matters">): string {
  return CHECKLIST_PLAIN[item.key]?.why ?? item.why_it_matters;
}
export function checklistLabelByKey(key: string, items: ChecklistItem[]): string {
  const it = items.find((i) => i.key === key);
  return it ? checklistLabel(it) : (CHECKLIST_PLAIN[key]?.label ?? humanize(key));
}

/** Names of the details read from a document. */
export const FIELD_LABEL: Record<string, string> = {
  amount: "Amount",
  reference: "Payment reference (UTR)",
  date_time: "Date and time",
  payee: "Paid to",
  currency: "Currency",
  status: "Status",
};
export function fieldLabel(f: string): string {
  return FIELD_LABEL[f] ?? humanize(f);
}

/** Result of comparing a document detail with the bank's record (words, not just colour). */
export function matchLabel(result: string): string {
  if (result === "matches" || result === "consistent") return "Matches";
  if (result === "contradicts" || result === "contradictory") return "Does not match";
  if (result === "unverifiable") return "Can't check";
  return humanize(result);
}

/** "Allegation amount vs ledger" → "Amount in the customer's statement vs the bank's record". */
export function plainCheckName(check: string, evidence: Pick<EvidenceItem, "id" | "filename">[]): string {
  const file = (id: string) => {
    const e = evidence.find((x) => x.id === id);
    return e ? `“${e.filename}”` : id;
  };
  if (check === "Allegation amount vs ledger") return "Amount in the customer's statement vs the bank's record";
  if (check === "Source systems agree") return "The bank's own systems agree on this payment";
  let m = /^Source systems agree on (.+)$/.exec(check);
  if (m) return `The bank's own systems agree on the ${m[1].replace(/_/g, " ")}`;
  m = /^Evidence (\S+) vs ledger$/.exec(check);
  if (m) return `${file(m[1])} vs the bank's record`;
  m = /^(EV-\S+) (\w+)$/.exec(check);
  if (m) return `${file(m[1])}: ${fieldLabel(m[2])} vs the bank's record`;
  return check.replace(/\bvs ledger\b/g, "vs the bank's record");
}

/** Backend detail sentences say "ledger"; on screen that is "the bank's record". */
export function plainDetail(detail: string): string {
  return detail
    .replace(/\s*\((?:[a-z_]+:[^,)]+)(?:,\s*[a-z_]+:[^,)]+)*\)/g, "")
    .replace(/\bledger has\b/g, "the bank's record has")
    .replace(/\bledger:/g, "bank's record:")
    .replace(/\bthe ledger\b/g, "the bank's record")
    .replace(/\bledger\b/g, "bank's record");
}

/** One line on how a document compared with the bank's record. */
export function reconSummary(rec: Reconciliation): string {
  if (rec.contradictions > 0) return `${rec.contradictions} detail${rec.contradictions > 1 ? "s" : ""} do${rec.contradictions > 1 ? "" : "es"} not match the bank's record`;
  if (rec.matches > 0) return `${rec.matches} detail${rec.matches > 1 ? "s" : ""} match${rec.matches > 1 ? "" : "es"} the bank's record`;
  return "Nothing in the document could be compared with the bank's record";
}

export const KIND_LABEL: Record<string, string> = {
  customer_upload: "Customer's file",
  bank_record: "Bank record",
  merchant_response: "Merchant's reply",
  complaint_ack: "Complaint acknowledgement",
};
export function kindLabel(k: string): string {
  return KIND_LABEL[k] ?? humanize(k);
}
