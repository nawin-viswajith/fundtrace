import { useMemo } from "react";
import { Link } from "react-router-dom";
import { ReactFlow, ReactFlowProvider, Background, BackgroundVariant, Handle, Position, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Info, Lock, Network, Smartphone } from "lucide-react";
import { useRings } from "../../api/hooks";
import { Card, EmptyState, ErrorState, LoadingBlock, Money, Note } from "../../components/Primitives";
import { SectionTitle, IdChip } from "../../components/Domain";
import type { Ring } from "../../types/api";
import { useCssVars } from "../../lib/cssVars";
import { canSupervise, useAuth } from "../auth/AuthProvider";
import { RecoveryPools } from "../recovery/RecoveryPools";

const centre = { left: "50%", top: "50%", opacity: 0, transform: "translate(-50%, -50%)", pointerEvents: "none" } as const;

/** Pill node with one centred handle, so straight edges run centre to centre beneath the nodes. */
function RingNode({ data }: NodeProps<Node<{ label: string; hub: boolean }>>) {
  return (
    <div className={`ring-pill ${data.hub ? "is-hub" : ""}`}>
      <Handle type="target" position={Position.Top} style={centre} isConnectable={false} />
      {data.label}
      {data.hub && <span className="ring-hub-tag">hub</span>}
      <Handle type="source" position={Position.Top} style={centre} isConnectable={false} />
    </div>
  );
}
const ringNodeTypes = { ring: RingNode };

/** Circle layout with the hub in the centre — deterministic. */
export function ringLayout(r: Ring): { nodes: Node[]; edges: Edge[] } {
  const others = r.accounts.filter((a) => a !== r.hub_account);
  const R = others.length <= 1 ? 170 : 150;
  const nodes: Node[] = [];
  if (r.hub_account) nodes.push({ id: r.hub_account, type: "ring", position: { x: 0, y: 0 }, data: { label: r.hub_account, hub: true } });
  others.forEach((a, i) => {
    const ang = (2 * Math.PI * i) / Math.max(1, others.length) - Math.PI / 2;
    nodes.push({ id: a, type: "ring", position: { x: Math.cos(ang) * R + (r.hub_account ? 0 : R), y: Math.sin(ang) * R * 0.75 }, data: { label: a, hub: false } });
  });
  // Parallel links between the same two accounts (a transfer and a shared device) are drawn as one line
  // with a combined label, so they never overlap.
  const groups = new Map<string, Ring["edges"]>();
  for (const e of r.edges) {
    const key = [e.source, e.target].sort().join("|");
    groups.set(key, [...(groups.get(key) ?? []), e]);
  }
  const edges: Edge[] = [...groups.values()].map((es, i) => {
    const transfers = es.filter((e) => e.kind !== "shared_device");
    const devices = es.filter((e) => e.kind === "shared_device");
    const deviceOnly = transfers.length === 0;
    const color = deviceOnly ? "var(--prov-inferred)" : "var(--prov-confirmed)";
    const txIds = [...new Set(transfers.map((e) => e.ref))];
    const devIds = [...new Set(devices.map((d) => d.ref))];
    const label = [
      ...(txIds.length === 1 ? [`transfer ${txIds[0]}`] : txIds.length ? [`${txIds.length} transfers`] : []),
      ...(devIds.length === 1 ? [`shared device ${devIds[0]}`] : devIds.length ? [`${devIds.length} shared devices`] : []),
    ].join(" · ");
    return {
      id: `${es[0].source}-${es[0].target}-${i}`,
      source: es[0].source,
      target: es[0].target,
      type: "straight",
      label,
      style: { stroke: color, strokeWidth: deviceOnly ? 1.75 : 2.25, strokeDasharray: deviceOnly ? "6 5" : undefined },
      labelStyle: { fill: "var(--text-2)", fontSize: 11 },
      labelBgStyle: { fill: "var(--surface)" },
    };
  });
  return { nodes, edges };
}

