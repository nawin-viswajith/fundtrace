import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { caseActionHref, formatAge, formatDurationHours, formatMeasurement, measurementBasis, NOT_ENOUGH_DATA } from "../lib/outcomes";
import { MeasurementCard, OutcomesSection } from "../features/overview/OverviewPage";
import { ThemeProvider } from "../lib/theme";
import type { Measurement, OutcomesResponse } from "../types/api";

const sample = JSON.parse(readFileSync(resolve(__dirname, "../../../docs/api-samples/outcomes.json"), "utf-8")) as OutcomesResponse;

const ok = (value: number, unit: Measurement["unit"]): Measurement => ({ value, n: 3, unit, note: "", status: "ok" });

describe("outcome measurement formatting", () => {
  it("formats hours below 48 h in hours and from 48 h in days", () => {
    expect(formatMeasurement(ok(36, "hours"))).toBe("36 h");
    expect(formatMeasurement(ok(5.5, "hours"))).toBe("5.5 h");
    expect(formatMeasurement(ok(144.01, "hours"))).toBe("6.0 d");
    expect(formatDurationHours(48)).toBe("2.0 d");
  });

  it("formats ratios as percentages, counts as integers and actions as numbers", () => {
    expect(formatMeasurement(ok(0.9286, "ratio"))).toBe("93%");
    expect(formatMeasurement(ok(1, "ratio"))).toBe("100%");
    expect(formatMeasurement(ok(0, "count"))).toBe("0");
    expect(formatMeasurement(ok(4, "actions"))).toBe("4");
    expect(formatMeasurement(ok(4.5, "actions"))).toBe("4.5");
  });

  it("never produces a number when there is not enough data", () => {
    const m: Measurement = { value: null, n: 0, unit: "hours", note: "x", status: "not_enough_data" };
    expect(formatMeasurement(m)).toBeNull();
    // Even a malformed payload with a value but a non-ok status is not shown as a number.
    const odd = { value: 12, n: 0, unit: "hours", note: "", status: "not_enough_data" } as unknown as Measurement;
    expect(formatMeasurement(odd)).toBeNull();
  });

  it("describes what n counts", () => {
    expect(measurementBasis("median_investigation_hours", 1)).toBe("based on 1 decided case");
    expect(measurementBasis("findings_linked_to_sources", 14)).toBe("based on 14 report claims");
  });

  it("formats case age and next-action links", () => {
    expect(formatAge(0.4)).toBe("24 min");
    expect(formatAge(5.2)).toBe("5 h");
    expect(formatAge(70)).toBe("2 d");
    expect(formatAge(null)).toBe("—");
    expect(caseActionHref({ id: "CASE-1", next_action: { tab: "graph" } })).toBe("/cases/CASE-1?tab=graph");
    expect(caseActionHref({ id: "CASE-1", next_action: null })).toBe("/cases/CASE-1");
  });
});

describe("measurement cards", () => {
  it("shows 'Not enough data yet' and no digits for not_enough_data", () => {
    render(<MeasurementCard mkey="median_hours_to_escalation" m={sample.measurements.median_hours_to_escalation} />);
    const card = screen.getByRole("article", { name: "Median time to escalation" });
    expect(within(card).getByText(NOT_ENOUGH_DATA)).toBeInTheDocument();
    const value = card.querySelector(".ov-measure-value");
    expect(value?.textContent).not.toMatch(/\d/);
    expect(within(card).getByText("based on 0 escalated cases")).toBeInTheDocument();
  });

  it("renders the real sample with values, n, notes, safeguards and the no-baseline footnote", () => {
    render(
      <ThemeProvider>
        <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <OutcomesSection outcomes={sample} />
        </MemoryRouter>
      </ThemeProvider>,
    );
    const inv = screen.getByRole("article", { name: "Median investigation time" });
    expect(within(inv).getByText("6.0 d")).toBeInTheDocument();
    expect(within(inv).getByText("based on 1 decided case")).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Findings linked to sources" })).toHaveTextContent("93%");
    expect(screen.getByText("Safeguards (target 0)")).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Automated claim rejections" })).toHaveTextContent("On target");
    expect(screen.getByText(/improvement percentages are not claimed/)).toBeInTheDocument();
  });
});
