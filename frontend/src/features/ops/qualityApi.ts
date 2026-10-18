/* Quality measurements (GET /api/ops/quality): reviewer agreement with the AI fact-check and warning-sign burden. */
import { useQuery } from "@tanstack/react-query";
import { request } from "../../api/client";

export type QualityStatus = "ok" | "not_enough_data";

export interface AgreementTable {
  accept: { supported: number; not_supported: number };
  reject: { supported: number; not_supported: number };
}

export interface ReportAgreementRow {
  report_id: string;
  case_id: string;
  version: number;
  review_status: string;
  compared: number;
  agreed: number;
  excluded: number;
  /** null below `min_report_claims` compared claims */
  agreement: number | null;
  reviewed_at: string | null;
}

export interface ReviewerAgreement {
  status: QualityStatus;
  n: number;
  min: number;
  claims_compared: number;
  agreed: number;
  agreement_rate: number | null;
  kappa: number | null;
  kappa_label: string | null;
  kappa_undefined_reason: string | null;
  table: AgreementTable;
  excluded: { unjudged: number; system_generated: number; other: number; missing: number };
  claims_not_marked: number;
  reports: number;
  per_report: ReportAgreementRow[];
  min_claims: number;
  min_report_claims: number;
  note: string;
  kappa_note: string;
  does_not_mean: string;
}

export interface RuleBurdenRow {
  rule_id: string;
  name: string;
  severity: string;
  evaluated: number;
  triggered: number;
  upheld: number;
  declined: number;
  not_evaluable: number;
  declined_share: number | null;
  status: QualityStatus;
  n: number;
  min: number;
}

export interface ReviewBurden {
  value: number | null;
  median?: number;
  status: QualityStatus;
  n: number;
  min: number;
  unit: "signals";
  note: string;
}

interface SourceCounts {
  stored: number;
  evaluated_now: number;
  failed: number;
}

export interface RuleBurden {
  rules: RuleBurdenRow[];
  review_burden: ReviewBurden;
  decided_cases: number;
  decided_cases_total: number;
  open_cases: number;
  open_cases_total: number;
  max_cases: number;
  sources: { decided: SourceCounts; open: SourceCounts };
  source_note: string;
  synthetic_cases: number;
  generator_decisions: number;
  min_cases_per_rule: number;
  demo_note: string | null;
  caveats: string[];
}

export interface QualityResponse {
  generated_at: string;
  reviewer_agreement: ReviewerAgreement;
  rule_burden: RuleBurden;
}

export const qualityApi = {
  get: () => request<QualityResponse>("/api/ops/quality"),
};

export const useOpsQuality = () => useQuery({ queryKey: ["ops", "quality"], queryFn: () => qualityApi.get() });
