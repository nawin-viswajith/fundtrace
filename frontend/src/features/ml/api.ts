/* Behaviour model (machine learning): API calls and types.

   A separate signal from the rules: how unlike the bank's other accounts an account behaves, with plain-language
   reasons. It never changes rule results, priority or any decision. Kept in its own module so the shared
   endpoint/type files stay untouched. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { request } from "../../api/client";

export type Band = "typical" | "unusual" | "very_unusual";

export interface FeatureRow {
  key: string;
  label: string;
  description: string;
  value: number | null;
  value_text: string;
  typical: number;
  typical_text: string;
  z: number | null;
  direction: "higher" | "lower" | "same" | null;
  percentile_text: string | null;
}

export interface Reason extends FeatureRow {
  text: string;
}

export interface AccountScore {
  account_id: string;
  scored: boolean;
  score: number | null;
  band: Band | null;
  band_label: string | null;
  anomaly_score?: number;
  reasons: Reason[];
  features: FeatureRow[];
  not_scored_reason: string | null;
  summary?: string;
  no_single_reason?: boolean;
}

export interface BehaviourAccount extends AccountScore {
  label: string;
  roles: string[];
}

export interface ModelBrief {
  version: string;
  status: "ok" | "not_enough_data";
  trained_at: string;
  data_as_of: string;
  window_days: number;
  accounts_scored: number;
  fingerprint: string;
  bands: Record<Band, string>;
}

export interface ModelCardFeature {
  key: string;
  label: string;
  description: string;
  typical: string | null;
}

export interface ModelCard extends ModelBrief {
  name: string;
  type: string;
  question: string;
  training: string;
  fit_seconds: number;
  accounts_not_scored: { merchant: number; high_activity: number };
  settings: Record<string, unknown>;
  contamination_note: string;
  features: ModelCardFeature[];
  how_scores_work: string;
  how_reasons_work: string;
  intended_use: string;
  limitations: string[];
}

export interface CaseBehaviourResponse {
  model: ModelBrief;
  accounts: BehaviourAccount[];
  note: string;
}

interface Agg {
  mean: number | null;
  min: number | null;
  max: number | null;
  n: number;
}

export interface HoldoutMetrics {
  label: string;
  model_version: string;
  seeds: number[];
  cases_per_seed: number;
  seconds: number;
  ml: Record<string, Agg>;
  ml_without_account_age: Record<string, Agg>;
  headline_mule_score: Agg;
  bands: Record<string, string>;
  rules: {
    per_category: Array<{
      category: string;
      label: string;
      cases: number;
      with_high_signal: number;
      rate_with_high_signal: number | null;
      ci95: [number | null, number | null];
      expectation: "at_least_one_high" | "no_high" | "none";
    }>;
    detection_fraud_with_trail: { cases: number; k: number; rate: number | null; ci95: [number | null, number | null] };
    false_alarm_merchant_and_processing: { cases: number; k: number; rate: number | null; ci95: [number | null, number | null] };
    high_signals_by_rule: Record<string, number>;
  };
  method: string[];
  caveats: string[];
}

export interface HoldoutRun {
  id: number;
  started_at: string;
  metrics: HoldoutMetrics;
  details: unknown[];
}

export interface OpsMlResponse {
  model_card: ModelCard;
  holdout: HoldoutRun | null;
  holdout_running: boolean;
}

export const mlApi = {
  caseBehaviour: (caseId: string) => request<CaseBehaviourResponse>(`/api/cases/${caseId}/behaviour`),
  opsMl: () => request<OpsMlResponse>("/api/ops/ml"),
  runEvaluation: () => request<HoldoutRun>("/api/ops/ml/evaluate", { method: "POST" }),
};

export const useCaseBehaviour = (caseId: string) =>
  useQuery({ queryKey: ["ml", "behaviour", caseId], queryFn: () => mlApi.caseBehaviour(caseId) });

export const useOpsMl = () => useQuery({ queryKey: ["ml", "ops"], queryFn: () => mlApi.opsMl() });

export const useRunMlEvaluation = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => mlApi.runEvaluation(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ml", "ops"] }),
  });
};
