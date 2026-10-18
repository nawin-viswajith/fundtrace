import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { RiskRow } from "../features/risk/RiskTab";
import { CaseAssistant } from "../features/case/CaseAssistant";
import { WorkspaceCtx, type WorkspaceApi } from "../features/case/workspace";
import { formatParam, paramLabel } from "../lib/labels";
import { api } from "../api/endpoints";
import type { CaseContext, RuleResult } from "../types/api";

const rule: RuleResult = {
  rule_id: "R1",
  name: "Rapid onward movement",
  version: 1,
  severity: "high",
  status: "triggered",
  facts: [
    { text: "₹15,000 credited to ACC-100209 at 11:09 IST.", source_ids: ["TXN-4001646"] },
    { text: "Threshold met: ≥80% moved on within 60 min.", source_ids: [] },
  ],
  source_ids: ["TXN-4001646"],
  params: { window_minutes: 60, min_share: 0.8 },
  limitations: ["Shows recorded onward transfers only."],
  missing_fields: [],
  suggested_step: "Consider a hold on visible downstream accounts.",
  evaluated_at: "2026-10-18T00:00:00Z",
} as RuleResult;

function withWorkspace(children: ReactNode, over: Partial<WorkspaceApi> = {}) {
  const ws: WorkspaceApi = {
    caseId: "CASE-1",
    ctx: {} as CaseContext,
    setTab: vi.fn(),
    showOnGraph: vi.fn(),
    highlight: [],
    clearHighlight: vi.fn(),
    ...over,
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <WorkspaceCtx.Provider value={ws}>{children}</WorkspaceCtx.Provider>
    </QueryClientProvider>
  );
}

describe("risk signals accordion", () => {
  it("is collapsed: shows the name, a plain summary and the outcome, and expands on click", async () => {
    const toggle = vi.fn();
    const { rerender } = render(withWorkspace(<RiskRow rule={rule} open={false} onToggle={toggle} />));
    const head = screen.getByRole("button", { name: /Rapid onward movement/ });
    expect(head).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Threshold met: ≥80% moved on within 60 min.")).toBeInTheDocument();
    expect(screen.getByText("Found")).toBeInTheDocument();
    expect(screen.queryByText("What we found")).not.toBeInTheDocument();
    await userEvent.click(head);
    expect(toggle).toHaveBeenCalled();
    rerender(withWorkspace(<RiskRow rule={rule} open onToggle={toggle} />));
    expect(screen.getByText("What we found")).toBeInTheDocument();
    expect(screen.getByText("at least 80%")).toBeInTheDocument(); // 0.8 is shown as a percentage
    expect(screen.getByText("60 minutes")).toBeInTheDocument();
  });

  it("names thresholds in plain words", () => {
    expect(paramLabel("min_share")).toBe("Share of the amount");
    expect(formatParam("min_share", 0.8)).toBe("at least 80%");
    expect(formatParam("multiple", 5)).toBe("5× or more");
    expect(paramLabel("something_new")).toBe("Something new");
  });
});

describe("case assistant", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("opens from the bubble, answers with record references, and links to the report after an edit", async () => {
    const setTab = vi.fn();
    const ask = vi
      .spyOn(api, "assistant")
      .mockResolvedValueOnce({
        status: "ok",
        claims: [{ id: "C1", text: "The money went to ACC-100209.", citations: ["ACC-100209"], basis: "verified", issues: [], valid: true, verdict: "supported", hallucination: false, flagged: false }],
        records: {},
        follow_up_questions: ["What evidence is missing?"],
      })
      .mockResolvedValueOnce({
        status: "ok",
        text: "Cleared “Limitations and uncertainty” (2 statements) in the draft. Nothing is saved yet.",
        claims: [],
        records: {},
        follow_up_questions: [],
        action: { kind: "clear_section", section_key: "limitations", claim_ids: ["C30", "C31"], changed: true },
        navigate: { tab: "report", section: "limitations" },
      });
    render(withWorkspace(<CaseAssistant />, { setTab }));
    const u = userEvent.setup();
    await u.click(screen.getByRole("button", { name: "Open the case assistant" }));
    expect(screen.getByRole("dialog", { name: /Case assistant/ })).toBeInTheDocument();
    await u.click(screen.getByRole("button", { name: "Where did the money go?" }));
    expect(await screen.findByText("The money went to ACC-100209.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "What evidence is missing?" })).toBeInTheDocument();
    await u.type(screen.getByLabelText("Message"), "clear the limitations section{Enter}");
    expect(ask).toHaveBeenLastCalledWith("CASE-1", "clear the limitations section", expect.any(Array));
    await u.click(await screen.findByRole("button", { name: "Open the AI report to review and save" }));
    expect(setTab).toHaveBeenCalledWith("report");
  });
});
