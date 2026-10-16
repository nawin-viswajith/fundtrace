import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CaseFilters } from "./endpoints";
import type { CaseAction, GraphQueryParams } from "../types/api";

/* Query keys: everything for one case lives under ["case", id] so a single
   invalidation after an action refreshes every tab. */
export const keys = {
  cases: (f: CaseFilters) => ["cases", f] as const,
  case: (id: string) => ["case", id] as const,
  caseCtx: (id: string) => ["case", id, "ctx"] as const,
  graph: (id: string, p: GraphQueryParams) => ["case", id, "graph", p] as const,
  timeline: (id: string) => ["case", id, "timeline"] as const,
  risk: (id: string) => ["case", id, "risk"] as const,
  evidence: (id: string) => ["case", id, "evidence"] as const,
  reports: (id: string) => ["case", id, "reports"] as const,
  audit: (id: string) => ["case", id, "audit"] as const,
  report: (rid: string) => ["report", rid] as const,
};

export const useAuthConfig = () => useQuery({ queryKey: ["auth-config"], queryFn: api.authConfig, staleTime: Infinity });
export const useMeta = () => useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: 5 * 60_000 });

export const useCases = (f: CaseFilters) => useQuery({ queryKey: keys.cases(f), queryFn: () => api.cases(f) });
export const useCase = (id: string) => useQuery({ queryKey: keys.caseCtx(id), queryFn: () => api.case(id) });
export const useGraph = (id: string, p: GraphQueryParams) =>
  useQuery({ queryKey: keys.graph(id, p), queryFn: () => api.graph(id, p), placeholderData: (prev) => prev });
export const useTimeline = (id: string) => useQuery({ queryKey: keys.timeline(id), queryFn: () => api.timeline(id) });
export const useRisk = (id: string) => useQuery({ queryKey: keys.risk(id), queryFn: () => api.risk(id) });
export const useEvidence = (id: string) => useQuery({ queryKey: keys.evidence(id), queryFn: () => api.evidence(id) });
export const useReports = (id: string) => useQuery({ queryKey: keys.reports(id), queryFn: () => api.reports(id) });
export const useReport = (rid: string | null | undefined) =>
  useQuery({ queryKey: keys.report(rid ?? "none"), queryFn: () => api.report(rid as string), enabled: !!rid });
export const useAudit = (id: string) => useQuery({ queryKey: keys.audit(id), queryFn: () => api.audit(id) });

export const useRules = () => useQuery({ queryKey: ["rules"], queryFn: api.rules });
export const useRuleHistory = (rid: string | null) =>
  useQuery({ queryKey: ["rule-history", rid], queryFn: () => api.ruleHistory(rid as string), enabled: !!rid });
export const useRings = () => useQuery({ queryKey: ["rings"], queryFn: api.rings });
export const useOpsMetrics = () => useQuery({ queryKey: ["ops", "metrics"], queryFn: api.opsMetrics });
export const useOpsCalls = () => useQuery({ queryKey: ["ops", "calls"], queryFn: api.opsCalls });
export const useOpsEvals = () => useQuery({ queryKey: ["ops", "evals"], queryFn: api.opsEvals });

/** Invalidate everything that depends on one case (all tabs + the queue). */
export function useInvalidateCase(id: string) {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: keys.case(id) }),
      qc.invalidateQueries({ queryKey: ["cases"] }),
      qc.invalidateQueries({ queryKey: ["report"] }),
    ]);
}

export function useCaseAction(id: string) {
  const invalidate = useInvalidateCase(id);
  return useMutation({ mutationFn: (body: CaseAction) => api.action(id, body), onSuccess: () => invalidate() });
}
