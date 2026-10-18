import { createContext, memo, useContext } from "react";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { AlertTriangle, Building2, ChevronsRight, FileText, Landmark, Store, Ban, RotateCcw } from "lucide-react";
import type { AccountNode, EvidenceNode, TransactionNode } from "../../types/api";
import { ENDPOINT_BADGE, ROLE_LABEL } from "../../lib/labels";
import { formatISTTime, formatIST, formatMoney, formatUTC, humanize } from "../../lib/format";
import { plainRange, spanOf } from "./moneySummary";
import { cleanName, statusLabel } from "./plainText";

export interface GraphActions {
  onExpand: (accountId: string) => void;
  expanding: string | null;
  currency: string;
}
export const GraphActionsCtx = createContext<GraphActions>({ onExpand: () => undefined, expanding: null, currency: "INR" });

interface Common {
  highlighted: boolean;
  dimmed: boolean;
  [k: string]: unknown;
}
export type AccountFlowNode = Node<Common & { node: AccountNode }, "account">;
export type TxnFlowNode = Node<Common & { node: TransactionNode }, "transaction">;
export type EvidenceFlowNode = Node<Common & { node: EvidenceNode; relation: string | null }, "evidence">;

function stateClass(d: Common, selected: boolean | undefined) {
  return `${d.highlighted ? "is-highlighted" : ""} ${d.dimmed ? "is-dimmed" : ""} ${selected ? "is-selected" : ""}`;
}

const hidden = { opacity: 0 } as const;

export const AccountNodeView = memo(function AccountNodeView({ data, selected }: NodeProps<AccountFlowNode>) {
  const n = data.node;
  const { onExpand, expanding } = useContext(GraphActionsCtx);
  const ext = n.data.external;
  const Icon = n.endpoint === "merchant" ? Store : ext ? Landmark : Building2;
  return (
    <div className={`gnode gnode-account prov-border-${n.provenance} ${ext ? "is-external" : ""} ${stateClass(data, selected)}`}>
      <Handle type="target" position={Position.Left} id="l" style={hidden} isConnectable={false} />
      <Handle type="target" position={Position.Top} id="tt" style={hidden} isConnectable={false} />
      <Handle type="target" position={Position.Bottom} id="bt" style={hidden} isConnectable={false} />
      <div className="gnode-badges">
        {(n.roles ?? []).map((r) => (
          <span key={r} className={`role-badge role-badge-${r}`}>
            {ROLE_LABEL[r] ?? humanize(r)}
          </span>
        ))}
        {n.endpoint && (
          <span className={`endpoint-badge endpoint-${n.endpoint}`} title={n.endpoint_reason ?? undefined}>
            <span className="sr-only">Trail stops: </span>
            {ENDPOINT_BADGE[n.endpoint] ?? humanize(n.endpoint)}
          </span>
        )}
      </div>
      <div className="gnode-title">
        <Icon size={14} aria-hidden="true" />
        <span className="gnode-label" title={n.label}>
          {cleanName(n.label)}
        </span>
      </div>
      <div className="gnode-sub">
        <span title={n.data.institution}>{cleanName(n.data.institution)}</span>
        {ext && <span className="gnode-ext">· other bank</span>}
      </div>
      <div className="gnode-id mono">
        {n.data.masked_number} · {n.id}
      </div>
      {n.expandable && (
        <button
          type="button"
          className="gnode-expand nodrag nopan"
          onClick={(e) => {
            e.stopPropagation();
            onExpand(n.id);
          }}
          disabled={expanding === n.id}
          aria-label={`Follow the money further from ${cleanName(n.label) || n.id}`}
        >
          <ChevronsRight size={13} aria-hidden="true" /> {expanding === n.id ? "Loading…" : "Follow further"}
        </button>
      )}
      <Handle type="source" position={Position.Right} id="r" style={hidden} isConnectable={false} />
      <Handle type="source" position={Position.Bottom} id="bs" style={hidden} isConnectable={false} />
    </div>
  );
});

export const TxnNodeView = memo(function TxnNodeView({ data, selected }: NodeProps<TxnFlowNode>) {
  const n = data.node;
  const t = n.data;
  const disputed = (n.roles ?? []).includes("disputed");
  const muted = t.status === "failed" || t.status === "reversed";
  const a = n.attribution;
  const missingRef = t.reference_missing || !t.reference || (n.flags ?? []).includes("missing_reference");
  return (
    <div className={`gnode gnode-txn prov-border-${n.provenance} ${disputed ? "is-disputed" : ""} ${muted ? "is-muted" : ""} ${stateClass(data, selected)}`}>
      <Handle type="target" position={Position.Left} id="l" style={hidden} isConnectable={false} />
      <Handle type="target" position={Position.Top} id="tt" style={hidden} isConnectable={false} />
      <Handle type="target" position={Position.Bottom} id="bt" style={hidden} isConnectable={false} />
      {disputed && <span className="disputed-tag">Disputed payment</span>}
      <div className="gnode-amount num">{formatMoney(t.amount_minor, t.currency)}</div>
      <div className="gnode-sub">
        {t.channel} · <time title={formatUTC(n.time)}>{formatISTTime(n.time)} IST</time>
        <span className={`txn-status txn-${t.status}`}>
          {t.status === "failed" && <Ban size={10} aria-hidden="true" />}
          {t.status === "reversed" && <RotateCcw size={10} aria-hidden="true" />}
          {statusLabel(t.status)}
        </span>
      </div>
      {a && !disputed && (
        <div className="gnode-attr" title="Smallest to largest result of the four ways of tracing the money">
          <span className="num">{plainRange(spanOf(a), t.currency, { capital: true })}</span> of this may be the disputed money
        </div>
      )}
      {missingRef && (
        <div className="gnode-warn">
          <AlertTriangle size={11} aria-hidden="true" /> No payment reference (UTR)
        </div>
      )}
      <div className="gnode-id mono" title={formatIST(n.time, { seconds: true })}>
        {n.id}
      </div>
      <Handle type="source" position={Position.Right} id="r" style={hidden} isConnectable={false} />
      <Handle type="source" position={Position.Bottom} id="bs" style={hidden} isConnectable={false} />
    </div>
  );
});

export const EvidenceNodeView = memo(function EvidenceNodeView({ data, selected }: NodeProps<EvidenceFlowNode>) {
  const n = data.node;
  const rel = data.relation;
  const status = n.data.analysis_status;
  return (
    <div className={`gnode gnode-evidence prov-border-${n.provenance} ${stateClass(data, selected)}`}>
      <div className="gnode-title">
        <FileText size={14} aria-hidden="true" />
        <span className="gnode-label" title={n.label}>
          {n.label}
        </span>
      </div>
      <div className="gnode-sub">
        <span className="gnode-kind">Evidence ·</span>
        <span className={`ev-status ev-${status}`}>{status === "not_analysed" ? "Not analysed yet" : humanize(status)}</span>
        {rel && rel !== "relates_to" && <span className={`ev-rel ev-rel-${rel}`}>{rel === "supports" ? "Supports" : "Contradicts"}</span>}
      </div>
      {n.data.summary && <div className="gnode-note">{n.data.summary}</div>}
      <div className="gnode-id mono">{n.id}</div>
      <Handle type="source" position={Position.Bottom} id="eb" style={hidden} isConnectable={false} />
    </div>
  );
});

export const nodeTypes = { account: AccountNodeView, transaction: TxnNodeView, evidence: EvidenceNodeView };
