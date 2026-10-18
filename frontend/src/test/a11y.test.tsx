/** Automated accessibility checks (axe-core via vitest-axe) on the screens most likely to regress:
 * the AI report, the warning-signs accordion, a modal dialog, and the customer portal. These check
 * real rendered markup for WCAG issues (missing labels, bad contrast, invalid ARIA) that a visual
 * review can miss; they complement, not replace, the keyboard/label assertions in the other tests. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { axe } from "./axe-helper";
import { ReportView } from "../features/report/ReportView";
import { RiskRow } from "../features/risk/RiskTab";
import { WorkspaceCtx, type WorkspaceApi } from "../features/case/workspace";
import { GenerateDataDialog } from "../features/queue/GenerateDataDialog";
import PortalHome from "../features/portal/PortalHome";
import { api } from "../api/endpoints";
import type { CaseContext, Meta, PortalProfile, Report, RuleResult } from "../types/api";

const report = JSON.parse(readFileSync(resolve(__dirname, "../../../docs/api-samples/report_ai_CASE-24044.json"), "utf-8")) as Report;

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

function withProviders(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

function withWorkspace(children: React.ReactNode) {
  const ws: WorkspaceApi = {
    caseId: "CASE-1",
    ctx: {} as CaseContext,
    setTab: vi.fn(),
    showOnGraph: vi.fn(),
    highlight: [],
    clearHighlight: vi.fn(),
  };
  return withProviders(<WorkspaceCtx.Provider value={ws}>{children}</WorkspaceCtx.Provider>);
}

describe("accessibility", () => {
  afterEach(() => vi.restoreAllMocks());

  it("the AI report has no axe violations, collapsed and expanded", async () => {
    const { container, rerender } = render(withProviders(<ReportView report={report} caseId={report.case_id} canEdit />));
    expect(await axe(container)).toHaveNoViolations();
    const first = screen.getByRole("list", { name: "Report sections" }).querySelector("button")!;
    first.click();
    rerender(withProviders(<ReportView report={report} caseId={report.case_id} canEdit />));
    expect(await axe(container)).toHaveNoViolations();
  });

  it("a warning-sign row has no axe violations, closed and open", async () => {
    // RiskRow renders an <li>; it is only ever used inside the <ul> in RiskTab (below), so the test matches that.
    const list = (open: boolean) => (
      <ul aria-label="Warning signs">
        <RiskRow rule={rule} open={open} onToggle={vi.fn()} />
      </ul>
    );
    const { container, rerender } = render(withWorkspace(list(false)));
    expect(await axe(container)).toHaveNoViolations();
    rerender(withWorkspace(list(true)));
    expect(await axe(container)).toHaveNoViolations();
  });

  it("the generate-data dialog has no axe violations (focus trap, labelled fields)", async () => {
    vi.spyOn(api, "meta").mockResolvedValue({
      statuses: [],
      status_labels: {},
      categories: { app_scam: "Authorised push-payment scam" },
      decisions: {},
      graph_relations: [],
      assignees: [],
      limits: { max_depth: 5, max_window_hours: 720, max_nodes: 300 },
    } as unknown as Meta);
    const { container } = render(withProviders(<GenerateDataDialog onClose={vi.fn()} />));
    await screen.findByRole("checkbox", { name: "Authorised push-payment scam" });
    expect(await axe(container)).toHaveNoViolations();
  });

  it("the customer portal home has no axe violations", async () => {
    vi.spyOn(api, "portalMe").mockResolvedValue({
      customer_id: "CUST-1002",
      name: "Priya N",
      is_synthetic: true,
      accounts: [],
      reasons: [],
      options: { otp_shared: {}, noticed: {}, contact_preference: {} },
    } as PortalProfile);
    vi.spyOn(api, "portalDisputes").mockResolvedValue({
      disputes: [
        {
          case_id: "CASE-24051",
          status: "Being investigated",
          step: 2,
          raised_at: "2026-10-17T14:31:00Z",
          reason: "Unauthorised transfer",
          payment: { id: "TXN-1", amount_minor: 5000000, currency: "INR", amount: "₹50,000", paid_to: "Rahul K", paid_to_bank: null, channel: "UPI", reference: "6289", status: "posted", occurred_at: "2026-10-17T13:56:00Z", from_account: "ACC-100216", dispute_case_id: "CASE-24051" },
          needs_action: 0,
        },
      ],
    });
    const { container } = render(withProviders(<PortalHome />));
    await screen.findByText("₹50,000 to Rahul K"); // wait for the dispute list query to settle, not just the static heading
    expect(await axe(container)).toHaveNoViolations();
  });
});
