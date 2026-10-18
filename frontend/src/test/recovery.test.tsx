import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { RecoveryPools } from "../features/recovery/RecoveryPools";
import { recoveryApi, type RecoveryPool } from "../features/recovery/api";

const claim = (case_id: string, disputed: number, eligible: number, allocated: number, hold = eligible) => ({
  case_id,
  restricted: case_id === "restricted",
  status: "new",
  status_label: "New",
  disputed_txn_id: case_id === "restricted" ? null : `TXN-${case_id}`,
  disputed_amount_minor: disputed,
  traced_min_minor: 0,
  traced_max_minor: eligible,
  by_method: null,
  traced_as_of: "2026-10-18T10:00:00Z",
  eligible_minor: eligible,
  allocated_minor: allocated,
  share: null,
  hold_id: null,
  hold_status: "recommended",
  hold_suggested_minor: hold,
});

const base: RecoveryPool = {
  account_id: "ACC-100209",
  label: "Rahul K (synthetic)",
  currency: "INR",
  method: "pro-rata-v1",
  basis: "traced",
  basis_description: "Each claim is the most of that case's money that may still be in this account.",
  bases: { traced: "Each claim is the most of that case's money that may still be in this account.", disputed: "Each claim is the full amount disputed." },
  available_minor: 120000,
  available_source: { case_id: "CASE-24051", window_end: "2026-10-21T10:00:00Z", as_of: "2026-10-18T10:00:00Z", description: "Balance on record." },
  total_eligible_minor: 360000,
  distributable_minor: 120000,
  left_over_minor: 0,
  claims: [claim("CASE-24038", 2200000, 120000, 40000), claim("CASE-24051", 5000000, 120000, 40000), claim("restricted", 1500000, 120000, 40000)],
  double_counting: { hold_total_minor: 360000, available_minor: 120000, exceeds: true, excess_minor: 240000, warning: "same money" },
  formula: "allocation = (eligible claim / total eligible claims) x money available",
  formula_plain: "Each case gets the same share of the money in the account as its claim is of all the claims together.",
  assumptions: ["All claims are treated as equal priority: no case is paid ahead of another."],
  warnings: [],
  input_ids: ["ACC-100209", "CASE-24038", "CASE-24051"],
  is_estimate: true,
  caveat: "",
  computed_at: "2026-10-18T10:00:00Z",
  last_recorded: null,
};

const disputed: RecoveryPool = {
  ...base,
  basis: "disputed",
  total_eligible_minor: 8700000,
  claims: [claim("CASE-24038", 2200000, 2200000, 30345), claim("CASE-24051", 5000000, 5000000, 68965), claim("restricted", 1500000, 1500000, 20690)],
};

function renderPools(canRecord: boolean) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <RecoveryPools canRecord={canRecord} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("money recovered from shared accounts", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the money in the account once, each case's share, the double-counting warning and the assumptions", async () => {
    vi.spyOn(recoveryApi, "pools").mockResolvedValue({ pools: [base], cases_scanned: 9, method: "pro-rata-v1", note: "" });
    renderPools(false);
    expect(await screen.findByRole("heading", { name: "Money recovered from shared accounts" })).toBeInTheDocument();
    expect(await screen.findByText("Rahul K's account")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /Rahul K's money would be split/ });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(5); // header, three cases, total
    expect(within(table).getByRole("link", { name: "CASE-24051" })).toHaveAttribute("href", "/cases/CASE-24051");
    expect(within(table).getByText("restricted")).toBeInTheDocument();
    expect(within(rows[4]).getAllByText("₹1,200")).toHaveLength(1); // shares add up to the money in the account
    expect(screen.getByText(/The same money is being counted more than once/)).toBeInTheDocument();
    expect(screen.getByText(/no case is paid ahead of another/)).toBeInTheDocument();
    expect(screen.getByText(/as its claim is of all the claims together/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record this split" })).toBeNull(); // investigators cannot record
  });

  it("switches the claim basis by asking the server for that split", async () => {
    vi.spyOn(recoveryApi, "pools").mockResolvedValue({ pools: [base], cases_scanned: 9, method: "pro-rata-v1", note: "" });
    const one = vi.spyOn(recoveryApi, "pool").mockResolvedValue(disputed);
    renderPools(false);
    await userEvent.click(await screen.findByRole("radio", { name: "Full amount disputed" }));
    expect(one).toHaveBeenCalledWith("ACC-100209", "disputed");
    expect(await screen.findByText("₹303.45")).toBeInTheDocument();
    expect(screen.getByText("₹87,000")).toBeInTheDocument();
  });

  it("lets a supervisor record the split with a reason of at least 10 characters, and says no money moves", async () => {
    vi.spyOn(recoveryApi, "pools").mockResolvedValue({ pools: [base], cases_scanned: 9, method: "pro-rata-v1", note: "" });
    const rec = vi.spyOn(recoveryApi, "record").mockResolvedValue({
      record: {
        id: 1, account_id: "ACC-100209", method: "pro-rata-v1", basis: "traced", currency: "INR", available_minor: 120000,
        allocations: [], note: "Agreed at review", recorded_by: "sup.meera", recorded_at: "2026-10-18T10:00:00Z",
        effect: "Recorded for the file only. No money was moved, held or released.",
      },
      pool: base,
    });
    renderPools(true);
    const u = userEvent.setup();
    await u.click(await screen.findByRole("button", { name: "Record this split" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/does not move, hold or release any money/)).toBeInTheDocument();
    const submit = within(dialog).getByRole("button", { name: "Record this split" });
    await u.type(within(dialog).getByLabelText("Reason (at least 10 characters)"), "too short");
    expect(submit).toBeDisabled();
    await u.type(within(dialog).getByLabelText("Reason (at least 10 characters)"), " still");
    expect(submit).toBeEnabled();
    await u.click(submit);
    expect(rec).toHaveBeenCalledWith("ACC-100209", { basis: "traced", note: "too short still" });
  });

  it("says so plainly when no account is shared", async () => {
    vi.spyOn(recoveryApi, "pools").mockResolvedValue({ pools: [], cases_scanned: 9, method: "pro-rata-v1", note: "" });
    renderPools(true);
    expect(await screen.findByText("No shared accounts")).toBeInTheDocument();
  });
});
