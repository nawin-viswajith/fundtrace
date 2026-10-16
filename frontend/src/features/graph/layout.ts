/* Deterministic, time-layered left-to-right layout for the trail graph.

   Columns come from the trace depth:
     account at depth d       -> column 2d      (payer = 0, upstream negative, downstream positive)
     transaction at depth d   -> column 2d + 1  (sits between its debit and credit accounts:
                                                 forward txn d links account d -> d+1,
                                                 backward txn -d links account -d -> -(d-1))
     evidence                 -> column of the disputed transaction, stacked above it
   Within a column, nodes are ordered by time (then id) and centred vertically.
   Evidence is placed above the top-most node so it never overlaps the trail. */

import type { GraphEdge, GraphNode } from "../../types/api";
import { parseIso } from "../../lib/format";

export const COL_W = 226;
export const ROW_H = 140;
export const EVIDENCE_GAP = 170;

export interface Positioned {
  id: string;
  x: number;
  y: number;
  column: number;
}

export function columnOf(n: GraphNode): number {
  if (n.type === "transaction") return 2 * n.depth + 1;
  if (n.type === "account") return 2 * n.depth;
  return 1;
}

function timeKey(iso: string | null | undefined): number {
  const d = parseIso(iso ?? null);
  return d ? d.getTime() : Number.MAX_SAFE_INTEGER;
}

export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[], rootTxnId: string): Map<string, Positioned> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const root = byId.get(rootTxnId);
  const rootCol = root ? columnOf(root) : 1;

  // An account's sort time is the earliest transaction touching it (its arrival on the trail).
  const accTime = new Map<string, number>();
  for (const e of edges) {
    if (e.type !== "sent" && e.type !== "received_by") continue;
    const t = timeKey(e.time);
    for (const id of [e.source, e.target]) {
      const n = byId.get(id);
      if (n?.type === "account") accTime.set(id, Math.min(accTime.get(id) ?? Number.MAX_SAFE_INTEGER, t));
    }
  }

  const sortTime = (n: GraphNode): number => {
    if (n.type === "transaction") return timeKey(n.time);
    if (n.type === "account") return accTime.get(n.id) ?? Number.MAX_SAFE_INTEGER;
    return 0;
  };

  const cols = new Map<number, GraphNode[]>();
  const evidence: GraphNode[] = [];
  for (const n of nodes) {
    if (n.type === "evidence") {
      evidence.push(n);
      continue;
    }
    const c = n.type === "transaction" && n.id === rootTxnId ? rootCol : columnOf(n);
    if (!cols.has(c)) cols.set(c, []);
    cols.get(c)!.push(n);
  }

  const out = new Map<string, Positioned>();
  for (const [c, list] of cols) {
    list.sort((a, b) => sortTime(a) - sortTime(b) || a.id.localeCompare(b.id));
    const k = list.length;
    list.forEach((n, i) => {
      out.set(n.id, { id: n.id, column: c, x: c * COL_W, y: (i - (k - 1) / 2) * ROW_H });
    });
  }

  // Evidence sits above the disputed transaction, spread horizontally around it.
  evidence.sort((a, b) => a.id.localeCompare(b.id));
  const rootPos = out.get(rootTxnId) ?? { x: rootCol * COL_W, y: 0 };
  // Above every node, so evidence never overlaps a busy neighbouring column.
  const colTop = Math.min(0, ...Array.from(out.values()).map((p) => p.y));
  const ek = evidence.length;
  evidence.forEach((n, i) => {
    out.set(n.id, {
      id: n.id,
      column: rootCol,
      x: rootPos.x + (i - (ek - 1) / 2) * (COL_W * 0.9),
      y: colTop - EVIDENCE_GAP,
    });
  });
  return out;
}
