import { ArrowLeftRight, FileText, KeyRound, Flag, CircleDot } from "lucide-react";
import { useTimeline } from "../../api/hooks";
import { useWorkspace } from "../case/workspace";
import { Card, EmptyState, ErrorState, LoadingBlock, Time } from "../../components/Primitives";
import { ProvenanceChip } from "../../components/Chip";
import { IdChip } from "../../components/Domain";
import { humanize } from "../../lib/format";
import { plainRange, spanOf } from "../graph/moneySummary";
import { cleanName, statusLabel } from "../graph/plainText";
import { plainTitle, TRAIL_ROLE } from "./plainTitle";
import { isGraphId, ROLE_LABEL } from "../../lib/labels";

const KIND = {
  transaction: { icon: ArrowLeftRight, label: "Payment" },
  auth_event: { icon: KeyRound, label: "Sign-in / security" },
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
  const names = new Map<string, string>();
  for (const n of [ctx.payer, ctx.beneficiary, ...(ctx.graph?.nodes ?? [])]) if (n?.type === "account") names.set(n.id, cleanName(n.label));
  return (
    <Card
      title="What happened, in order"
      subtitle="Every payment, sign-in and evidence item for this case, oldest first. Times are Indian Standard Time (IST); point at a time to see UTC. Click a record ID to see it on the map."
    >
      {d.empty && <p className="inline-note">Only the disputed payment is on the trail. We can't see any money moving before or after it.</p>}
      <div className="table-wrap">
        <table className="table timeline-table">
          <caption className="sr-only">Case timeline</caption>
          <thead>
            <tr>
              <th scope="col">When (IST)</th>
              <th scope="col">What happened</th>
              <th scope="col">Status</th>
              <th scope="col">Payment reference (UTR)</th>
              <th scope="col" className="ta-r">
                Disputed money it may carry
              </th>
              <th scope="col">How we know</th>
            </tr>
          </thead>
          <tbody>
            {d.items.map((it, i) => {
              const k = KIND[it.kind as keyof typeof KIND] ?? {
                icon: CircleDot,
                label: humanize(it.kind),
              };
              const Icon = k.icon;
              const disputed = it.id === d.disputed_txn_id;
              return (
                <tr key={`${it.id}-${i}`} className={disputed ? "row-disputed" : ""}>
                  <td data-label="When">
                    <Time iso={it.time} seconds />
                  </td>
                  <td data-label="What happened" className="tl-what">
                    <span className="tl-what-body">
                      <span className="kind-cell tl-kind">
                        <Icon size={13} aria-hidden="true" /> {k.label}
                      </span>
                      <span className={disputed ? "strong" : ""} title={it.title}>
                        {plainTitle(it, names)}
                      </span>
                      {it.role && it.kind === "transaction" && (
                        <span className="cell-sub">{TRAIL_ROLE[it.role] ?? ROLE_LABEL[it.role] ?? humanize(it.role)}</span>
                      )}
                      {it.device && (
                        <span className="cell-sub">
                          Device <span className="mono">{it.device}</span>
                        </span>
                      )}
                      {it.note && <span className="cell-sub">{it.note}</span>}
                    </span>
                  </td>
                  <td data-label="Status" className={it.status ? "" : "tl-empty"}>
                    {it.status ? <span className={`txn-status txn-${it.status}`}>{statusLabel(it.status)}</span> : <span className="muted">—</span>}
                  </td>
                  <td data-label="Payment reference (UTR)" className={it.kind === "transaction" ? "" : "tl-empty"}>
                    {it.kind === "transaction" ? (
                      it.reference ? (
                        <span className="mono">{it.reference}</span>
                      ) : (
                        <span className="warn-text">Missing</span>
                      )
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td data-label="Disputed money it may carry" className={`ta-r ${disputed || it.attribution ? "" : "tl-empty"}`}>
                    {disputed ? (
                      <span className="small">All of it</span>
                    ) : it.attribution ? (
                      <span className="num" title="Smallest to largest result of the four ways of tracing the money">
                        {plainRange(spanOf(it.attribution), cur, {
                          capital: true,
                        })}
                      </span>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td data-label="How we know">
                    <span className="tl-source">
                      <ProvenanceChip provenance={it.provenance} size="sm" />
                      {isGraphId(it.id) ? (
                        <IdChip id={it.id} onClick={() => showOnGraph([it.id])} title={`Show ${it.id} on the map`} />
                      ) : (
                        <IdChip id={it.id} />
                      )}
                    </span>
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
