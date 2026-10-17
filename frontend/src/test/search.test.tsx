import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import GlobalSearch from "../features/shell/GlobalSearch";
import type { SearchResponse } from "../types/api";

const RESULTS: SearchResponse = {
  query: "240",
  results: [
    {
      id: "CASE-24031",
      category_label: "Account takeover",
      status: "awaiting_evidence",
      priority: "P1",
      amount_label: "₹15,000",
      matched_on: "case",
      disputed_txn_id: "TXN-4001646",
    },
    {
      id: "CASE-24051",
      category_label: "Unauthorised transfer",
      status: "new",
      priority: "P1",
      amount_label: "₹50,000",
      matched_on: "transaction",
      disputed_txn_id: "TXN-4001679",
    },
  ],
};

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname}</p>;
}

function setup() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/overview"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <GlobalSearch />
        <button type="button">elsewhere</button>
        <Routes>
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return screen.getByRole("combobox", { name: "Search cases" });
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn(async (url: string) => {
    const q = new URL(url, "http://x").searchParams.get("q") ?? "";
    const body: SearchResponse = { query: q, results: q === "240" ? RESULTS.results : [] };
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("global case search", () => {
  it("does not search below two characters", async () => {
    const input = setup();
    await userEvent.type(input, "2");
    expect(await screen.findByText("Type at least 2 characters")).toBeInTheDocument();
    await act(() => new Promise((r) => setTimeout(r, 350)));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("debounces, lists results and opens the highlighted case with the keyboard", async () => {
    const input = setup();
    expect(input).toHaveAttribute("placeholder", "Search case, transaction, UTR, account…");
    await userEvent.type(input, "240");
    const options = await screen.findAllByRole("option");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/search?q=240");
    expect(options).toHaveLength(2);
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Matched on transaction TXN-4001679")).toBeInTheDocument();

    await userEvent.keyboard("{ArrowDown}");
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveAttribute("aria-activedescendant", options[0].id);
    await userEvent.keyboard("{ArrowDown}");
    expect(options[1]).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{ArrowDown}");
    expect(options[0]).toHaveAttribute("aria-selected", "true"); // wraps
    await userEvent.keyboard("{ArrowUp}");
    expect(options[1]).toHaveAttribute("aria-selected", "true");

    await userEvent.keyboard("{Enter}");
    expect(screen.getByTestId("where")).toHaveTextContent("/cases/CASE-24051");
    expect(screen.queryByRole("option")).toBeNull();
  });

  it("closes on Escape and says when nothing matches", async () => {
    const input = setup();
    await userEvent.type(input, "zz");
    expect(await screen.findByText("No cases match “zz”")).toBeInTheDocument();
    await userEvent.clear(input);
    await userEvent.type(input, "240");
    await screen.findAllByRole("option");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("option")).toBeNull());
    expect(input).toHaveAttribute("aria-expanded", "false");
    expect(input).toHaveValue("240");
    await userEvent.keyboard("{Escape}");
    expect(input).toHaveValue("");
  });

  it("focuses from anywhere with '/'", async () => {
    const input = setup();
    screen.getByRole("button", { name: "elsewhere" }).focus();
    await userEvent.keyboard("/");
    await waitFor(() => expect(input).toHaveFocus());
    expect(input).toHaveValue("");
  });
});
