import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { BehaviourAccount, CaseBehaviourResponse, HoldoutRun, ModelCard, OpsMlResponse } from "../features/ml/api";

const state = vi.hoisted(() => ({
  behaviour: undefined as CaseBehaviourResponse | undefined,
  ops: undefined as OpsMlResponse | undefined,
  runMutate: vi.fn(),
}));

vi.mock("../features/ml/api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../features/ml/api")>();
  return {
    ...orig,
    useCaseBehaviour: () => ({ data: state.behaviour, isLoading: false, error: null, refetch: vi.fn() }),
    useOpsMl: () => ({ data: state.ops, isLoading: false, error: null, refetch: vi.fn() }),
    useRunMlEvaluation: () => ({ mutate: state.runMutate, isPending: false, error: null }),
  };
});

import { BehaviourSection } from "../features/ml/BehaviourSection";
import MlOpsPanel from "../features/ml/MlOpsPanel";

afterEach(() => vi.restoreAllMocks());

function withQuery(children: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{children}</QueryClientProvider>);
}

const scoredAccount = (over: Partial<BehaviourAccount> = {}): BehaviourAccount => ({
  account_id: "ACC-100209",
  label: "Rahul K",
  roles: ["beneficiary"],
  scored: true,
  score: 99,
  band: "very_unusual",
  band_label: "Very unusual",
  anomaly_score: 0.7,
  reasons: [
    {
      key: "account_age_days",
      label: "Account age",
      description: "Days since the account was opened.",
      value: 8,
      value_text: "8 days",
      typical: 1611,
      typical_text: "1,611 days",
      z: 3.1,
      direction: "lower",
      percentile_text: "newer than 99% of accounts",
      text: "Account age: 8 days, newer than 99% of accounts (typical: 1,611 days).",
    },
  ],
  features: [],
  not_scored_reason: null,
  summary: "More unusual than 99% of the bank's other personal accounts.",
  no_single_reason: false,
  ...over,
});

const notScored = (over: Partial<BehaviourAccount> = {}): BehaviourAccount => ({
  account_id: "ACC-200000",
  label: "QuickMart marketplace settlement",
  roles: ["downstream"],
  scored: false,
  score: null,
  band: null,
  band_label: null,
  reasons: [],
  features: [],
  not_scored_reason: "Merchant account: its payments are business activity, so it is not compared with personal accounts.",
  ...over,
});

