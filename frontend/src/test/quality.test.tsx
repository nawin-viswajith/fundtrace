import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import QualityPanels, { sortByDeclinedShare } from "../features/ops/QualityPanels";
import { qualityApi, type QualityResponse, type RuleBurdenRow } from "../features/ops/qualityApi";
import { NOT_ENOUGH_DATA } from "../lib/outcomes";

const rule = (rule_id: string, name: string, triggered: number, upheld: number, declined: number, share: number | null, not_evaluable = 0): RuleBurdenRow => ({
  rule_id,
  name,
  severity: "high",
  evaluated: 10,
  triggered,
  upheld,
  declined,
  not_evaluable,
  declined_share: share,
  status: share === null ? "not_enough_data" : "ok",
  n: triggered,
  min: 5,
});

const caveats = ["A declined claim does not prove the warning sign was wrong.", "Referred cases are not counted."];

function sample(over: Partial<QualityResponse["reviewer_agreement"]> = {}): QualityResponse {
  return {
    generated_at: "2026-10-18T10:00:00Z",
    reviewer_agreement: {
      status: "ok",
      n: 12,
      min: 10,
      claims_compared: 12,
      agreed: 9,
      agreement_rate: 0.75,
      kappa: 0.4706,
      kappa_label: "moderate",
      kappa_undefined_reason: null,
      table: { accept: { supported: 6, not_supported: 1 }, reject: { supported: 2, not_supported: 3 } },
      excluded: { unjudged: 2, system_generated: 1, other: 0, missing: 0 },
      claims_not_marked: 1,
      reports: 2,
      per_report: [
        { report_id: "RPT-A", case_id: "CASE-24051", version: 2, review_status: "partial", compared: 7, agreed: 5, excluded: 2, agreement: 0.7143, reviewed_at: null },
        { report_id: "RPT-B", case_id: "CASE-24033", version: 1, review_status: "accepted", compared: 2, agreed: 2, excluded: 0, agreement: null, reviewed_at: null },
      ],
      min_claims: 10,
      min_report_claims: 3,
      note: "Compares each claim an investigator marked accept or reject with the AI fact-check verdict.",
      kappa_note: "Kappa is agreement beyond chance: 0 means no better than chance, 1 means perfect agreement.",
      does_not_mean: "Agreement does not show who is right.",
      ...over,
    },
    rule_burden: {
      rules: [
        rule("R3", "Beneficiary linked to other disputes", 2, 1, 1, null, 4),
        rule("R1", "Rapid onward movement", 6, 2, 4, 0.6667),
        rule("R2", "Split into multiple transfers", 5, 4, 1, 0.2),
      ],
      review_burden: { value: 1.75, median: 1.5, status: "ok", n: 4, min: 1, unit: "signals", note: "Warning signs found per open case (average)." },
      decided_cases: 7,
      decided_cases_total: 7,
      open_cases: 4,
      open_cases_total: 4,
      max_cases: 200,
      sources: { decided: { stored: 6, evaluated_now: 1, failed: 0 }, open: { stored: 0, evaluated_now: 4, failed: 0 } },
      source_note: "Each case uses its latest saved rule check when there is one.",
      synthetic_cases: 7,
      generator_decisions: 1,
      min_cases_per_rule: 5,
      demo_note: "7 of 7 decided case(s) are synthetic demo data, so these are demo figures and not the bank's real rule performance.",
      caveats,
    },
  };
}

