import { useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useNodesState,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertTriangle, Eye, Layers, X } from "lucide-react";
import { useGraph, useMeta } from "../../api/hooks";
import { useWorkspace } from "../case/workspace";
import { useToast } from "../../components/Toast";
import { ErrorState, Note, Skeleton, Spinner } from "../../components/Primitives";
import { IdChip } from "../../components/Domain";
import { Drawer } from "../../components/Overlay";
import { errorMessage } from "../../api/client";
import type { GraphEdge, GraphNode, GraphQueryParams } from "../../types/api";
import { GraphActionsCtx, nodeTypes } from "./nodes";
import { toFlow, type FlowNode } from "./flow";
import { GraphFilters } from "./GraphFilters";
import { NodeDetails, EdgeDetails } from "./DetailsPanel";
import { AttributionPanel } from "./AttributionPanel";
import { formatMoney, humanize } from "../../lib/format";
import { TrailLegend } from "./TrailLegend";
import { leadSentence } from "./moneySummary";
import { cleanName, directionLabel, relationLabel, windowLabel } from "./plainText";
import { useCssVars } from "../../lib/cssVars";

/** Smallest zoom on phones, so box text stays readable (people drag to see the rest). */
const NARROW_MIN_ZOOM = 0.85;

type Selection = { kind: "node"; id: string } | { kind: "edge"; id: string } | null;

export default function TrailGraphTab() {
  return (
    <ReactFlowProvider>
      <TrailGraph />
    </ReactFlowProvider>
  );
}

