import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { GenerateDataDialog } from "../features/queue/GenerateDataDialog";
import { api } from "../api/endpoints";
import type { Meta } from "../types/api";

const meta = {
  statuses: [],
  status_labels: {},
  categories: { app_scam: "Authorised push-payment scam", merchant_dispute: "Merchant dispute" },
  decisions: {},
  graph_relations: [],
  assignees: [{ id: 1, username: "inv.asha", full_name: "Asha Raman", role: "investigator" }],
  limits: { max_depth: 5, max_window_hours: 720, max_nodes: 300 },
} as unknown as Meta;

function renderDialog() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <GenerateDataDialog onClose={() => undefined} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("generate demo disputes", () => {
  afterEach(() => vi.restoreAllMocks());

  it("asks for count, types, amounts, status and AI budget, then lists what was created", async () => {
    vi.spyOn(api, "meta").mockResolvedValue(meta);
    const gen = vi.spyOn(api, "generateData").mockResolvedValue({
      created: [{ case_id: "CASE-24100", category: "Merchant dispute", status: "new", priority: "P3", amount: "₹12,000" }],
      statements: { ai: 0, ai_rejected: 0, template: 1, ai_cost_usd: 0, ai_available: false },
    });
    renderDialog();
    const u = userEvent.setup();
    await u.click(await screen.findByRole("checkbox", { name: "Authorised push-payment scam" })); // leave only merchant disputes
    const lowest = screen.getByLabelText("Lowest payment (₹)");
    await u.clear(lowest);
    await u.type(lowest, "200000");
    expect(screen.getByText("The lowest amount must not be above the highest.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Generate 5 cases/ })).toBeDisabled();
    await u.clear(lowest);
    await u.type(lowest, "8000");
    await u.selectOptions(screen.getByLabelText("Status of the new cases"), "new");
    await u.click(screen.getByRole("radio", { name: /AI write varied statements/ }));
    expect(screen.getByLabelText("AI budget (US$, up to 2.00)")).toHaveValue(0.1);
    await u.click(screen.getByRole("button", { name: /Generate 5 cases/ }));
    expect(gen).toHaveBeenCalledWith(
      expect.objectContaining({ categories: ["merchant_dispute"], amount_min: 8000, status_mode: "new", statements: "ai", ai_budget_usd: 0.1 }),
    );
    expect(await screen.findByRole("link", { name: "CASE-24100" })).toHaveAttribute("href", "/cases/CASE-24100");
  });
});