function renderPanels() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <QualityPanels />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("reviewer agreement panel", () => {
  it("shows the rate, the 2x2 table, kappa explained and per-report rows", async () => {
    vi.spyOn(qualityApi, "get").mockResolvedValue(sample());
    renderPanels();
    const panel = await screen.findByRole("region", { name: "Do investigators agree with the AI fact-check?" });
    const rate = within(panel).getByRole("group", { name: "Agreement" });
    expect(rate).toHaveTextContent("75%");
    expect(rate).toHaveTextContent("9 of 12 claims");
    const kappa = within(panel).getByRole("group", { name: "Agreement beyond chance (kappa)" });
    expect(kappa).toHaveTextContent("0.47");
    expect(kappa).toHaveTextContent("Moderate");
    expect(within(panel).getByText(/agreement beyond chance: 0 means no better than chance/)).toBeInTheDocument();

    const matrix = within(panel).getByRole("table", { name: "Investigator review against AI fact-check" });
    const accepted = within(matrix).getByRole("row", { name: /Investigator accepted/ });
    expect(within(accepted).getAllByRole("cell").map((c) => c.textContent)).toEqual(["6", "1"]);
    const rejected = within(matrix).getByRole("row", { name: /Investigator rejected/ });
    expect(within(rejected).getAllByRole("cell").map((c) => c.textContent)).toEqual(["2", "3"]);

    const perReport = within(panel).getByRole("table", { name: "Agreement per report" });
    const a = within(perReport).getByRole("row", { name: /CASE-24051/ });
    expect(a).toHaveTextContent("v2");
    expect(a).toHaveTextContent("5 of 7");
    expect(a).toHaveTextContent("71%");
    expect(within(perReport).getByRole("link", { name: "CASE-24051" })).toHaveAttribute("href", "/cases/CASE-24051?tab=report");
    // too few claims in one report: counts, no percentage
    const b = within(perReport).getByRole("row", { name: /CASE-24033/ });
    expect(b).toHaveTextContent("Too few claims");
    expect(b).not.toHaveTextContent("100%");
  });

  it("says 'Not enough data yet' instead of a number for a small sample", async () => {
    vi.spyOn(qualityApi, "get").mockResolvedValue(
      sample({ status: "not_enough_data", n: 4, claims_compared: 4, agreed: 4, agreement_rate: null, kappa: null, kappa_label: null }),
    );
    renderPanels();
    const panel = await screen.findByRole("region", { name: "Do investigators agree with the AI fact-check?" });
    const rate = within(panel).getByRole("group", { name: "Agreement" });
    expect(rate).toHaveTextContent(NOT_ENOUGH_DATA);
    expect(rate).toHaveTextContent("4 claims compared, needs at least 10");
    expect(rate).not.toHaveTextContent("%");
    expect(within(panel).getByRole("group", { name: "Agreement beyond chance (kappa)" })).toHaveTextContent(NOT_ENOUGH_DATA);
  });

  it("shows an empty state before any report has been reviewed", async () => {
    vi.spyOn(qualityApi, "get").mockResolvedValue(sample({ reports: 0, per_report: [], claims_compared: 0, status: "not_enough_data", n: 0 }));
    renderPanels();
    expect(await screen.findByText("No reviewed reports yet")).toBeInTheDocument();
  });
});

describe("warning-sign burden panel", () => {
  it("lists every rule sorted by declined share, with upheld / declined counts and caveats", async () => {
    vi.spyOn(qualityApi, "get").mockResolvedValue(sample());
    renderPanels();
    const panel = await screen.findByRole("region", { name: "Warning signs: how often do they matter?" });
    expect(within(panel).getByText(/Demo figures\./)).toBeInTheDocument();
    expect(within(panel).getByText(/not the bank's real rule performance/)).toBeInTheDocument();
    expect(within(panel).getByRole("group", { name: "Warning signs per open case" })).toHaveTextContent("1.8");

    const table = within(panel).getByRole("table", { name: "Warning signs in decided cases" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByText(/^R\d+$/).textContent)).toEqual(["R1", "R2", "R3"]);
    const cells = within(rows[0]).getAllByRole("cell").map((c) => c.textContent);
    expect(cells[2]).toBe("2");
    expect(cells[3]).toBe("4");
    expect(cells[4]).toContain("67%");
    expect(within(rows[0]).getByRole("meter", { name: "Rapid onward movement: 67% declined" })).toBeInTheDocument();
    expect(within(rows[2]).getByText(NOT_ENOUGH_DATA)).toBeInTheDocument();
    expect(within(rows[2]).getAllByRole("cell").at(-1)?.textContent).toBe("4");

    for (const c of caveats) expect(within(panel).getByText(c)).toBeInTheDocument();
    expect(within(panel).getByText(/6 from a saved check, 1 checked now/)).toBeInTheDocument();
  });

  it("sorts rules without enough data after rules with a share", () => {
    const sorted = sortByDeclinedShare([rule("R9", "x", 1, 0, 1, null), rule("R2", "y", 8, 6, 2, 0.25), rule("R4", "z", 6, 1, 5, 0.8333), rule("R10", "w", 3, 1, 2, null)]);
    expect(sorted.map((r) => r.rule_id)).toEqual(["R4", "R2", "R10", "R9"]);
  });
});
