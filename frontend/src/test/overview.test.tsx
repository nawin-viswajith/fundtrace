import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { OverviewBody } from "../features/overview/OverviewPage";
import { ThemeProvider } from "../lib/theme";
import type { Measurement, OverviewResponse } from "../types/api";

const sample = JSON.parse(readFileSync(resolve(__dirname, "../../../docs/api-samples/overview.json"), "utf-8")) as OverviewResponse;

function renderBody(data: OverviewResponse) {
  return render(
    <ThemeProvider>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <OverviewBody data={data} />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("overview", () => {
  it("renders KPIs, focus cases with next actions and recent activity from the real sample", () => {
    renderBody(sample);
    expect(screen.getByText("₹3,07,499")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "4 P1 cases" })).toHaveAttribute("href", "/cases?priority=P1");
    const attention = screen.getByRole("region", { name: "Needs attention" });
    const triage = within(attention).getByRole("link", { name: /Triage: check the trail and claim the case/ });
    expect(triage).toHaveAttribute("href", "/cases/CASE-24051?tab=graph");
    expect(within(attention).getByRole("link", { name: /Record the decision/ })).toHaveAttribute("href", "/cases/CASE-24042?tab=audit");
    expect(screen.getAllByText(/recorded a decision/).length).toBeGreaterThan(0);
  });

  it("shows friendly empty states when nothing needs attention", () => {
    const notEnough: Measurement = { value: null, n: 0, unit: "hours", note: "n/a", status: "not_enough_data" };
    const measurements = Object.fromEntries(
      Object.keys(sample.outcomes.measurements).map((k) => [k, notEnough]),
    ) as OverviewResponse["outcomes"]["measurements"];
    const empty: OverviewResponse = {
      ...sample,
      counts: { ...sample.counts, open: 0, golden_hour: 0, by_priority: { P1: 0, P2: 0, P3: 0, P4: 0 } },
      focus: [],
      golden_hour: [],
      at_risk: [],
      recent_activity: [],
      outcomes: { ...sample.outcomes, measurements },
    };
    renderBody(empty);
    expect(screen.getByText("Nothing needs attention")).toBeInTheDocument();
    expect(screen.getByText("No holds waiting for approval")).toBeInTheDocument();
    expect(screen.getByText(/recommends a hold/)).toBeInTheDocument();
    expect(screen.getByText("No activity recorded yet")).toBeInTheDocument();
    expect(screen.getAllByText("Not enough data yet")).toHaveLength(Object.keys(measurements).length);
  });
});
