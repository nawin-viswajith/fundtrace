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
import { ProvenanceLegend, IdChip } from "../../components/Domain";
import { Drawer } from "../../components/Overlay";
import { errorMessage } from "../../api/client";
import type { GraphEdge, GraphNode, GraphQueryParams } from "../../types/api";
import { GraphActionsCtx, nodeTypes } from "./nodes";
import { toFlow, type FlowNode } from "./flow";
import { GraphFilters } from "./GraphFilters";
import { NodeDetails, EdgeDetails } from "./DetailsPanel";
import { AttributionPanel } from "./AttributionPanel";
import { humanize } from "../../lib/format";
import { useCssVars } from "../../lib/cssVars";

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
    dot: ["--canvas-dot", "#d8dce3"],
    disputed: ["--disputed", "#3a3fb3"],
    txn: ["--prov-derived", "#2c68cf"],
    ev: ["--prov-inferred", "#b8740f"],
    acc: ["--border-strong", "#c9ced7"],
    mask: ["--overlay", "rgba(15,18,26,0.38)"],
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
      rf.fitView({ nodes: target, padding: hl.length ? 0.5 : 0.06, duration: 300, maxZoom: 1.1 });
    }, 180);
    return () => window.clearTimeout(t);
  }, [signature, highlight.join("|"), rf]); // eslint-disable-line react-hooks/exhaustive-deps

  const nodeById = useMemo(() => new Map<string, GraphNode>((q.data?.graph.nodes ?? []).map((n) => [n.id, n])), [q.data]);
  const edgeById = useMemo(() => new Map<string, GraphEdge>((q.data?.graph.edges ?? []).map((e) => [e.id, e])), [q.data]);
  const selectId = (id: string) => {
    if (nodeById.has(id)) setSel({ kind: "node", id });
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
  if (q.error && !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load the trail" />;
  if (!q.data) return null;

  const g = q.data.graph;
  const onlyRoot = g.stats.transactions <= 1;
  const selNode = sel?.kind === "node" ? nodeById.get(sel.id) : undefined;
  const selEdge = sel?.kind === "edge" ? edgeById.get(sel.id) : undefined;

  return (
    <div className="stack-lg">
      <GraphFilters value={params} onChange={(p) => setParams({ ...p, expand: p.direction === params.direction ? p.expand : [] })} relations={meta.data?.graph_relations} maxDepth={meta.data?.limits.max_depth ?? 5} />

      <div className="graph-status" aria-live="polite">
        <span className="muted small">
          <span className="num">{g.stats.accounts}</span> accounts · <span className="num">{g.stats.transactions}</span> transactions ·{" "}
          <span className="num">{g.stats.endpoints}</span> endpoints · window {humanize(g.params.direction)} {g.params.window_hours} h
        </span>
        {q.isFetching && <Spinner size={14} label="Updating trail" />}
        {params.expand.length > 0 && (
          <span className="small">
            Expanded: {params.expand.map((id) => <IdChip key={id} id={id} />)}{" "}
            <button type="button" className="link-btn" onClick={() => setParams((p) => ({ ...p, expand: [] }))}>
              Clear
            </button>
          </span>
        )}
        {highlight.length > 0 && (
          <span className="hl-bar">
            <Eye size={14} aria-hidden="true" /> Highlighting {highlight.length} record{highlight.length > 1 ? "s" : ""}
            <button type="button" className="icon-btn icon-btn-sm" onClick={clearHighlight} aria-label="Clear highlight">
              <X size={13} />
            </button>
          </span>
        )}
      </div>

      {(g.truncated || g.warnings.length > 0) && (
        <Note tone="warn" icon={<AlertTriangle size={15} />}>
          {g.truncated && <p>Trace limits were reached — not all activity is shown. Expand an account or narrow the filters.</p>}
          {g.warnings.map((w, i) => (
            <p key={i}>{w}</p>
          ))}
        </Note>
      )}
      {onlyRoot && (
        <Note tone="neutral" icon={<Layers size={15} />}>
          <p>
            <strong>No onward trail visible.</strong> Only the disputed transaction is on the trail with these filters.
          </p>
          {g.nodes
            .filter((n) => n.type === "account" && n.endpoint)
            .map((n) => (
              <p key={n.id}>
                <IdChip id={n.id} /> {n.endpoint_reason ?? humanize(n.endpoint ?? "")}
                {n.expandable ? " — use Expand on the node to follow it." : ""}
              </p>
            ))}
          <p className="muted">Try “Both” directions or a longer window. Unknown beyond this point is not the same as absent.</p>
        </Note>
      )}

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
            aria-label="Transaction trail graph"
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color={colors.dot} />
            <Controls showInteractive={false} position="bottom-left" />
            <MiniMap pannable zoomable position="bottom-right" className="graph-minimap" nodeColor={minimapColor} maskColor={colors.mask} />
          </ReactFlow>
        </GraphActionsCtx.Provider>
        <Drawer
          open={!!(selNode || selEdge)}
          onClose={() => setSel(null)}
          title={selNode ? (selNode.type === "transaction" ? `Transaction ${selNode.id}` : selNode.type === "evidence" ? `Evidence ${selNode.id}` : selNode.label) : selEdge ? humanize(selEdge.type) : ""}
          subtitle={selNode && selNode.type === "account" ? <span className="mono">{selNode.id}</span> : selEdge ? <span className="mono small">{selEdge.id}</span> : undefined}
        >
          {selNode && <NodeDetails node={selNode} att={q.data.attribution} onSelect={selectId} />}
          {selEdge && <EdgeDetails edge={selEdge} currency={currency} onSelect={selectId} />}
        </Drawer>
      </div>
      <div className="legend-strip" aria-label="Graph legend">
        <ProvenanceLegend compact />
        <ul className="legend-extra">
          <li>
            <svg width="34" height="10" aria-hidden="true">
              <line x1="1" y1="5" x2="33" y2="5" stroke="var(--prov-derived)" strokeWidth="1.75" strokeDasharray="6 5" />
            </svg>
            <span>
              <strong>Possible onward funding</strong> <span className="muted">(range from balance arithmetic)</span>
            </span>
          </li>
          <li>
            <span className="legend-box legend-disputed" aria-hidden="true" />
            <span>Disputed transaction</span>
          </li>
          <li>
            <span className="legend-box legend-muted" aria-hidden="true" />
            <span>Failed / reversed</span>
          </li>
          <li className="muted">Line width grows with the amount</li>
        </ul>
      </div>

      <p className="muted small graph-hint">
        Click a node or line for its records. Drag to pan, scroll or pinch to zoom. The Timeline tab lists the same trail as an accessible table.
      </p>

      <AttributionPanel att={q.data.attribution} paths={g.paths} onSelect={selectId} />
    </div>
  );
}
