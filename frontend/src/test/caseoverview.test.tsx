import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { OverviewTab } from "../features/case/OverviewTab";
import { WorkspaceCtx, type WorkspaceApi } from "../features/case/workspace";
import { amountRange, displayName, whereMoneyIs } from "../features/case/plainSummary";
import type { CaseContext, Hold } from "../types/api";

const sample = JSON.parse(readFileSync(resolve(__dirname, "../../../docs/api-samples/case_CASE-24051.json"), "utf-8")) as CaseContext;

const hold: Hold = {
  id: 7,
  account_id: "ACC-100210",
  amount_minor: 1900000,
  currency: "INR",
  basis: { method: "attribution upper bound, capped by balance" },
  status: "recommended",
  recommended_by: "system (attribution)",
  decision_note: null,
  created_at: "2026-10-18T00:00:00Z",
  decided_at: null,
};

function renderTab(ctx: CaseContext, setTab = vi.fn()) {
  const ws: WorkspaceApi = { caseId: ctx.case.id, ctx, setTab, showOnGraph: vi.fn(), highlight: [], clearHighlight: vi.fn() };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <WorkspaceCtx.Provider value={ws}>
        <OverviewTab />
      </WorkspaceCtx.Provider>
    </QueryClientProvider>,
  );
  return setTab;
}

describe("plain-language summary helpers", () => {
  it("formats ranges as at least / up to amounts and strips the synthetic suffix from names", () => {
    expect(amountRange(0, 120000, "INR")).toBe("up to ₹1,200");
    expect(amountRange(1380000, 1500000, "INR")).toBe("₹13,800–₹15,000");
    expect(amountRange(500, 500, "INR")).toBe("₹5");
    expect(displayName("Rahul K (synthetic)")).toBe("Rahul K");
  });

  it("says where the money is now in plain sentences", () => {
    const lines = whereMoneyIs(sample);
    expect(lines[0]).toBe("₹29,800–₹32,000 has moved to other banks.");
    expect(lines[1]).toBe("₹18,000–₹20,200 may still be in accounts at this bank and could be held.");
  });
});

describe("case overview tab", () => {
  it("reads top to bottom: statement, at a glance, six checks, holds", () => {
    renderTab({ ...sample, can_edit: true, holds: [hold] });
    const h2 = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(h2).toEqual(["What the customer says", "At a glance", "Six separate checks", "Money that could be held"]);
    const glance = screen.getByRole("region", { name: "At a glance" });
    expect(within(glance).getByText(/has moved to other banks/)).toBeInTheDocument();
    expect(within(glance).getByText(/Decide on the suggested hold below/)).toBeInTheDocument();
    expect(screen.getByText("none of them is a verdict")).toBeInTheDocument();
    // No jargon outside the "how this was worked out" disclosures (where it is kept, not deleted).
    const visible = document.body.cloneNode(true) as HTMLElement;
    visible.querySelectorAll("details > :not(summary)").forEach((n) => n.remove());
    expect(visible.textContent).not.toMatch(/lower bound|upper bound|deterministic|traceab|attribution|FIFO|pro-rata|POL-/i);
    expect(document.body.textContent).toMatch(/attribution upper bound/);
  });

  it("shows the six checks as collapsed rows that open on click, with the working-out behind a disclosure", async () => {
    renderTab(sample);
    const rows = within(screen.getByRole("list", { name: "Six separate checks" })).getAllByRole("button");
    expect(rows).toHaveLength(6);
    rows.forEach((r) => expect(r).toHaveAttribute("aria-expanded", "false"));
    const trace = screen.getByRole("button", { name: /Tracing the money/ });
    expect(trace).toHaveTextContent("All accounted for");
    expect(screen.queryByText("Show how this was worked out", { selector: "#dim-body-trace summary" })).toBeNull();
    await userEvent.click(trace);
    expect(trace).toHaveAttribute("aria-expanded", "true");
    const body = document.getElementById("dim-body-trace") as HTMLElement;
    expect(within(body).getByText("Show how this was worked out")).toBeInTheDocument();
    expect(within(body).getByText("Sent to other banks")).toBeInTheDocument();
  });

  it("states each hold in a sentence with approve / decline and keeps the method numbers in the disclosure", () => {
    renderTab({ ...sample, can_edit: true, holds: [hold] });
    const holds = screen.getByRole("region", { name: "Money that could be held" });
    expect(within(holds).getAllByText(/may still hold/)).toHaveLength(2);
    expect(within(holds).getByText("Suggested hold:", { exact: false })).toHaveTextContent("Suggested hold: ₹19,000.");
    expect(within(holds).getByRole("button", { name: "Approve hold on Sunil P's account" })).toBeInTheDocument();
    expect(within(holds).getByRole("button", { name: "Decline hold on Sunil P's account" })).toBeInTheDocument();
    expect(within(holds).getAllByText("Clean money out first").length).toBe(2);
    expect(within(holds).getAllByText("Show how this was worked out").length).toBe(2);
  });
});
