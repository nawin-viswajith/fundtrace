import { MarkerType, type BuiltInEdge, type Edge } from "@xyflow/react";
import type { GraphEdge, GraphNode, TraceGraph } from "../../types/api";
import { provenanceStyle } from "../../lib/labels";
import { formatMoney } from "../../lib/format";
import { layoutGraph } from "./layout";
import type { AccountFlowNode, EvidenceFlowNode, TxnFlowNode } from "./nodes";

export type FlowNode = AccountFlowNode | TxnFlowNode | EvidenceFlowNode;

export function matchesHighlight(ids: string[], sourceIds: string[], set: Set<string>): boolean {
  if (!set.size) return false;
  return ids.some((i) => set.has(i)) || sourceIds.some((i) => set.has(i));
}

const EVIDENCE_REL = new Set(["supports", "contradicts", "relates_to"]);
const TXN_TXN = new Set(["possible_onward_funding", "reversal_of"]);

function handlesFor(e: GraphEdge, byId: Map<string, GraphNode>, backward: boolean): { sourceHandle: string; targetHandle: string } {
  const src = byId.get(e.source);
  const tgt = byId.get(e.target);
  if (EVIDENCE_REL.has(e.type) || src?.type === "evidence") return { sourceHandle: "eb", targetHandle: "tt" };
  if (TXN_TXN.has(e.type) && src?.type === "transaction" && tgt?.type === "transaction") return { sourceHandle: "bs", targetHandle: "bt" };
  // Money flowing back to an account further left (a cycle) arcs underneath instead of wrapping round.
  if (backward) return { sourceHandle: "bs", targetHandle: "bt" };
  return { sourceHandle: "r", targetHandle: "l" };
}

function shortEdgeLabel(e: GraphEdge, currency: string): string | undefined {
  if (e.type === "possible_onward_funding") {
    const min = typeof e.data.min === "number" ? e.data.min : null;
    const max = typeof e.data.max === "number" ? e.data.max : null;
    if (min !== null && min > 0) return `possible onward funding · ≥ ${formatMoney(min, currency)}`;
    if (max !== null) return `possible onward funding · ≤ ${formatMoney(max, currency)}`;
    return "possible onward funding";
  }
  if (e.type === "reversal_of") return "reversal of";
  if (e.type === "supports" || e.type === "contradicts") return e.type;
  if (e.type === "relates_to") return e.label ?? "relates to";
  return undefined;
}

/** Convert the API graph into React Flow nodes/edges with provenance styling and highlight state. */
export function toFlow(g: TraceGraph, highlight: string[], currency: string, disputedAmount: number): { nodes: FlowNode[]; edges: Edge[] } {
  const pos = layoutGraph(g.nodes, g.edges, g.root_txn_id);
  const set = new Set(highlight);
  const byId = new Map(g.nodes.map((n) => [n.id, n]));
  const hasHl = set.size > 0;
  const evRel = new Map<string, string>();
  for (const e of g.edges) if (EVIDENCE_REL.has(e.type)) evRel.set(e.source, e.type);

  const nodes: FlowNode[] = g.nodes.map((n) => {
    const p = pos.get(n.id) ?? { x: 0, y: 0 };
    const highlighted = matchesHighlight([n.id], n.source_ids, set);
    const common = { highlighted, dimmed: hasHl && !highlighted };
    const position = { x: p.x, y: p.y };
    if (n.type === "account") return { id: n.id, type: "account", position, data: { ...common, node: n } } as AccountFlowNode;
    if (n.type === "transaction") return { id: n.id, type: "transaction", position, data: { ...common, node: n } } as TxnFlowNode;
    return { id: n.id, type: "evidence", position, data: { ...common, node: n, relation: evRel.get(n.id) ?? null } } as EvidenceFlowNode;
  });

  const edges: Edge[] = g.edges
    .filter((e) => byId.has(e.source) && byId.has(e.target))
    .map((e) => {
      const prov = e.type === "contradicts" ? "contradictory" : e.provenance;
      const s = provenanceStyle(prov);
      const color = `var(--prov-${s.tone})`;
      let width = s.strokeWidth;
      // Width by amount for money-movement edges.
      const txn = byId.get(e.type === "sent" ? e.target : e.source);
      if ((e.type === "sent" || e.type === "received_by") && txn?.type === "transaction" && disputedAmount > 0) {
        width = s.strokeWidth + 2 * Math.min(1, txn.data.amount_minor / disputedAmount);
      }
      const onward = e.type === "possible_onward_funding";
      const dash = onward ? "6 5" : s.dash;
      const highlighted = matchesHighlight([e.source, e.target], e.source_ids, set);
      const ps = pos.get(e.source);
      const pt = pos.get(e.target);
      const backward = (e.type === "sent" || e.type === "received_by") && !!ps && !!pt && pt.x <= ps.x;
      const label = backward ? "returns to an account already on the path" : shortEdgeLabel(e, currency);
      return {
        id: e.id,
        source: e.source,
        target: e.target,
        ...handlesFor(e, byId, backward),
        type: "smoothstep",
        // Edges routed under the nodes drop by a fixed offset so they don't run flat along node bottoms.
        pathOptions: backward ? { offset: 70, borderRadius: 14 } : onward || TXN_TXN.has(e.type) ? { offset: 26, borderRadius: 10 } : { borderRadius: 8 },
        label,
        labelStyle: { fill: "var(--text-2)", fontSize: 11, fontWeight: 500 },
        labelBgStyle: { fill: "var(--surface)", fillOpacity: 0.92 },
        labelBgPadding: [6, 3] as [number, number],
        labelBgBorderRadius: 4,
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
        style: {
          stroke: color,
          strokeWidth: highlighted ? width + 1.5 : width,
          strokeDasharray: dash,
          opacity: hasHl && !highlighted ? 0.25 : onward ? 0.85 : 1,
        },
        className: `gedge gedge-${e.type} ${highlighted ? "is-highlighted" : ""}`,
        data: { edge: e },
        ariaLabel: `${e.type.replace(/_/g, " ")} from ${e.source} to ${e.target}, ${s.label}`,
      } satisfies BuiltInEdge;
    });
  return { nodes, edges };
}
