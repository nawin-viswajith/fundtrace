import type { ReactNode } from "react";
import type { Attribution, AttributionMethod, GraphEdge, GraphNode } from "../../types/api";
import { KeyValues, Money, Time } from "../../components/Primitives";
import { ProvenanceChip } from "../../components/Chip";
import { IdList } from "../../components/Domain";
import { ENDPOINT_BADGE, provenanceStyle, ROLE_LABEL } from "../../lib/labels";
import { formatMoney, formatUTC, humanize } from "../../lib/format";
import { MethodTable, MethodsExplained } from "./AttributionPanel";
import { plainRange, spanOf } from "./moneySummary";
import { cleanName, directionLabel, relationLabel, statusLabel } from "./plainText";

type Rows = [ReactNode, ReactNode][];
type Nodes = Map<string, GraphNode>;

function TimeBoth({ iso }: { iso: string | null | undefined }) {
  if (!iso) return <span className="muted">—</span>;
  return (
    <span className="time-both">
      <Time iso={iso} seconds />
      <span className="cell-sub mono">{formatUTC(iso)}</span>
    </span>
  );
}

/** Provenance chip with its meaning on its own line (fits the narrow details panel). */
function HowWeKnow({ provenance }: { provenance: string }) {
  const s = provenanceStyle(provenance);
  return (
    <span className="how-we-know">
      <ProvenanceChip provenance={provenance} size="sm" />
      <span className="small muted">{s.meaning}</span>
    </span>
  );
}

/** A record shown by name (clickable), with its id small underneath. */
function NameLink({ id, nodes, onSelect }: { id: string; nodes: Nodes; onSelect: (id: string) => void }) {
  const n = nodes.get(id);
  const name =
    n?.type === "transaction" ? `Payment of ${formatMoney(n.data.amount_minor, n.data.currency)}` : n ? cleanName(n.label) || id : id;
  return (
    <span className="name-link">
      <button type="button" className="link-btn name-btn" onClick={() => onSelect(id)}>
        {name}
      </button>
      <span className="cell-sub mono">{id}</span>
    </span>
  );
}

/** Codes and internal ids, kept but out of the way. */
function RecordDetails({ rows }: { rows: Rows }) {
  return (
    <details className="disclosure">
      <summary>Show record details</summary>
      <div className="disclosure-body">
        <KeyValues rows={rows} />
      </div>
    </details>
  );
}

/** Plain sentence with the range, then the four-method table behind a disclosure. */
function MoneyFigure({ sentence, values, currency, caption, extra }: { sentence: ReactNode; values: Partial<Record<AttributionMethod, number>>; currency: string; caption: string; extra?: ReactNode }) {
  return (
    <>
      <p>{sentence}</p>
      <details className="disclosure">
        <summary>Show how this was worked out</summary>
        <div className="disclosure-body">
          <MethodTable values={values} currency={currency} caption={caption} />
          {extra}
          <MethodsExplained />
        </div>
      </details>
    </>
  );
}

