import { describe, expect, it } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { OPEN_SECTION_EVENT, ReportView } from "../features/report/ReportView";
import type { Report } from "../types/api";

const report = JSON.parse(readFileSync(resolve(__dirname, "../../../docs/api-samples/report_ai_CASE-24044.json"), "utf-8")) as Report;

function renderReport() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <ReportView report={report} caseId={report.case_id} canEdit />
    </QueryClientProvider>,
  );
}

describe("AI report sections accordion", () => {
  it("starts with every section collapsed, each row summarising its statements", () => {
    renderReport();
    const list = screen.getByRole("list", { name: "Report sections" });
    const heads = within(list).getAllByRole("button", { expanded: false });
    expect(heads.length).toBe(report.sections.length);
    expect(within(list).queryAllByRole("button", { expanded: true })).toHaveLength(0);
    expect(document.querySelectorAll(".claim-list li").length).toBe(0); // no statements shown until opened
    const first = report.sections.find((s) => s.claims.length > 0)!;
    expect(screen.getByRole("button", { name: new RegExp(first.title) })).toHaveTextContent(`${first.claims.length} statement`);
  });

  it("opens a section on click, and on request from the case assistant", async () => {
    renderReport();
    const sec = report.sections.find((s) => s.claims.length > 0)!;
    await userEvent.click(screen.getByRole("button", { name: new RegExp(sec.title) }));
    expect(screen.getByRole("button", { name: new RegExp(sec.title) })).toHaveAttribute("aria-expanded", "true");
    expect(document.querySelectorAll(".claim-list li").length).toBe(sec.claims.length);

    const other = report.sections.filter((s) => s.claims.length > 0)[1];
    act(() => {
      window.dispatchEvent(new CustomEvent(OPEN_SECTION_EVENT, { detail: other.key }));
    });
    expect(screen.getByRole("button", { name: new RegExp(other.title) })).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(screen.getByRole("button", { name: "Open all" }));
    expect(screen.getAllByRole("button", { expanded: true }).length).toBeGreaterThanOrEqual(report.sections.length);
  });
});
