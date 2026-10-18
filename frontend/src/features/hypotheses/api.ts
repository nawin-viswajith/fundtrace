/* "AI ideas about where the money went — checked against the bank's records": API calls and types.

   Gemini (or, when AI is unavailable, the system's fixed pattern detectors) proposes hypotheses in a
   small, typed claim language; the server's deterministic verifier proves, allows, refutes, or rejects
   each one as invented. The amounts and verdicts shown here always come from the verifier, never from
   the AI's own words. Kept in its own module so the shared endpoint/type files stay untouched. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "../../api/client";

export type Verdict = "proven" | "possible" | "refuted" | "cannot_check" | "invented";
export type HypothesisSource = "ai" | "system";

export interface CheckFigure {
  label: string;
  value: string;
}

export interface CheckResult {
  kind: string;
  check: Record<string, unknown>;
  claim: string;
  verdict: Verdict;
  summary: string;
  figures: CheckFigure[];
  record_ids: string[];
  amounts_minor: Record<string, number | null>;
  unknown_ids?: string[];
}

export interface Hypothesis {
  statement: string;
  rationale: string;
  typology: string;
  source: HypothesisSource;
  record_ids: string[];
  verdict: Verdict;
  invented_ids: string[];
  checks: CheckResult[];
}

export interface VerdictCounts {
  proven?: number;
  possible?: number;
  refuted?: number;
  cannot_check?: number;
  invented?: number;
}

export interface HypothesesResult {
  status: "ok" | "ai_unavailable" | "none";
  run_id?: string;
  model?: string | null;
  cost_usd?: number;
  reason?: string | null;
  hypotheses: Hypothesis[];
  counts: VerdictCounts;
  generated_at?: string | null;
}

export interface AskLedgerResult {
  status: "ok" | "ai_unavailable" | "not_analysed" | "cannot_express" | "invalid";
  question?: string;
  verdict?: Verdict;
  answer: string;
  checks: CheckResult[];
  model?: string | null;
  cost_usd?: number;
}

const enc = encodeURIComponent;

export const hypothesesApi = {
  latest: (caseId: string) => request<HypothesesResult>(`/api/cases/${enc(caseId)}/hypotheses`),
  run: (caseId: string) => request<HypothesesResult>(`/api/cases/${enc(caseId)}/hypotheses`, { method: "POST" }),
  askLedger: (caseId: string, question: string) =>
    request<AskLedgerResult>(`/api/cases/${enc(caseId)}/ask-ledger`, { method: "POST", body: { question } }),
};

export const hypothesesKeys = {
  latest: (caseId: string) => ["hypotheses", caseId] as const,
};

export const useHypotheses = (caseId: string | null | undefined) =>
  useQuery({
    queryKey: hypothesesKeys.latest(caseId ?? "none"),
    queryFn: () => hypothesesApi.latest(caseId as string),
    enabled: !!caseId,
    staleTime: 30_000,
  });

export const useRunHypotheses = (caseId: string) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => hypothesesApi.run(caseId),
    onSuccess: (data) => qc.setQueryData(hypothesesKeys.latest(caseId), data),
  });
};

export const useAskLedger = (caseId: string) => useMutation({ mutationFn: (question: string) => hypothesesApi.askLedger(caseId, question) });

export const VERDICT_LABELS: Record<Verdict, string> = {
  proven: "Proven by the records",
  possible: "Possible",
  refuted: "Ruled out by the records",
  cannot_check: "Can't check",
  invented: "Invented — rejected",
};

export const VERDICT_HINTS: Record<Verdict, string> = {
  proven: "The records force this to be true.",
  possible: "Consistent with the records, but not proven.",
  refuted: "The records contradict this.",
  cannot_check: "The data needed is missing, or beyond this bank's visibility.",
  invented: "Names an account or payment that is not in this case's records.",
};

export const TYPOLOGY_LABELS: Record<string, string> = {
  fan_out: "Split to several accounts",
  layering_chain: "Passed along a chain of accounts",
  round_trip: "Came back round",
  cash_out: "Taken out as cash",
  mule_reuse: "Receiving account used in other disputes",
  rapid_pass_through: "Passed on straight away",
  other: "Other",
};