function RingGraph({ ring }: { ring: Ring }) {
  const { nodes, edges } = useMemo(() => ringLayout(ring), [ring]);
  const c = useCssVars({ dot: ["--canvas-dot", "#2a3850"] });
  return (
    <div className="ring-graph" aria-label={`Graph of ring around ${ring.hub_account ?? ring.accounts[0]}`}>
      <ReactFlowProvider>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={ringNodeTypes}
          nodeOrigin={[0.5, 0.5]}
          fitView
          fitViewOptions={{ padding: 0.35 }}
          nodesConnectable={false}
          nodesDraggable={false}
          panOnScroll={false}
          zoomOnScroll={false}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} color={c.dot} />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  );
}

export default function NetworkPage() {
  const q = useRings();
  const { user } = useAuth();
  return (
    <div className="page">
      <SectionTitle>Linked cases</SectionTitle>
      <p className="page-lede">Groups of disputes connected through the same receiving accounts or the same phone/device. One person may be behind several of them, so review them together.</p>
      {q.isLoading ? (
        <LoadingBlock label="Scanning trails" lines={6} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load network signals" />
      ) : !q.data ? null : (
        <div className="stack-lg">
          <Note tone="info" icon={<Info size={15} />}>
            {q.data.note} Scanned <span className="num">{q.data.cases_scanned}</span> cases and <span className="num">{q.data.accounts_in_trails}</span> accounts on
            their trails.
          </Note>
          {q.data.rings.length === 0 ? (
            <EmptyState title="No connected accounts found" icon={<Network size={22} />}>
              No account appears across two or more disputes you can see.
            </EmptyState>
          ) : (
            <div className="ring-grid">
              {q.data.rings.map((r, i) => (
                <Card key={i} className="ring-card" title={r.signal} subtitle={<>Disputed total <Money minor={r.disputed_amount_minor} currency={r.currency} className="strong" /></>}>
                  <RingGraph ring={r} />
                  <div className="ring-legend small">
                    <span>
                      <svg width="28" height="8" aria-hidden="true">
                        <line x1="1" y1="4" x2="27" y2="4" stroke="var(--prov-confirmed)" strokeWidth="2.25" />
                      </svg>{" "}
                      Transfer (ledger)
                    </span>
                    <span>
                      <svg width="28" height="8" aria-hidden="true">
                        <line x1="1" y1="4" x2="27" y2="4" stroke="var(--prov-inferred)" strokeWidth="1.75" strokeDasharray="6 5" />
                      </svg>{" "}
                      Shared device (link, not a transfer)
                    </span>
                  </div>
                  <dl className="kv">
                    <div className="kv-row">
                      <dt>Hub account</dt>
                      <dd>{r.hub_account ? <IdChip id={r.hub_account} /> : <span className="muted">none</span>}</dd>
                    </div>
                    <div className="kv-row">
                      <dt>Accounts</dt>
                      <dd className="id-list">
                        {r.accounts.map((a) => (
                          <IdChip key={a} id={a} />
                        ))}
                      </dd>
                    </div>
                    <div className="kv-row">
                      <dt>Cases</dt>
                      <dd className="id-list">
                        {r.cases.map((c, j) =>
                          c === "restricted" ? (
                            <span key={`r${j}`} className="id-chip id-restricted" title="Assigned to another investigator">
                              <Lock size={11} aria-hidden="true" /> restricted
                            </span>
                          ) : (
                            <Link key={c} to={`/cases/${c}`} className="id-chip id-chip-btn">
                              {c}
                            </Link>
                          ),
                        )}
                      </dd>
                    </div>
                    <div className="kv-row">
                      <dt>Shared devices</dt>
                      <dd className="id-list">
                        {r.shared_devices.length ? (
                          r.shared_devices.map((d) => (
                            <span key={d} className="id-chip">
                              <Smartphone size={11} aria-hidden="true" /> {d}
                            </span>
                          ))
                        ) : (
                          <span className="muted">none</span>
                        )}
                      </dd>
                    </div>
                  </dl>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}
      <RecoveryPools canRecord={canSupervise(user)} />
    </div>
  );
}