export function NodeDetails({ node, att, nodes, onSelect }: { node: GraphNode; att: Attribution; nodes: Nodes; onSelect: (id: string) => void }) {
  const cur = att.currency;
  const how: Rows = [["How we know", <HowWeKnow key="p" provenance={node.provenance} />]];
  const records: Rows = [["Record IDs", <IdList key="s" ids={node.source_ids} />]];
  const role: Rows = node.roles?.length ? [["Role", node.roles.map((r) => ROLE_LABEL[r] ?? humanize(r)).join(", ")]] : [];

  if (node.type === "account") {
    const d = node.data;
    const per = att.per_account?.[node.id];
    const exit = att.exits?.[node.id];
    const hold = att.holdable?.find((h) => h.account_id === node.id);
    return (
      <div className="stack">
        <KeyValues
          rows={[
            ["Account holder", cleanName(node.label)],
            ["Bank", `${cleanName(d.institution)}${d.external ? " (another bank)" : ""}`],
            ["Account number", <span key="a" className="mono">{d.masked_number}</span>],
            ["Account type", humanize(d.kind)],
            ["Opened on", d.opened_at ? <Time key="o" iso={d.opened_at} dateOnly /> : <span className="muted">Not visible to this bank</span>],
            ...role,
            ["Steps from the disputed payment", Math.abs(node.depth)],
            ...how,
          ]}
        />
        {node.endpoint && (
          <div className="note note-warn">
            <div>
              <strong>The trail stops here: {ENDPOINT_BADGE[node.endpoint] ?? humanize(node.endpoint)}</strong>
              {node.endpoint_reason && <p className="small">{node.endpoint_reason}</p>}
              {node.provenance_note && <p className="small muted">{node.provenance_note}</p>}
            </div>
          </div>
        )}
        {per && (
          <section>
            <h4 className="plain-sub">Disputed money that may still be here</h4>
            <MoneyFigure
              sentence={
                <>
                  <strong className="num">{plainRange(spanOf(per.residual), cur, { capital: true })}</strong> of the disputed money may still be in
                  this account. Its balance at the end of the time period was <Money minor={per.balance_at_window_end} currency={cur} />.
                </>
              }
              values={per.residual}
              currency={cur}
              caption="Disputed money that may still be here, by tracing method"
            />
          </section>
        )}
        {exit && (
          <section>
            <h4 className="plain-sub">Disputed money that may have gone to this bank</h4>
            <MoneyFigure
              sentence={
                <>
                  <strong className="num">{plainRange(spanOf(exit), cur, { capital: true })}</strong> of the disputed money may have been sent here.
                  This bank cannot see where it went next.
                </>
              }
              values={exit}
              currency={cur}
              caption="Disputed money sent here, by tracing method"
            />
          </section>
        )}
        {hold && (
          <p className="small">
            <strong>Could be held:</strong> up to <Money minor={hold.max_minor} currency={cur} />. See Overview → Hold recommendations.
          </p>
        )}
        <RecordDetails rows={[["Account ID", <span key="i" className="mono">{node.id}</span>], ...records]} />
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
            ["From", <NameLink key="f" id={t.debit_account_id} nodes={nodes} onSelect={onSelect} />],
            ["To", <NameLink key="t" id={t.credit_account_id} nodes={nodes} onSelect={onSelect} />],
            ["Made at", <TimeBoth key="o" iso={t.occurred_at} />],
            ["Status", <span key="s" className={`txn-status txn-${t.status}`}>{statusLabel(t.status)}</span>],
            ["Payment method", t.channel],
            [
              "Payment reference (UTR)",
              t.reference ? <span key="r" className="mono">{t.reference}</span> : <span key="r" className="warn-text">Missing — ask the payment network for it</span>,
            ],
            ["Payment note", t.narrative || <span className="muted">—</span>],
            ...(t.reversal_of_id ? ([["Reverses", <NameLink key="rv" id={t.reversal_of_id} nodes={nodes} onSelect={onSelect} />]] as Rows) : []),
            ["Part of", directionLabel(node.direction)],
            ...how,
          ]}
        />
        {disputed ? (
          <p className="small muted">This is the disputed payment. The whole amount is where the trail starts.</p>
        ) : a ? (
          <section>
            <h4 className="plain-sub">How much of this may be the disputed money</h4>
            <MoneyFigure
              sentence={
                <>
                  <strong className="num">{plainRange(spanOf(a), t.currency, { capital: true })}</strong> of this payment may be the disputed money.
                  The smaller figure is what the records prove; the larger is possible but not proven.
                </>
              }
              values={a}
              currency={t.currency}
              caption="Disputed money in this payment, by tracing method"
              extra={
                <p className="small muted">
                  How we know: <ProvenanceChip provenance={a.provenance ?? "derived"} size="sm" />
                </p>
              }
            />
          </section>
        ) : (
          <p className="small muted">The system did not work out how much of this is disputed money, because it is not on the path the money took forward.</p>
        )}
        <RecordDetails
          rows={[
            ["Payment ID", <span key="i" className="mono">{node.id}</span>],
            ["Recorded by the bank at", <TimeBoth key="p" iso={t.posted_at} />],
            ["Device", t.device_id ? <span className="mono">{t.device_id}</span> : <span className="muted">—</span>],
            ["Source system", <span key="ss" className="mono">{t.source_system}:{t.source_record_id}</span>],
            ...records,
          ]}
        />
      </div>
    );
  }

  const d = node.data;
  return (
    <div className="stack">
      <KeyValues
        rows={[
          ["File", node.label],
          ["Type", humanize(d.kind)],
          ["Analysed", d.analysis_status === "not_analysed" ? "Not analysed yet" : humanize(d.analysis_status)],
          ...(d.summary ? ([["What it says", d.summary]] as Rows) : []),
          ...how,
        ]}
      />
      {d.checks && d.checks.length > 0 && (
        <div className="table-wrap">
          <table className="mini-table">
            <caption className="sr-only">Document compared with the bank's record</caption>
            <thead>
              <tr>
                <th scope="col">Detail</th>
                <th scope="col">Document says</th>
                <th scope="col">Bank record says</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {d.checks.map((c, i) => (
                <tr key={i}>
                  <td>{humanize(c.field)}</td>
                  <td>{c.document_value ?? "—"}</td>
                  <td>{c.ledger_value ?? "—"}</td>
                  <td>{c.result === "matches" ? "Matches" : c.result === "contradicts" ? "Does not match" : c.result === "unverifiable" ? "Can't check" : humanize(c.result)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <RecordDetails
        rows={[
          ["Evidence ID", <span key="i" className="mono">{node.id}</span>],
          ["File fingerprint (SHA-256)", <span key="h" className="mono break">{d.sha256}</span>],
          ...records,
        ]}
      />
    </div>
  );
}

export function EdgeDetails({ edge, currency, nodes, onSelect }: { edge: GraphEdge; currency: string; nodes: Nodes; onSelect: (id: string) => void }) {
  const hasRange = typeof edge.data.min === "number";
  const vals = { min: edge.data.min as number, fifo: edge.data.fifo as number, pro_rata: edge.data.pro_rata as number, max: edge.data.max as number };
  return (
    <div className="stack">
      <KeyValues
        rows={[
          ["What this line shows", relationLabel(edge.type)],
          ["From", <NameLink key="f" id={edge.source} nodes={nodes} onSelect={onSelect} />],
          ["To", <NameLink key="t" id={edge.target} nodes={nodes} onSelect={onSelect} />],
          ["Time", <TimeBoth key="ti" iso={edge.time} />],
          ["How we know", <HowWeKnow key="p" provenance={edge.provenance} />],
        ]}
      />
      {edge.type === "possible_onward_funding" && (
        <p className="small">
          The later payment may have been paid for with money from the earlier one. Timing alone does not prove this.
        </p>
      )}
      {hasRange && (
        <section>
          <h4 className="plain-sub">How much disputed money this link could carry</h4>
          <MoneyFigure
            sentence={
              <>
                <strong className="num">{plainRange(spanOf(vals), currency, { capital: true })}</strong> of the disputed money.
              </>
            }
            values={vals}
            currency={currency}
            caption="Disputed money on this link, by tracing method"
          />
        </section>
      )}
      <RecordDetails
        rows={[
          ["Link ID", <span key="i" className="mono">{edge.id}</span>],
          ["Link type (system name)", <span key="ty" className="mono">{edge.type}</span>],
          ["Record IDs", <IdList key="s" ids={edge.source_ids} />],
          ...(edge.label ? ([["System note", edge.label]] as Rows) : []),
        ]}
      />
    </div>
  );
}
