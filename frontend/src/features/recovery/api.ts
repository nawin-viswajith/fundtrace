import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "../../api/client";

/* Recovery pools: how money in an account shared by several open disputes would be split.
   Kept in this feature folder (not the shared endpoints/types files) so it can evolve on its own. */

export type RecoveryBasis = "traced" | "disputed";

export interface RecoveryClaim {
  /** "restricted" when the viewer cannot open the case. */
  case_id: string;
  restricted?: boolean;
  status: string;
  status_label: string;
  disputed_txn_id: string | null;
  disputed_amount_minor: number;
  traced_min_minor: number;
  traced_max_minor: number;
  by_method: Record<string, number | null> | null;
  traced_as_of: string;
  eligible_minor: number;
  allocated_minor: number | null;
  share: number | null;
  hold_id: number | null;
  hold_status: string | null;
  hold_suggested_minor: number;
}

export interface RecoveryRecord {
  id: number;
  account_id: string;
  method: string;
  basis: RecoveryBasis;
  currency: string;
  available_minor: number;
  allocations: { case_id: string; eligible_minor: number; allocated_minor: number }[];
  note: string;
  recorded_by: string;
  recorded_at: string;
  effect: string;
}

export interface RecoveryPool {
  account_id: string;
  label: string;
  currency: string;
  method: string;
  basis: RecoveryBasis;
  basis_description: string;
  bases: Record<RecoveryBasis, string>;
  available_minor: number | null;
  available_source: { case_id: string; window_end: string; as_of: string; description: string } | null;
  total_eligible_minor: number;
  distributable_minor: number | null;
  left_over_minor: number | null;
  claims: RecoveryClaim[];
  double_counting: { hold_total_minor: number; available_minor: number | null; exceeds: boolean; excess_minor: number; warning: string | null };
  formula: string;
  formula_plain: string;
  assumptions: string[];
  warnings: string[];
  input_ids: string[];
  is_estimate: boolean;
  caveat: string;
  computed_at: string;
  last_recorded: RecoveryRecord | null;
}

export interface RecoveryPoolsResponse {
  pools: RecoveryPool[];
  cases_scanned: number;
  method: string;
  note: string;
}

export interface SharedAccountsResponse {
  case_id: string;
  accounts: { account_id: string; other_cases: string[] }[];
}

export const recoveryApi = {
  pools: () => request<RecoveryPoolsResponse>("/api/recovery/pools"),
  pool: (accountId: string, basis: RecoveryBasis) =>
    request<RecoveryPool>(`/api/recovery/pools/${encodeURIComponent(accountId)}?basis=${basis}`),
  record: (accountId: string, body: { basis: RecoveryBasis; note: string }) =>
    request<{ record: RecoveryRecord; pool: RecoveryPool }>(`/api/recovery/pools/${encodeURIComponent(accountId)}/record`, {
      method: "POST",
      body,
    }),
  history: (accountId: string) =>
    request<{ account_id: string; records: RecoveryRecord[]; effect: string }>(
      `/api/recovery/pools/${encodeURIComponent(accountId)}/history`,
    ),
  shared: (caseId: string) => request<SharedAccountsResponse>(`/api/recovery/cases/${encodeURIComponent(caseId)}/shared`),
};

export const recoveryKeys = {
  pools: ["recovery", "pools"] as const,
  pool: (accountId: string, basis: RecoveryBasis) => ["recovery", "pool", accountId, basis] as const,
  history: (accountId: string) => ["recovery", "history", accountId] as const,
  shared: (caseId: string) => ["recovery", "shared", caseId] as const,
};

export const useRecoveryPools = () => useQuery({ queryKey: recoveryKeys.pools, queryFn: recoveryApi.pools });

/** One pool under a chosen basis. The list already carries the default ("traced") split, so callers enable this only for the other one. */
export const useRecoveryPool = (accountId: string, basis: RecoveryBasis, enabled: boolean) =>
  useQuery({ queryKey: recoveryKeys.pool(accountId, basis), queryFn: () => recoveryApi.pool(accountId, basis), enabled });

export const useRecoveryHistory = (accountId: string, enabled: boolean) =>
  useQuery({ queryKey: recoveryKeys.history(accountId), queryFn: () => recoveryApi.history(accountId), enabled });

export const useSharedAccounts = (caseId: string) =>
  useQuery({ queryKey: recoveryKeys.shared(caseId), queryFn: () => recoveryApi.shared(caseId), retry: false, staleTime: 60_000 });

export function useRecordSplit(accountId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { basis: RecoveryBasis; note: string }) => recoveryApi.record(accountId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["recovery"] }),
  });
}
