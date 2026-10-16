import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueueBody } from "../features/queue/CaseQueue";
import { ThemeProvider } from "../lib/theme";
import type { CaseListResponse } from "../types/api";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const sample = JSON.parse(readFileSync(resolve(__dirname, "../../../docs/api-samples/cases.json"), "utf-8")) as CaseListResponse;

function renderBody(props: Partial<Parameters<typeof QueueBody>[0]>) {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <QueueBody loading={false} error={null} retry={vi.fn()} cases={[]} labels={sample.status_labels} filtersActive={false} {...props} />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("case queue", () => {
  it("shows an empty state when there are no cases", () => {
    renderBody({ cases: [] });
    expect(screen.getByText("No cases in your queue")).toBeInTheDocument();
  });

  it("suggests clearing filters when filters hide everything", () => {
    renderBody({ cases: [], filtersActive: true });
    expect(screen.getByText("No cases match these filters")).toBeInTheDocument();
  });

  it("shows an error with retry", () => {
    const retry = vi.fn();
    renderBody({ error: new Error("boom"), retry });
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
    screen.getByRole("button", { name: /Retry/ }).click();
    expect(retry).toHaveBeenCalled();
  });

  it("renders rows from the real sample with INR amounts and priority", () => {
    renderBody({ cases: sample.cases });
    expect(screen.getByRole("link", { name: "CASE-24051" })).toHaveAttribute("href", "/cases/CASE-24051");
    expect(screen.getAllByText("₹50,000").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: /Priority P1/ }).length).toBeGreaterThan(0);
  });
});
