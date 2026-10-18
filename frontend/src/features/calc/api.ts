/* Forensic calculation record: API calls and types.

   The record is what lets another investigator recreate the money figures from the bank's
   records: named, versioned methods, the exact inputs (with a SHA-256 fingerprint), the outputs,
   and checks on the arithmetic. Kept in its own module so the shared endpoint/type files stay
   untouched. */

import { useMutation, useQuery } from "@tanstack/react-query";
import { request } from "../../api/client";
import type { AttributionMethod, Buckets, GraphQueryParams } from "../../types/api";

export type CheckStatus = "pass" | "warn" | "fail" | "not_applicable";

export interface CalcCheckItem {
  status: CheckStatus;
  text: string;
}

export interface CalcCheck {
  id: string;
  name: string;
  what_it_checks: string;
  status: CheckStatus;
  detail: string;
  items: CalcCheckItem[];
}

export interface CalcMethod {
  id: AttributionMethod;
  name: string;
  label: string;
  version: string;
  bound: "lower" | "upper" | "estimate";
  definition: string;
  formula: string;
}

export interface AmountRange {
  txn_id: string;
  role: "disputed" | "trail" | "other_activity";
  currency: string;
  min_minor: number;
  max_minor: number;
  used_minor: number;
  used_system: string;
  used_system_label: string;
  reported: { system: string; system_label: string; record_id: string; amount_minor: number }[];
  statement: string;
  explanation: string;
}

export interface CalcInputTxn {
  id: string;
  order: number;
  occurred_at: string;
  debit_account_id: string;
  credit_account_id: string;
  amount_minor: number;
  currency: string;
  status: string;
  role: "disputed" | "trail" | "other_activity";
  treatment: "used" | "excluded_failed" | "excluded_reversed" | "excluded_reverses_reversed";
}

export interface CalcTraceParameters {
  direction: string;
  attribution_direction: string;
  depth: number;
  window_hours: number;
  max_nodes: number;
  hub_threshold: number;
  per_account_cap: number;
  expand_accounts: string[];
  window_start: string | null;
  window_end: string | null;
  activity_limit: number;
}

export interface CalcRecord {
  record_type: string;
  calc_version: string;
  case_id: string | null;
  disputed_txn_id: string;
  currency: string;
  generated_at: string;
  versions: { calc_version: string; attribution_version: string; method_versions: Record<AttributionMethod, string> };
  methods: CalcMethod[];
  method_symbols: string;
  assumptions: { id: string; text: string }[];
  kinds: { inputs: string; outputs: string; conclusions: string };
  inputs: {
    trace_parameters: CalcTraceParameters;
    accounts: { id: string; label: string; external: boolean; treatment: string }[];
    trail_txn_ids: string[];
    transactions: CalcInputTxn[];
    opening_balances: { account_id: string; as_of: string; balance_minor: number | null; label: string }[];
    fingerprint: { algorithm: string; value: string; covers: string; canonical_form: string };
  };
  outputs: {
    disputed_amount_minor: number;
    evaluable: boolean;
    buckets: Record<AttributionMethod, Buckets>;
    fingerprint: { algorithm: string; value: string };
  };
  amount_ranges: AmountRange[];
  primary_record_rule: string;
  checks: CalcCheck[];
  checks_summary: { pass: number; warn: number; fail: number; not_applicable: number; overall: CheckStatus };
}

export interface CalcVerifyResult {
  matches: boolean;
  fingerprint: string;
  output_fingerprint: string;
  expected_fingerprint: string | null;
  calc_version: string;
  differences: string[];
  checked_at: string;
}

/** The trace settings the figures were worked out with (same meaning as the graph view's). */
export type CalcParams = Partial<Pick<GraphQueryParams, "direction" | "depth" | "window_hours" | "expand">> & { max_nodes?: number };

const enc = encodeURIComponent;

export function calcQuery(p: CalcParams = {}, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams();
  if (p.direction) q.set("direction", p.direction);
  if (p.depth) q.set("depth", String(p.depth));
  if (p.window_hours) q.set("window_hours", String(p.window_hours));
  if (p.max_nodes) q.set("max_nodes", String(p.max_nodes));
  if (p.expand?.length) q.set("expand", p.expand.join(","));
  for (const [k, v] of Object.entries(extra)) q.set(k, v);
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const calcApi = {
  record: (caseId: string, p: CalcParams = {}) => request<CalcRecord>(`/api/cases/${enc(caseId)}/calculation${calcQuery(p)}`),
  /** The same record, fetched as a download: the server records the export in the case audit trail. */
  download: (caseId: string, p: CalcParams = {}) =>
    request<CalcRecord>(`/api/cases/${enc(caseId)}/calculation${calcQuery(p, { download: "1" })}`),
  verify: (caseId: string, p: CalcParams = {}, fingerprint?: string) =>
    request<CalcVerifyResult>(`/api/cases/${enc(caseId)}/calculation/verify${calcQuery(p, fingerprint ? { fingerprint } : {})}`),
};

export const calcKeys = {
  record: (caseId: string, p: CalcParams) => ["calc", caseId, calcQuery(p)] as const,
};

export const useCalcRecord = (caseId: string | null | undefined, p: CalcParams) =>
  useQuery({
    queryKey: calcKeys.record(caseId ?? "none", p),
    queryFn: () => calcApi.record(caseId as string, p),
    enabled: !!caseId,
    staleTime: 60_000,
  });

export const useVerifyCalc = (caseId: string, p: CalcParams) =>
  useMutation({ mutationFn: (fingerprint?: string) => calcApi.verify(caseId, p, fingerprint) });

export const useDownloadCalc = (caseId: string, p: CalcParams) =>
  useMutation({
    mutationFn: async () => {
      const rec = await calcApi.download(caseId, p);
      saveJson(rec, `${caseId}-calculation-${rec.inputs.fingerprint.value.slice(0, 12)}.json`);
      return rec;
    },
  });

/** Save a value as a pretty-printed JSON file in the browser. */
export function saveJson(value: unknown, filename: string): void {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
