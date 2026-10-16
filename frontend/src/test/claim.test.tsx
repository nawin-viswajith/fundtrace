import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ClaimView } from "../features/report/ClaimView";
import type { Claim } from "../types/api";

const records = {
  "TXN-4001695": { type: "transaction", provenance: "confirmed (ledger record)", amount: "₹40,000", to_account: "ACC-100218" },
};

const good: Claim = {
  id: "C01",
  text: "The disputed transfer TXN-4001695 of ₹40,000 went to ACC-100218.",
  citations: ["TXN-4001695"],
  basis: "verified",
  issues: [],
  valid: true,
  verdict: "supported",
  verdict_reason: "matches record",
  hallucination: false,
  flagged: false,
};

const bad: Claim = {
  id: "C07",
  text: "₹45,000 moved to ACC-999999 and proves fraud.",
  citations: ["TXN-4001695", "ACC-999999"],
  basis: "verified",
  issues: [
    { code: "invalid_citation", detail: "cites ACC-999999, which is not in the evidence snapshot", severity: "error" },
    { code: "number_mismatch", detail: "amount ₹45,000 does not appear in the cited records", severity: "error" },
  ],
  valid: false,
  verdict: "contradicted",
  verdict_reason: "record says ₹40,000",
  hallucination: true,
  flagged: true,
};

function renderClaim(c: Claim, extra: Partial<Parameters<typeof ClaimView>[0]> = {}) {
  return render(
    <ol>
      <ClaimView claim={c} records={records} {...extra} />
    </ol>,
  );
}

describe("ClaimView", () => {
  it("renders a supported claim with basis, verdict and citation chips", () => {
    renderClaim(good);
    const li = screen.getByTestId("claim-C01");
    expect(li).not.toHaveClass("is-flagged");
    expect(within(li).getByText("Verified")).toBeInTheDocument();
    expect(within(li).getByText("Supported")).toBeInTheDocument();
    expect(within(li).getByRole("button", { name: /Citation TXN-4001695/ })).toBeInTheDocument();
    expect(within(li).queryByText("Possible hallucination")).toBeNull();
  });

  it("marks flagged hallucinated claims and lists the issues", () => {
    renderClaim(bad);
    const li = screen.getByTestId("claim-C07");
    expect(li).toHaveClass("is-flagged");
    expect(li).toHaveClass("is-hallucination");
    expect(within(li).getByText("Possible hallucination")).toBeInTheDocument();
    expect(within(li).getByText("Contradicted")).toBeInTheDocument();
    expect(within(li).getByText("invalid_citation")).toBeInTheDocument();
    expect(within(li).getByText("number_mismatch")).toBeInTheDocument();
    // A citation that is not in the snapshot is visibly marked.
    expect(within(li).getByRole("button", { name: /ACC-999999 \(not in snapshot\)/ })).toHaveClass("is-missing");
  });

  it("opens a popover with the cited record and a show-on-graph link", async () => {
    const user = userEvent.setup();
    const onGraph = vi.fn();
    renderClaim(good, { onShowOnGraph: onGraph });
    await user.click(screen.getByRole("button", { name: /Citation TXN-4001695/ }));
    const dialog = screen.getByRole("dialog", { name: "Record TXN-4001695" });
    expect(within(dialog).getByText("₹40,000")).toBeInTheDocument();
    expect(within(dialog).getByText("confirmed (ledger record)")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /Show on graph/ }));
    expect(onGraph).toHaveBeenCalledWith("TXN-4001695");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("explains a citation missing from the snapshot", async () => {
    const user = userEvent.setup();
    renderClaim(bad);
    await user.click(screen.getByRole("button", { name: /ACC-999999/ }));
    const dialog = screen.getByRole("dialog", { name: "Record ACC-999999" });
    expect(within(dialog).getByText(/is not in the evidence snapshot. A claim citing it/)).toBeInTheDocument();
  });

  it("supports accept/reject review toggles", async () => {
    const user = userEvent.setup();
    const onReview = vi.fn();
    renderClaim(good, { onReview, review: undefined });
    await user.click(screen.getByRole("button", { name: "Reject" }));
    expect(onReview).toHaveBeenCalledWith("reject");
  });
});
