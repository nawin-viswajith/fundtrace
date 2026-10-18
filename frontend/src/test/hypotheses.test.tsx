import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AskLedgerResult, Hypothesis, HypothesesResult } from "../features/hypotheses/api";

const state = vi.hoisted(() => ({
  latest: undefined as HypothesesResult | undefined,
  latestLoading: false,
  latestError: null as unknown,
  runMutate: vi.fn(),
  runPending: false,
  runError: null as unknown,
  askMutate: vi.fn(),
  askPending: false,
  askData: undefined as AskLedgerResult | undefined,
  askError: null as unknown,
}));

vi.mock("../features/hypotheses/api", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../features/hypotheses/api")>();
  return {
    ...orig,
    useHypotheses: () => ({ data: state.latest, isLoading: state.latestLoading, error: state.latestError, refetch: vi.fn() }),
    useRunHypotheses: () => ({ mutate: state.runMutate, isPending: state.runPending, error: state.runError }),
    useAskLedger: () => ({ mutate: state.askMutate, isPending: state.askPending, data: state.askData, error: state.askError }),
  };
});

import { HypothesesSection } from "../features/hypotheses/HypothesesSection";

const provenHypothesis: Hypothesis = {
  statement: "At least ₹28,800 of the disputed money went from Rahul K to Sunil P.",
  rationale: "Balance arithmetic on the trail accounts (TXN-4001680).",
  typology: "fan_out",
  source: "ai",
  record_ids: ["ACC-100209", "ACC-100210"],
  verdict: "proven",
  invented_ids: [],
  checks: [
    {
      kind: "flow_at_least",
      check: { from_account: "ACC-100209", to_account: "ACC-100210", amount_rupees: 28800 },
      claim: "At least ₹28,800 of the disputed money went from Rahul K (ACC-100209) to Sunil P (ACC-100210).",
      verdict: "proven",
      summary: "Balance arithmetic forces at least ₹28,800 to have gone from Rahul K to Sunil P.",
      figures: [{ label: "Least the records force", value: "₹28,800" }],
      record_ids: ["ACC-100209", "ACC-100210", "TXN-4001680"],
      amounts_minor: { claimed: 2880000, lower: 2880000, upper: 3000000 },
    },
  ],
};

const inventedHypothesis: Hypothesis = {
  statement: "Money reached a made-up account.",
  rationale: "x",
  typology: "other",
  source: "system",
  record_ids: [],
  verdict: "invented",
  invented_ids: ["ACC-999999"],
  checks: [],
};

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <HypothesesSection caseId="CASE-24051" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  state.latest = undefined;
  state.latestLoading = false;
  state.latestError = null;
  state.runMutate = vi.fn();
  state.runPending = false;
  state.runError = null;
  state.askMutate = vi.fn();
  state.askPending = false;
  state.askData = undefined;
  state.askError = null;
});

describe("HypothesesSection", () => {
  it("shows the plain-language heading and a Run button when nothing has been run yet", () => {
    renderSection();
    expect(screen.getByRole("heading", { name: /AI ideas about where the money went/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Run$/i })).toBeInTheDocument();
    expect(screen.getByText(/No ideas have been generated/i)).toBeInTheDocument();
  });

  it("calls run when the button is clicked", async () => {
    renderSection();
    await userEvent.click(screen.getByRole("button", { name: /^Run$/i }));
    expect(state.runMutate).toHaveBeenCalled();
  });

  it("renders a proven hypothesis with its verdict chip, source label and check figures", () => {
    state.latest = { status: "ok", hypotheses: [provenHypothesis], counts: { proven: 1 } };
    renderSection();
    expect(screen.getByText(provenHypothesis.statement)).toBeInTheDocument();
    expect(screen.getByText("Suggested by AI (Gemini)")).toBeInTheDocument();
    const chips = screen.getAllByText("Proven by the records");
    expect(chips.length).toBeGreaterThan(0);
    expect(screen.getByText("₹28,800")).toBeInTheDocument();
    expect(screen.getByText("ACC-100209")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run again/i })).toBeInTheDocument();
  });

  it("shows the system-suggested label and an invented-ids rejection note", () => {
    state.latest = { status: "ai_unavailable", reason: "AI is not configured for this environment", hypotheses: [inventedHypothesis], counts: { invented: 1 } };
    renderSection();
    expect(screen.getByText("Suggested by the system (AI unavailable)")).toBeInTheDocument();
    expect(screen.getByText("Invented — rejected")).toBeInTheDocument();
    expect(screen.getByText(/ACC-999999/)).toBeInTheDocument();
    expect(screen.getByText(/AI was not available/)).toBeInTheDocument();
  });

  it("lets the investigator ask the ledger a plain question and shows the templated answer", async () => {
    renderSection();
    const input = screen.getByLabelText(/Your question/i);
    await userEvent.type(input, "Did at least 25000 reach Sunil?");
    await userEvent.click(screen.getByRole("button", { name: /^Ask$/i }));
    expect(state.askMutate).toHaveBeenCalledWith("Did at least 25000 reach Sunil?");
  });

  it("shows the code-templated ask-the-ledger answer with its verdict chip", () => {
    state.askData = {
      status: "ok",
      question: "Did at least 25000 reach Sunil?",
      verdict: "proven",
      answer: "Yes. The bank's records prove this. Balance arithmetic forces at least ₹28,800 to have gone from Rahul K to Sunil P.",
      checks: [],
    };
    renderSection();
    expect(screen.getByText(/Yes\. The bank's records prove this\./)).toBeInTheDocument();
  });

  it("disables the Ask button until at least 3 characters are typed", async () => {
    renderSection();
    const askBtn = screen.getByRole("button", { name: /^Ask$/i });
    expect(askBtn).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Your question/i), "ok");
    expect(askBtn).toBeDisabled();
  });
});