describe("BehaviourSection (case view, Warning signs tab)", () => {
  it("shows the model explainer, scored accounts with score/band/reasons, and not-scored accounts with a reason", async () => {
    state.behaviour = {
      model: {
        version: "behaviour-iforest-v1",
        status: "ok",
        trained_at: "2026-10-18T10:00:00Z",
        data_as_of: "2026-10-18T10:00:00Z",
        window_days: 90,
        accounts_scored: 86,
        fingerprint: "abc123",
        bands: { typical: "below 80", unusual: "80-94", very_unusual: "95+" },
      },
      accounts: [scoredAccount(), notScored()],
      note: "Unusual is not fraud. It helps you decide where to look, not what to decide.",
    };
    withQuery(<BehaviourSection caseId="CASE-24051" />);

    expect(await screen.findByText("Behaviour model (machine learning)")).toBeInTheDocument();
    expect(screen.getByText(/Unusual is not fraud/)).toBeInTheDocument();
    expect(screen.getByText(/86 of the bank's other accounts/)).toBeInTheDocument();

    const row = screen.getByText("ACC-100209").closest("li") as HTMLElement;
    expect(within(row).getByText("99")).toBeInTheDocument();
    expect(within(row).getByText("Very unusual")).toBeInTheDocument();
    fireEvent.click(within(row).getByRole("button"));
    expect(within(row).getByText(/Account age: 8 days/)).toBeInTheDocument();

    const quiet = screen.getByText("ACC-200000").closest("li") as HTMLElement;
    expect(within(quiet).getByText(/Merchant account/)).toBeInTheDocument();
  });

  it("shows an empty state when there are no trail accounts", async () => {
    state.behaviour = {
      model: {
        version: "behaviour-iforest-v1",
        status: "ok",
        trained_at: "2026-10-18T10:00:00Z",
        data_as_of: "2026-10-18T10:00:00Z",
        window_days: 90,
        accounts_scored: 86,
        fingerprint: "abc123",
        bands: { typical: "below 80", unusual: "80-94", very_unusual: "95+" },
      },
      accounts: [],
      note: "",
    };
    withQuery(<BehaviourSection caseId="CASE-24051" />);
    expect(await screen.findByText("No accounts to score")).toBeInTheDocument();
  });
});

const modelCard = (over: Partial<ModelCard> = {}): ModelCard => ({
  version: "behaviour-iforest-v1",
  status: "ok",
  trained_at: "2026-10-18T10:00:00Z",
  data_as_of: "2026-10-18T10:00:00Z",
  window_days: 90,
  accounts_scored: 86,
  fingerprint: "abc123",
  bands: { typical: "below 80", unusual: "80-94", very_unusual: "95+" },
  name: "Behaviour model",
  type: "Isolation Forest (scikit-learn 1.8.0), unsupervised anomaly detection",
  question: "How unlike the bank's other personal accounts does this account behave?",
  training: "Fitted on every in-bank personal account.",
  fit_seconds: 0.25,
  accounts_not_scored: { merchant: 7, high_activity: 4 },
  settings: { n_estimators: 200, contamination: 0.05 },
  contamination_note: "Contamination 0.05 means about 5% of accounts are expected to stand out.",
  features: [{ key: "account_age_days", label: "Account age", description: "Days since the account was opened.", typical: "1,611 days" }],
  how_scores_work: "Each account is isolated by random splits.",
  how_reasons_work: "Reasons list the measures furthest from typical.",
  intended_use: "Helps decide where to look first.",
  limitations: ["Unusual is not fraud.", "Trained and tested only on synthetic demo data."],
  ...over,
});

const holdoutRun = (over: Partial<HoldoutRun> = {}): HoldoutRun => ({
  id: 7,
  started_at: "2026-10-18T10:00:00Z",
  metrics: {
    label: "Synthetic hold-out, not real-world performance",
    model_version: "behaviour-iforest-v1",
    seeds: [101, 202, 303, 404, 505],
    cases_per_seed: 30,
    seconds: 7.3,
    ml: {
      roc_auc: { mean: 0.78, min: 0.74, max: 0.8, n: 5 },
      precision_at_k: { mean: 0.41, min: 0.36, max: 0.45, n: 5 },
      precision_at_10: { mean: 0.28, min: 0.2, max: 0.3, n: 5 },
      recall_unusual_or_higher: { mean: 0.3, min: 0.25, max: 0.38, n: 5 },
      other_accounts_unusual_or_higher: { mean: 0.17, min: 0.14, max: 0.19, n: 5 },
      accounts: { mean: 113, min: 112, max: 114, n: 5 },
      positives: { mean: 29, min: 28, max: 30, n: 5 },
    },
    ml_without_account_age: {
      roc_auc: { mean: 0.75, min: 0.7, max: 0.79, n: 5 },
      precision_at_k: { mean: 0.38, min: 0.3, max: 0.42, n: 5 },
      precision_at_10: { mean: 0.25, min: 0.2, max: 0.3, n: 5 },
      recall_unusual_or_higher: { mean: 0.28, min: 0.2, max: 0.35, n: 5 },
      other_accounts_unusual_or_higher: { mean: 0.15, min: 0.12, max: 0.18, n: 5 },
      accounts: { mean: 113, min: 112, max: 114, n: 5 },
      positives: { mean: 29, min: 28, max: 30, n: 5 },
    },
    headline_mule_score: { mean: 98.5, min: 98, max: 99, n: 5 },
    bands: { unusual_or_higher: "score 80 or more", very_unusual: "score 95 or more" },
    rules: {
      per_category: [
        {
          category: "unauthorised_transfer",
          label: "Unauthorised transfer",
          cases: 20,
          with_high_signal: 14,
          rate_with_high_signal: 0.7,
          ci95: [0.48, 0.85],
          expectation: "at_least_one_high",
        },
      ],
      detection_fraud_with_trail: { cases: 75, k: 52, rate: 0.69, ci95: [0.58, 0.79] },
      false_alarm_merchant_and_processing: { cases: 50, k: 23, rate: 0.46, ci95: [0.33, 0.6] },
      high_signals_by_rule: { R1: 10, R3: 12 },
    },
    method: ["Each seed builds a new synthetic bank."],
    caveats: ["Synthetic hold-out, not real-world performance."],
  },
  details: [],
  ...over,
});

describe("MlOpsPanel (AI & system health page)", () => {
  it("shows the model card and the hold-out numbers, with a run button only when canRun", async () => {
    state.ops = { model_card: modelCard(), holdout: holdoutRun(), holdout_running: false };
    withQuery(<MlOpsPanel canRun={true} />);

    expect(await screen.findByText("Behaviour model (machine learning)")).toBeInTheDocument();
    expect(screen.getByText("Account age")).toBeInTheDocument();
    expect(screen.getAllByText(/Unusual is not fraud/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /Run hold-out evaluation/ })).toBeInTheDocument();

    expect(screen.getByText("Synthetic hold-out, not real-world performance")).toBeInTheDocument();
    expect(screen.getByText(/78%/)).toBeInTheDocument(); // mean ROC-AUC
  });

  it("hides the run button for a role that cannot supervise", async () => {
    state.ops = { model_card: modelCard(), holdout: holdoutRun(), holdout_running: false };
    withQuery(<MlOpsPanel canRun={false} />);
    await screen.findByText("Behaviour model (machine learning)");
    expect(screen.queryByRole("button", { name: /Run hold-out evaluation/ })).not.toBeInTheDocument();
  });

  it("shows an empty state before any hold-out has run", async () => {
    state.ops = { model_card: modelCard(), holdout: null, holdout_running: false };
    withQuery(<MlOpsPanel canRun={true} />);
    expect(await screen.findByText("No hold-out run yet")).toBeInTheDocument();
  });
});
