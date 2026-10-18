import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { leadSentence, plainRange, spanOf, summariseBuckets } from "../features/graph/moneySummary";
import { plainTitle } from "../features/timeline/plainTitle";
import type { Attribution, GraphResponse } from "../types/api";

const sample = JSON.parse(
  readFileSync(resolve(__dirname, "../../../docs/api-samples/graph_CASE-24051_both.json"), "utf-8"),
) as GraphResponse;

describe("plain money summary", () => {
  it("uses the smallest and largest of the four methods, whichever method gives them", () => {
    // For money still in an account, "clean money spent first" (min) is the HIGHEST value.
    expect(spanOf({ min: 120000, fifo: 120000, pro_rata: 117187, max: 0 })).toEqual({ min: 0, max: 120000 });
    expect(spanOf({ min: 1900000, fifo: 1824000, pro_rata: 1795615, max: 1800000 })).toEqual({ min: 1795615, max: 1900000 });
  });

  it("writes ranges as at least / up to / a single figure", () => {
    expect(plainRange({ min: 1380000, max: 1500000 }, "INR")).toBe("₹13,800–₹15,000");
    expect(plainRange({ min: 0, max: 120000 }, "INR", { capital: true })).toBe("Up to ₹1,200");
    expect(plainRange({ min: 500000, max: 500000 }, "INR")).toBe("₹5,000");
  });

  it("leads with where the money is, largest first, and skips empty destinations", () => {
    const att = sample.attribution;
    const parts = summariseBuckets(att);
    expect(parts.map((p) => p.key)).toEqual(["left_visibility", "residual_in_visible_accounts"]);
    expect(leadSentence(att)).toBe(
      "₹29,800–₹32,000 has moved to other banks. ₹18,000–₹20,200 may still be in accounts at this bank and could be held.",
    );
  });

  it("says plainly when the figures can't be worked out", () => {
    const att = { ...sample.attribution, evaluable: false } as Attribution;
    expect(leadSentence(att)).toMatch(/could not work out where the money went/);
  });
});

describe("plain timeline titles", () => {
  it("swaps account ids for names and sign-in codes for words", () => {
    const names = new Map([
      ["ACC-100216", "Priya N"],
      ["ACC-100209", "Rahul K"],
    ]);
    expect(plainTitle({ kind: "transaction", title: "₹50,000 UPI ACC-100216 → ACC-100209" }, names)).toBe("₹50,000 UPI Priya N → Rahul K");
    expect(plainTitle({ kind: "transaction", title: "₹1 UPI ACC-999 → ACC-100209" }, names)).toBe("₹1 UPI ACC-999 → Rahul K");
    expect(plainTitle({ kind: "auth_event", title: "login failure" }, names)).toBe("Failed sign-in attempt");
  });
});

describe("plain evidence wording", () => {
  it("names checks and details in bank language, keeping unknown text as is", async () => {
    const { plainCheckName, plainDetail, matchLabel } = await import("../features/evidence/plainEvidence");
    const ev = [{ id: "EV-1", filename: "receipt.png" }];
    expect(plainCheckName("Allegation amount vs ledger", ev)).toBe("Amount in the customer's statement vs the bank's record");
    expect(plainCheckName("Evidence EV-1 vs ledger", ev)).toBe("“receipt.png” vs the bank's record");
    expect(plainCheckName("EV-1 reference", ev)).toBe("“receipt.png”: Payment reference (UTR) vs the bank's record");
    expect(plainCheckName("Something new", ev)).toBe("Something new");
    expect(plainDetail("Statement mentions ₹50,000; ledger has ₹50,000.")).toBe("Statement mentions ₹50,000; the bank's record has ₹50,000.");
    expect(plainDetail("2 source records agree (core:cbs-1, upi_switch:sw-2).")).toBe("2 source records agree.");
    expect(matchLabel("contradicts")).toBe("Does not match");
  });
});
