import type { ReactNode } from "react";
import type { Attribution, GraphEdge, GraphNode } from "../../types/api";
import { KeyValues, Money, Time } from "../../components/Primitives";
import { ProvenanceChip } from "../../components/Chip";
import { IdList } from "../../components/Domain";
import { ENDPOINT_BADGE, ROLE_LABEL } from "../../lib/labels";
import { formatUTC, humanize } from "../../lib/format";
import { MethodTable } from "./AttributionPanel";

function TimeBoth({ iso }: { iso: string | null | undefined }) {
  if (!iso) return <span className="muted">—</span>;
  return (
    <span className="time-both">
      <Time iso={iso} seconds />
      <span className="cell-sub mono">{formatUTC(iso)}</span>
    </span>
  );
}

export function NodeDetails({ node, att, onSelect }: { node: GraphNode; att: Attribution; onSelect: (id: string) => void }) {
  const cur = att.currency;
  const common: [ReactNode, ReactNode][] = [
    ["Provenance", <ProvenanceChip key="p" provenance={node.provenance} showMeaning />],
    ["Source records", <IdList key="s" ids={node.source_ids} />],
  ];
  if (node.roles?.length) common.push(["Roles", node.roles.map((r) => ROLE_LABEL[r] ?? humanize(r)).join(", ")]);

  if (node.type === "account") {
    const d = node.data;
    const per = att.per_account?.[node.id];
    const exit = att.exits?.[node.id];
    const hold = att.holdable?.find((h) => h.account_id === node.id);
    return (
      <div className="stack">
        <KeyValues
          rows={[
            ["Holder", node.label],
            ["Account", <span key="a" className="mono">{node.id} · {d.masked_number}</span>],
            ["Institution", `${d.institution}${d.external ? " (external)" : ""}`],
            ["Kind", humanize(d.kind)],
            ["Opened", d.opened_at ? <Time key="o" iso={d.opened_at} dateOnly /> : <span className="muted">Not visible</span>],
            ["Trace depth", node.depth],
            ...common,
          ]}
        />
        {node.endpoint && (
          <div className="note note-warn">
            <div>
              <strong>{ENDPOINT_BADGE[node.endpoint] ?? humanize(node.endpoint)}</strong>
              {node.endpoint_reason && <p className="small">{node.endpoint_reason}</p>}
              {node.provenance_note && <p className="small muted">{node.provenance_note}</p>}
            </div>
          </div>
        )}
        {per && (
          <section>
            <h4 className="h-sub">Disputed funds that may remain here</h4>
            <MethodTable values={per.residual} currency={cur} caption="Residual by method" />
            <p className="small muted">
              Balance at window end: <Money minor={per.balance_at_window_end} currency={cur} />
            </p>
          </section>
        )}
        {exit && (
          <section>
            <h4 className="h-sub">Disputed funds that may have left to this institution</h4>
            <MethodTable values={exit} currency={cur} caption="Exit by method" />
          </section>
        )}
        {hold && (
          <p className="small">
            Hold candidate: up to <Money minor={hold.max_minor} currency={cur} /> (see Overview → Hold recommendations).
          </p>
        )}
      </div>
    );
  }

  if (node.type === "transaction") {
    const t = node.data;
    const a = node.attribution ?? att.per_transaction?.[node.id];
    const disputed = node.roles?.includes("disputed");
    return (
      <div className="stack">
        <KeyValues
          rows={[
            ["Amount", <Money key="m" minor={t.amount_minor} currency={t.currency} className="strong" />],
            ["Status", <span key="s" className={`txn-status txn-${t.status}`}>{t.status}</span>],
            ["Channel", t.channel],
            ["Reference", t.reference ? <span key="r" className="mono">{t.reference}</span> : <span key="r" className="warn-text">Missing</span>],
            ["From", <IdList key="f" ids={[t.debit_account_id]} onSelect={onSelect} />],
            ["To", <IdList key="t" ids={[t.credit_account_id]} onSelect={onSelect} />],
            ["Occurred", <TimeBoth key="o" iso={t.occurred_at} />],
            ["Posted", <TimeBoth key="p" iso={t.posted_at} />],
            ["Device", t.device_id ?? <span className="muted">—</span>],
            ["Source system", <span key="ss" className="mono">{t.source_system}:{t.source_record_id}</span>],
            ["Narrative", t.narrative || <span className="muted">—</span>],
            ["Direction", humanize(node.direction)],
            ...(t.reversal_of_id ? ([["Reversal of", <IdList key="rv" ids={[t.reversal_of_id]} onSelect={onSelect} />]] as [ReactNode, ReactNode][]) : []),
            ...common,
          ]}
        />
        {disputed ? (
          <p className="small muted">This is the disputed transaction: its full amount is the starting point of the trail.</p>
        ) : a ? (
          <section>
            <h4 className="h-sub">How much of this may be disputed funds</h4>
            <MethodTable values={a} currency={t.currency} caption="Attribution by method" />
            <p className="small muted">
              Attribution provenance: <ProvenanceChip provenance={a.provenance ?? "derived"} size="sm" /> — the lower bound is forced by the
              ledger; the upper bound is possible, not established.
            </p>
          </section>
        ) : (
          <p className="small muted">No attribution computed for this transaction (outside the forward trail).</p>
        )}
      </div>
    );
  }

  const d = node.data;
  return (
    <div className="stack">
      <KeyValues
        rows={[
          ["File", node.label],
          ["Kind", humanize(d.kind)],
          ["Analysis", d.analysis_status === "not_analysed" ? "Not analysed" : humanize(d.analysis_status)],
          ["SHA-256", <span key="h" className="mono break">{d.sha256}</span>],
          ...(d.summary ? ([["Summary", d.summary]] as [ReactNode, ReactNode][]) : []),
          ...common,
        ]}
      />
      {d.checks && d.checks.length > 0 && (
        <table className="mini-table">
          <thead>
            <tr>
              <th scope="col">Field</th>
              <th scope="col">Document</th>
              <th scope="col">Ledger</th>
              <th scope="col">Result</th>
            </tr>
          </thead>
          <tbody>
            {d.checks.map((c, i) => (
              <tr key={i}>
                <td>{humanize(c.field)}</td>
                <td>{c.document_value ?? "—"}</td>
                <td>{c.ledger_value ?? "—"}</td>
                <td>{humanize(c.result)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function EdgeDetails({ edge, currency, onSelect }: { edge: GraphEdge; currency: string; onSelect: (id: string) => void }) {
  const hasRange = typeof edge.data.min === "number";
  return (
    <div className="stack">
      <KeyValues
        rows={[
          ["Relationship", humanize(edge.type)],
          ["From", <IdList key="f" ids={[edge.source]} onSelect={onSelect} />],
          ["To", <IdList key="t" ids={[edge.target]} onSelect={onSelect} />],
          ["Provenance", <ProvenanceChip key="p" provenance={edge.provenance} showMeaning />],
          ["Time", <TimeBoth key="ti" iso={edge.time} />],
          ["Source records", <IdList key="s" ids={edge.source_ids} />],
          ...(edge.label ? ([["Label", edge.label]] as [ReactNode, ReactNode][]) : []),
        ]}
      />
      {hasRange && (
        <section>
          <h4 className="h-sub">Attribution by method</h4>
          <MethodTable
            values={{ min: edge.data.min as number, fifo: edge.data.fifo as number, pro_rata: edge.data.pro_rata as number, max: edge.data.max as number }}
            currency={currency}
            caption="Edge attribution"
          />
        </section>
      )}
      {edge.type === "possible_onward_funding" && (
        <p className="small muted">
          This link says the later transfer may have been funded by the earlier one. Timing alone does not establish it; the range above is
          what balance arithmetic allows.
        </p>
      )}
    </div>
  );
}
