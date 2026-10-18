import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

const v2 = JSON.parse(readFileSync(resolve(__dirname, "../../../docs/api-samples/cases_v2.json"), "utf-8")) as CaseListResponse;

describe("case queue: age, next action and pagination", () => {
  it("links the next action to the right workspace tab and shows a dash once resolved", () => {
    renderBody({ cases: v2.cases });
    const row = screen.getByRole("link", { name: "CASE-24051" }).closest("tr") as HTMLElement;
    expect(within(row).getByRole("link", { name: /Check the money trail and take the case/ })).toHaveAttribute(
      "href",
      "/cases/CASE-24051?tab=graph",
    );
    expect(within(row).getByText("1 h")).toBeInTheDocument();
    const resolved = screen.getByRole("link", { name: "CASE-24033" }).closest("tr") as HTMLElement;
    expect(within(resolved).queryByRole("link", { name: /tab=|Review|Record|Run|Triage/ })).toBeNull();
    expect(within(resolved).getByText("—")).toBeInTheDocument();
  });

  it("pages 15 rows at a time with Prev/Next and a range label", async () => {
    const many = Array.from({ length: 22 }, (_, i) => ({ ...v2.cases[i % v2.cases.length], id: `CASE-9${String(i).padStart(4, "0")}` }));
    renderBody({ cases: many });
    expect(screen.getByText("1–15 of 22")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(16); // header + 15
    const prev = screen.getByRole("button", { name: /Prev/ });
    const next = screen.getByRole("button", { name: /Next/ });
    expect(prev).toBeDisabled();
    await userEvent.click(next);
    expect(screen.getByText("16–22 of 22")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(8);
    expect(screen.getByRole("link", { name: "CASE-90015" })).toBeInTheDocument();
    expect(next).toBeDisabled();
    await userEvent.click(prev);
    expect(screen.getByText("1–15 of 22")).toBeInTheDocument();
  });
});