function TrailGraph() {
  const { caseId, ctx, highlight, clearHighlight } = useWorkspace();
  const meta = useMeta();
  const toast = useToast();
  const [params, setParams] = useState<GraphQueryParams>(() => ({
    direction: "both",
    depth: Math.min(ctx.graph.params.depth || 3, 5),
    window_hours: ctx.graph.params.window_hours || 72,
    status: [],
    rel: [],
    expand: [],
  }));
  const [expanding, setExpanding] = useState<string | null>(null);
  const [sel, setSel] = useState<Selection>(null);
  const q = useGraph(caseId, params);
  const rf = useReactFlow();
  const frameRef = useRef<HTMLDivElement>(null);
  const colors = useCssVars({
    dot: ["--canvas-dot", "#2a3850"],
    disputed: ["--disputed", "#2dd4bf"],
    txn: ["--prov-derived", "#60a5fa"],
    ev: ["--prov-inferred", "#fbbf24"],
    acc: ["--border-strong", "#3b4b67"],
    mask: ["--minimap-mask", "rgba(5,9,18,0.55)"],
  });
  const minimapColor = (n: { type?: string; data?: Record<string, unknown> }): string => {
    if (n.type === "transaction") {
      const node = n.data?.node as GraphNode | undefined;
      return node?.roles?.includes("disputed") ? colors.disputed : colors.txn;
    }
    if (n.type === "evidence") return colors.ev;
    return colors.acc;
  };

  const currency = ctx.case.currency;
  const flow = useMemo(
    () => (q.data ? toFlow(q.data.graph, highlight, currency, ctx.case.amount_minor) : { nodes: [] as FlowNode[], edges: [] as Edge[] }),
    [q.data, highlight, currency, ctx.case.amount_minor],
  );

  // React Flow writes measured sizes back through onNodesChange (needed for the minimap and dragging).
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<FlowNode>([]);
  useEffect(() => setRfNodes(flow.nodes), [flow.nodes, setRfNodes]);

  // Clear the expanding spinner (and report errors) once the expanded graph arrives.
  useEffect(() => {
    if (!expanding) return;
    if (q.error) {
      toast.show(errorMessage(q.error), "bad");
      setParams((p) => ({ ...p, expand: p.expand.filter((x) => x !== expanding) }));
      setExpanding(null);
    } else if (!q.isFetching) setExpanding(null);
  }, [q.isFetching, q.error, expanding, toast]);

  // Fit to highlighted records ("Show on graph"), otherwise to everything.
  const signature = flow.nodes.map((n) => n.id).join("|");
  useEffect(() => {
    if (!flow.nodes.length) return;
    const t = window.setTimeout(() => {
      const hl = flow.nodes.filter((n) => n.data.highlighted).map((n) => ({ id: n.id }));
      // On narrow screens fit to the start of the trail (payer -> disputed txn -> beneficiary) and let the user pan.
      const narrow = (frameRef.current?.clientWidth ?? 1000) < 640;
      const start = narrow
        ? flow.nodes
            .filter((n) => {
              const g = n.data.node;
              return (g.type === "account" && (g.depth === 0 || g.depth === 1)) || (g.type === "transaction" && g.depth === 0);
            })
            .map((n) => ({ id: n.id }))
        : [];
      const target = hl.length ? hl : start.length ? start : undefined;
      // On a phone, never shrink below a readable size: centre on the start of the trail and let people drag.
      rf.fitView({ nodes: target, padding: hl.length ? 0.5 : 0.06, duration: 300, maxZoom: 1.1, minZoom: narrow ? NARROW_MIN_ZOOM : undefined });
    }, 180);
    return () => window.clearTimeout(t);
  }, [signature, highlight.join("|"), rf]); // eslint-disable-line react-hooks/exhaustive-deps

  const nodeById = useMemo(() => new Map<string, GraphNode>((q.data?.graph.nodes ?? []).map((n) => [n.id, n])), [q.data]);
  const edgeById = useMemo(() => new Map<string, GraphEdge>((q.data?.graph.edges ?? []).map((e) => [e.id, e])), [q.data]);
  const selectId = (id: string) => {
    if (nodeById.has(id)) setSel({ kind: "node", id });
  };
  // From the money panel below the map: open the details and bring the map into view.
  const selectFromPanel = (id: string) => {
    if (!nodeById.has(id)) return;
    setSel({ kind: "node", id });
    frameRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    const narrow = (frameRef.current?.clientWidth ?? 1000) < 640;
    rf.fitView({ nodes: [{ id }], padding: 0.8, duration: 300, maxZoom: 1.1, minZoom: narrow ? NARROW_MIN_ZOOM : undefined });
  };

  const onExpand = (id: string) => {
    if (params.expand.includes(id)) return;
    setExpanding(id);
    setParams((p) => ({ ...p, expand: [...p.expand, id].slice(0, 10) }));
  };

  if (q.isLoading && !q.data)
    return (
      <div className="stack">
        <Skeleton height={64} />
        <Skeleton height={520} />
      </div>
    );
  if (q.error && !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load where the money went" />;
  if (!q.data) return null;

  const g = q.data.graph;
  const onlyRoot = g.stats.transactions <= 1;
  const selNode = sel?.kind === "node" ? nodeById.get(sel.id) : undefined;
  const selEdge = sel?.kind === "edge" ? edgeById.get(sel.id) : undefined;

  const stops = g.stats.endpoints;
  return (
    <div className="stack-lg">
      <header className="plain-intro">
        <h2 className="plain-intro-title">Where the money went</h2>
        <p className="plain-lead">{leadSentence(q.data.attribution)}</p>
        <p className="muted small">
          The map follows the disputed payment of <strong className="num">{formatMoney(q.data.attribution.disputed_amount_minor, currency)}</strong> from account
          to account. Click any box or line to see its details. The full breakdown is below the map.
        </p>
      </header>

      <GraphFilters value={params} onChange={(p) => setParams({ ...p, expand: p.direction === params.direction ? p.expand : [] })} relations={meta.data?.graph_relations} maxDepth={meta.data?.limits.max_depth ?? 5} />

      <div className="graph-status" aria-live="polite">
        <span className="muted small">
          Showing <span className="num">{g.stats.accounts}</span> account{g.stats.accounts === 1 ? "" : "s"} and{" "}
          <span className="num">{g.stats.transactions}</span> payment{g.stats.transactions === 1 ? "" : "s"} — {directionLabel(g.params.direction)}, over{" "}
          {windowLabel(g.params.window_hours)}. The trail stops at <span className="num">{stops}</span> place{stops === 1 ? "" : "s"}.
        </span>
        {q.isFetching && <Spinner size={14} label="Updating the map" />}
        {params.expand.length > 0 && (
          <span className="small">
            Followed further from:{" "}
            {params.expand.map((id) => (
              <span key={id} className="followed-name">
                {cleanName(nodeById.get(id)?.label) || <IdChip id={id} />}
              </span>
            ))}{" "}
            <button type="button" className="link-btn" onClick={() => setParams((p) => ({ ...p, expand: [] }))}>
              Undo
            </button>
          </span>
        )}
        {highlight.length > 0 && (
          <span className="hl-bar">
            <Eye size={14} aria-hidden="true" /> Highlighting {highlight.length} item{highlight.length > 1 ? "s" : ""} from another tab
            <button type="button" className="icon-btn icon-btn-sm" onClick={clearHighlight} aria-label="Clear highlight">
              <X size={13} />
            </button>
          </span>
        )}
      </div>

      {(g.truncated || g.warnings.length > 0) && (
        <Note tone="warn" icon={<AlertTriangle size={15} />}>
          {g.truncated && <p>Not everything is shown — the trail was too big. Use “Follow further” on an account, or show fewer steps.</p>}
          {g.warnings.map((w, i) => (
            <p key={i}>{w}</p>
          ))}
        </Note>
      )}
      {onlyRoot && (
        <Note tone="neutral" icon={<Layers size={15} />}>
          <p>
            <strong>We can't see the money move on from here.</strong> With these settings, only the disputed payment is on the map.
          </p>
          {g.nodes
            .filter((n) => n.type === "account" && n.endpoint)
            .map((n) => (
              <p key={n.id}>
                <strong>{cleanName(n.label) || n.id}</strong> <span className="muted small mono">{n.id}</span> — {n.endpoint_reason ?? humanize(n.endpoint ?? "")}
                {n.expandable ? " Use “Follow further” on its box to keep going." : ""}
              </p>
            ))}
          <p className="muted">Try “Both” or a longer time period. Not seeing it here does not mean it didn't happen.</p>
        </Note>
      )}

      <p className="graph-phone-hint small muted">Drag the map with one finger to follow the money, or see “Routes the money took” below for the same trail as a list.</p>
      <div className="graph-frame" ref={frameRef}>
        <GraphActionsCtx.Provider value={{ onExpand, expanding, currency }}>
          <ReactFlow
            nodes={rfNodes}
            onNodesChange={onNodesChange}
            edges={flow.edges}
            nodeTypes={nodeTypes}
            onNodeClick={(_, n) => setSel({ kind: "node", id: n.id })}
            onEdgeClick={(_, e) => setSel({ kind: "edge", id: e.id })}
            onPaneClick={() => setSel(null)}
            fitView
            fitViewOptions={{ padding: 0.06, maxZoom: 1.1 }}
            nodeOrigin={[0, 0.5]}
            minZoom={0.2}
            maxZoom={2}
            nodesConnectable={false}
            elementsSelectable
            aria-label="Map of where the money went"
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color={colors.dot} />
            <Controls showInteractive={false} position="bottom-left" />
            <MiniMap pannable zoomable position="bottom-right" className="graph-minimap" nodeColor={minimapColor} maskColor={colors.mask} />
          </ReactFlow>
        </GraphActionsCtx.Provider>
        <Drawer
          open={!!(selNode || selEdge)}
          onClose={() => setSel(null)}
          title={
            selNode
              ? selNode.type === "transaction"
                ? `${selNode.roles?.includes("disputed") ? "Disputed payment" : "Payment"} of ${formatMoney(selNode.data.amount_minor, selNode.data.currency)}`
                : selNode.type === "evidence"
                  ? `Evidence: ${selNode.label}`
                  : cleanName(selNode.label)
              : selEdge
                ? relationLabel(selEdge.type)
                : ""
          }
          subtitle={selNode ? <span className="mono small">{selNode.id}</span> : undefined}
        >
          {selNode && <NodeDetails node={selNode} att={q.data.attribution} nodes={nodeById} onSelect={selectId} />}
          {selEdge && <EdgeDetails edge={selEdge} currency={currency} nodes={nodeById} onSelect={selectId} />}
        </Drawer>
      </div>
      <TrailLegend />

      <p className="muted small graph-hint">
        Click a box or line to see its details. Drag to move the map; scroll or pinch to zoom. Prefer a list? The Timeline tab shows the same payments in time order.
      </p>

      <AttributionPanel
        att={q.data.attribution}
        paths={g.paths}
        nodes={nodeById}
        onSelect={selectFromPanel}
        traceParams={{ direction: params.direction, depth: params.depth, window_hours: params.window_hours, expand: params.expand }}
      />
    </div>
  );
}
