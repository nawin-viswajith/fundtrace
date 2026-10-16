import { ArrowLeftRight, FileText, KeyRound, Flag, CircleDot } from "lucide-react";
import { useTimeline } from "../../api/hooks";
import { useWorkspace } from "../case/workspace";
import { Card, EmptyState, ErrorState, LoadingBlock, MoneyRange, Time } from "../../components/Primitives";
import { ProvenanceChip } from "../../components/Chip";
import { IdChip } from "../../components/Domain";
import { humanize } from "../../lib/format";
import { isGraphId, ROLE_LABEL } from "../../lib/labels";

const KIND = {
  transaction: { icon: ArrowLeftRight, label: "Transaction" },
  auth_event: { icon: KeyRound, label: "Login / auth" },
  case: { icon: Flag, label: "Case" },
  evidence: { icon: FileText, label: "Evidence" },
} as const;

export function TimelineTab() {
  const { caseId, ctx, showOnGraph } = useWorkspace();
  const q = useTimeline(caseId);
  if (q.isLoading) return <LoadingBlock label="Loading timeline" lines={8} />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load the timeline" />;
  const d = q.data;
  if (!d || d.items.length === 0) return <EmptyState title="Nothing on the timeline">No records were found for this case.</EmptyState>;
  const cur = ctx.case.currency;
  return (
    <Card
      title="Timeline"
      subtitle="Every record on the trail in time order (IST; hover a time for UTC). This is the text equivalent of the trail graph, traced in both directions."
    >
      {d.empty && <p className="inline-note">Only the disputed transaction is on the trail — no onward or earlier transfers are visible.</p>}
      <div className="table-wrap">
        <table className="table timeline-table">
          <caption className="sr-only">Case timeline</caption>
          <thead>
            <tr>
              <th scope="col">Time (IST)</th>
              <th scope="col">Kind</th>
              <th scope="col">What happened</th>
              <th scope="col">Status</th>
              <th scope="col">Reference</th>
              <th scope="col">Provenance</th>
              <th scope="col" className="ta-r">
                May be disputed funds
              </th>
              <th scope="col">Record</th>
            </tr>
          </thead>
          <tbody>
            {d.items.map((it, i) => {
              const k = KIND[it.kind as keyof typeof KIND] ?? { icon: CircleDot, label: humanize(it.kind) };
              const Icon = k.icon;
              const disputed = it.id === d.disputed_txn_id;
              return (
                <tr key={`${it.id}-${i}`} className={disputed ? "row-disputed" : ""}>
                  <td data-label="Time">
                    <Time iso={it.time} seconds />
                  </td>
                  <td data-label="Kind">
                    <span className="kind-cell">
                      <Icon size={14} aria-hidden="true" /> {k.label}
                    </span>
                  </td>
                  <td data-label="What happened">
                    <span className={disputed ? "strong" : ""}>{it.title}</span>
                    {it.role && it.kind === "transaction" && (
                      <span className="cell-sub">
                        {ROLE_LABEL[it.role] ?? humanize(it.role)}
                        {disputed ? " transaction" : ""}
                      </span>
                    )}
                    {it.device && <span className="cell-sub mono">device {it.device}</span>}
                    {it.note && <span className="cell-sub">{it.note}</span>}
                  </td>
                  <td data-label="Status">
                    {it.status ? <span className={`txn-status txn-${it.status}`}>{humanize(it.status)}</span> : <span className="muted">—</span>}
                  </td>
                  <td data-label="Reference">
                    {it.kind === "transaction" ? (
                      it.reference ? <span className="mono">{it.reference}</span> : <span className="warn-text">missing</span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td data-label="Provenance">
                    <ProvenanceChip provenance={it.provenance} size="sm" />
                  </td>
                  <td data-label="May be disputed funds" className="ta-r">
                    {it.attribution ? <MoneyRange min={it.attribution.min} max={it.attribution.max} currency={cur} /> : <span className="muted">—</span>}
                  </td>
                  <td data-label="Record">
                    {isGraphId(it.id) ? (
                      <IdChip id={it.id} onClick={() => showOnGraph([it.id])} title={`Show ${it.id} on the trail graph`} />
                    ) : (
                      <IdChip id={it.id} />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
