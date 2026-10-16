import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { columnOf, layoutGraph } from "../features/graph/layout";
import type { GraphEdge, GraphNode, GraphResponse } from "../types/api";

const sample = JSON.parse(
  readFileSync(resolve(__dirname, "../../../docs/api-samples/graph_CASE-24051_both.json"), "utf-8"),
) as GraphResponse;

function acc(id: string, depth: number, roles: string[]): GraphNode {
  return {
    id,
    type: "account",
    label: id,
    provenance: "confirmed",
    source_ids: [id],
    depth,
    roles,
    data: { masked_number: "XXXX0000", institution: "Bank", external: false, kind: "savings", opened_at: null, currency: "INR" },
  };
}
function txn(id: string, depth: number, from: string, to: string, time: string, direction: "root" | "forward" | "backward"): GraphNode {
  return {
    id,
    type: "transaction",
    label: id,
    provenance: "confirmed",
    source_ids: [id],
    depth,
    direction,
    time,
    roles: direction === "root" ? ["disputed"] : [],
    data: {
      amount_minor: 100,
      currency: "INR",
      status: "posted",
      channel: "UPI",
      reference: "1",
      reference_missing: false,
      occurred_at: time,
      posted_at: time,
      debit_account_id: from,
      credit_account_id: to,
      reversal_of_id: null,
      device_id: null,
      source_system: "core",
      source_record_id: id,
      narrative: "",
    },
  };
}
function edges(nodes: GraphNode[]): GraphEdge[] {
  return nodes.flatMap((n) =>
    n.type === "transaction"
      ? [
          { id: `s${n.id}`, source: n.data.debit_account_id, target: n.id, type: "sent", provenance: "confirmed", source_ids: [n.id], time: n.time, label: null, data: {} },
          { id: `r${n.id}`, source: n.id, target: n.data.credit_account_id, type: "received_by", provenance: "confirmed", source_ids: [n.id], time: n.time, label: null, data: {} },
        ]
      : [],
  );
}

describe("graph layout", () => {
  it("is deterministic", () => {
    const a = layoutGraph(sample.graph.nodes, sample.graph.edges, sample.graph.root_txn_id);
    const b = layoutGraph([...sample.graph.nodes].reverse(), [...sample.graph.edges].reverse(), sample.graph.root_txn_id);
    for (const [id, p] of a) expect(b.get(id)).toEqual(p);
  });

  it("places transactions between their accounts, left to right by depth", () => {
    const pos = layoutGraph(sample.graph.nodes, sample.graph.edges, sample.graph.root_txn_id);
    for (const n of sample.graph.nodes) {
      if (n.type !== "transaction") continue;
      const t = pos.get(n.id)!;
      expect(pos.get(n.data.debit_account_id)!.x).toBeLessThan(t.x);
      expect(pos.get(n.data.credit_account_id)!.x).toBeGreaterThan(t.x);
    }
    const payer = pos.get("ACC-100216")!;
    const ben = pos.get("ACC-100209")!;
    expect(payer.x).toBeLessThan(ben.x);
  });

  it("orders a column by time and centres it", () => {
    const pos = layoutGraph(sample.graph.nodes, sample.graph.edges, sample.graph.root_txn_id);
    const t30 = pos.get("TXN-4001680")!; // 17:51
    const t20 = pos.get("TXN-4001681")!; // 17:57
    expect(t30.column).toBe(t20.column);
    expect(t30.y).toBeLessThan(t20.y);
    expect(t30.y + t20.y).toBe(0);
  });

  it("puts evidence above the disputed transaction", () => {
    const pos = layoutGraph(sample.graph.nodes, sample.graph.edges, sample.graph.root_txn_id);
    const ev = pos.get("EV-CD9D4D5A")!;
    const root = pos.get(sample.graph.root_txn_id)!;
    expect(ev.x).toBe(root.x);
    const minOther = Math.min(...[...pos.values()].filter((p) => p.id !== "EV-CD9D4D5A").map((p) => p.y));
    expect(ev.y).toBeLessThan(minOther);
  });

  it("places upstream accounts left of the payer and root", () => {
    const nodes = [
      acc("UP2", -2, ["upstream"]),
      acc("UP1", -1, ["upstream"]),
      acc("PAYER", 0, ["payer"]),
      acc("BEN", 1, ["beneficiary"]),
      txn("T-2", -2, "UP2", "UP1", "2026-10-16T10:00:00Z", "backward"),
      txn("T-1", -1, "UP1", "PAYER", "2026-10-16T11:00:00Z", "backward"),
      txn("ROOT", 0, "PAYER", "BEN", "2026-10-16T12:00:00Z", "root"),
    ];
    const pos = layoutGraph(nodes, edges(nodes), "ROOT");
    const x = (id: string) => pos.get(id)!.x;
    expect(x("UP2")).toBeLessThan(x("T-2"));
    expect(x("T-2")).toBeLessThan(x("UP1"));
    expect(x("UP1")).toBeLessThan(x("T-1"));
    expect(x("T-1")).toBeLessThan(x("PAYER"));
    expect(x("PAYER")).toBeLessThan(x("ROOT"));
    expect(x("ROOT")).toBeLessThan(x("BEN"));
    expect(columnOf(nodes[0])).toBe(-4);
  });
});
