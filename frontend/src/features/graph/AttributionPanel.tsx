import { Info } from "lucide-react";
import type { Attribution, AttributionMethod, GraphNode, TracePath } from "../../types/api";
import { BUCKET_LABELS, ENDPOINT_BADGE, METHOD_LABELS, METHODS } from "../../lib/labels";
import { formatMoney, formatPct, humanize } from "../../lib/format";
import { Card, Note } from "../../components/Primitives";
import { IdChip } from "../../components/Domain";
import { BUCKET_ORDER, METHOD_EXPLAINED, plainRange, spanOf, summariseBuckets } from "./moneySummary";
import { cleanName } from "./plainText";

/** The four tracing methods, one per row (always behind "Show how this was worked out"). */
export function MethodTable({ values, currency, caption }: { values: Partial<Record<AttributionMethod, number>>; currency: string; caption: string }) {
  return (
    <table className="mini-table method-table method-table-v">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr>
          <th scope="col">Way of tracing the money</th>
          <th scope="col" className="ta-r">
            Amount
          </th>
        </tr>
      </thead>
      <tbody>
        {METHODS.map((m) => (
          <tr key={m}>
            <th scope="row">{METHOD_LABELS[m]}</th>
            <td className="ta-r num">{formatMoney(values[m], currency)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Short explanation of why there are four figures, for use inside a disclosure. */
export function MethodsExplained() {
  return (
    <div className="method-explained">
      <p className="small">
        Once money lands in an account it mixes with the money already there, so the records cannot say which rupees moved on. We work it out
        four ways and show the smallest and largest result in the summary.
      </p>
      <dl className="method-dl">
        {METHODS.map((m) => (
          <div key={m}>
            <dt>{METHOD_LABELS[m]}</dt>
            <dd>{METHOD_EXPLAINED[m]}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

interface Props {
  att: Attribution;
  paths: TracePath[];
  nodes: Map<string, GraphNode>;
  onSelect: (id: string) => void;
}

const PATHS_SHOWN = 5;

export function AttributionPanel({ att, paths, nodes, onSelect }: Props) {
  const cur = att.currency;
  const accounts = Object.entries(att.per_account ?? {});
  const exits = Object.entries(att.exits ?? {});
  const breakdown = att.evaluable ? summariseBuckets(att) : [];
  const accName = (id: string, fallback?: string) => {
    const n = nodes.get(id);
    return cleanName(n?.label ?? fallback) || id;
  };
  const bank = (id: string) => {
    const n = nodes.get(id);
    return n?.type === "account" ? cleanName(n.data.institution) : "";
  };

  return (
    <Card
      title="Where the disputed money is now"
      subtitle={
        <>
          Disputed payment: <strong className="num">{formatMoney(att.disputed_amount_minor, cur)}</strong>. Amounts are shown as ranges — see
          “How sure are these figures?” below.
        </>
      }
      className="money-panel"
    >
      {!att.evaluable && (
        <Note tone="warn">
          We could not work out where the money went, because some of the data needed is missing. This is not the same as finding nothing.
        </Note>
      )}

      {breakdown.length > 0 && (
        <ul className="money-breakdown" aria-label="Where the disputed money is">
          {breakdown.map((b) => (
            <li key={b.key} className={`money-row money-${b.key}`}>
              <span className="money-amount num">{plainRange(b.span, cur, { capital: true })}</span>
              <span className="money-text">
                <strong>{BUCKET_LABELS[b.key]?.label ?? humanize(b.key)}</strong>
                <span className="muted small">{BUCKET_LABELS[b.key]?.hint}</span>
              </span>
            </li>
          ))}
        </ul>
      )}

      {accounts.length > 0 && (
        <section className="money-section">
          <h4 className="plain-sub">Accounts at this bank that may still hold some of it</h4>
          <div className="table-wrap">
            <table className="table table-compact plain-table">
              <caption className="sr-only">Disputed money that may still be in each account</caption>
              <thead>
                <tr>
                  <th scope="col">Account</th>
                  <th scope="col" className="ta-r">
                    Disputed money that may be there
                  </th>
                  <th scope="col" className="ta-r">
                    Balance at end of time period
                  </th>
                </tr>
              </thead>
              <tbody>
                {accounts.map(([id, a]) => (
                  <tr key={id}>
                    <th scope="row">
                      <button type="button" className="link-btn name-btn" onClick={() => onSelect(id)} title={`Show ${id} on the map`}>
                        {accName(id, a.label)}
                      </button>
                      <span className="cell-sub mono">{id}</span>
                    </th>
                    <td className="ta-r num" data-label="Disputed money that may be there">{plainRange(spanOf(a.residual), cur, { capital: true })}</td>
                    <td className="ta-r num" data-label="Balance at end of time period">{formatMoney(a.balance_at_window_end, cur)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {exits.length > 0 && (
        <section className="money-section">
          <h4 className="plain-sub">Where it left this bank</h4>
          <div className="table-wrap">
            <table className="table table-compact plain-table">
              <caption className="sr-only">Disputed money that may have gone to each other bank</caption>
              <thead>
                <tr>
                  <th scope="col">Sent to</th>
                  <th scope="col" className="ta-r">
                    Disputed money that may have gone there
                  </th>
                </tr>
              </thead>
              <tbody>
                {exits.map(([id, v]) => (
                  <tr key={id}>
                    <th scope="row">
                      <button type="button" className="link-btn name-btn" onClick={() => onSelect(id)} title={`Show ${id} on the map`}>
                        {accName(id)}
                      </button>
                      <span className="cell-sub">
                        {bank(id) && <>{bank(id)} · </>}
                        <span className="mono">{id}</span>
                      </span>
                    </th>
                    <td className="ta-r num" data-label="Disputed money that may have gone there">{plainRange(spanOf(v), cur, { capital: true })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">This bank cannot see what happened after that. Ask the receiving bank for its records.</p>
        </section>
      )}

      {paths.length > 0 && (
        <section className="money-section">
          <h4 className="plain-sub">Routes the money took</h4>
          <PathList paths={paths.slice(0, PATHS_SHOWN)} nodes={nodes} currency={cur} onSelect={onSelect} />
          {paths.length > PATHS_SHOWN && (
            <details className="disclosure">
              <summary>Show {paths.length - PATHS_SHOWN} more routes</summary>
              <div className="disclosure-body">
                <PathList paths={paths.slice(PATHS_SHOWN)} nodes={nodes} currency={cur} onSelect={onSelect} />
              </div>
            </details>
          )}
          <p className="muted small">
            Each step is a payment in the bank's records. Being on a route does not prove a payment carried the disputed money — the amounts above
            show how much it could have carried.
          </p>
        </section>
      )}

      {att.warnings?.length > 0 && (
        <Note tone="warn">
          <ul className="plain-list">
            {att.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Note>
      )}

      <Note tone="info" icon={<Info size={15} />}>
        <p>
          <strong>How sure are these figures?</strong> They are worked out by the system from the bank's payment records. Each range runs from
          the smallest to the largest result of four ways of tracing the money; the records cannot say exactly where in that range the true amount
          is. They do not show who controlled the money or why it moved.
        </p>
      </Note>

      <details className="disclosure">
        <summary>Show how this was worked out</summary>
        <div className="disclosure-body">
          <MethodsExplained />
          <div className="table-wrap">
            <table className="table table-compact attr-table">
              <caption className="sr-only">Where the disputed money is, by tracing method</caption>
              <thead>
                <tr>
                  <th scope="col">Where the money is at the end of the time period</th>
                  {METHODS.map((m) => (
                    <th key={m} scope="col" className="ta-r" title={att.methods?.[m]}>
                      {METHOD_LABELS[m]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {BUCKET_ORDER.map((b) => {
                  const allZero = METHODS.every((m) => !att.buckets?.[m]?.[b]);
                  return (
                    <tr key={b} className={allZero ? "row-zero" : ""}>
                      <th scope="row">
                        <span>{BUCKET_LABELS[b].label}</span>
                        <span className="cell-sub">{BUCKET_LABELS[b].hint}</span>
                      </th>
                      {METHODS.map((m) => (
                        <td key={m} className="ta-r num">
                          {formatMoney(att.buckets?.[m]?.[b] ?? 0, cur)}
                        </td>
                      ))}
                    </tr>
                  );
                })}
                <tr className="row-total">
                  <th scope="row">Share of the disputed payment accounted for</th>
                  {METHODS.map((m) => (
                    <td key={m} className="ta-r num">
                      {formatPct(att.coverage?.[m])}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>

          {accounts.length > 0 && (
            <>
              <h5 className="plain-sub">Money that may still be in each account, by method</h5>
              <div className="table-wrap">
                <table className="table table-compact">
                  <thead>
                    <tr>
                      <th scope="col">Account</th>
                      {METHODS.map((m) => (
                        <th key={m} scope="col" className="ta-r">
                          {METHOD_LABELS[m]}
                        </th>
                      ))}
                      <th scope="col" className="ta-r">
                        Balance at end of time period
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {accounts.map(([id, a]) => (
                      <tr key={id}>
                        <th scope="row">
                          {accName(id, a.label)} <IdChip id={id} onClick={() => onSelect(id)} />
                        </th>
                        {METHODS.map((m) => (
                          <td key={m} className="ta-r num">
                            {formatMoney(a.residual[m], cur)}
                          </td>
                        ))}
                        <td className="ta-r num">{formatMoney(a.balance_at_window_end, cur)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {exits.length > 0 && (
            <>
              <h5 className="plain-sub">Money that may have left to each other bank, by method</h5>
              <div className="table-wrap">
                <table className="table table-compact">
                  <thead>
                    <tr>
                      <th scope="col">Sent to</th>
                      {METHODS.map((m) => (
                        <th key={m} scope="col" className="ta-r">
                          {METHOD_LABELS[m]}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {exits.map(([id, v]) => (
                      <tr key={id}>
                        <th scope="row">
                          {accName(id)} <IdChip id={id} onClick={() => onSelect(id)} />
                        </th>
                        {METHODS.map((m) => (
                          <td key={m} className="ta-r num">
                            {formatMoney(v[m], cur)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <div className="small muted method-notes">
            <p>System descriptions of the methods:</p>
            <ul className="plain-list">
              {METHODS.map((m) => (
                <li key={m}>
                  <strong>{METHOD_LABELS[m]}:</strong> {att.methods?.[m] ?? m}
                </li>
              ))}
            </ul>
            {att.caveat && <p>{att.caveat}</p>}
            {paths[0]?.note && <p>{paths[0].note}</p>}
          </div>
        </div>
      </details>
    </Card>
  );
}

/** Routes written with names: "Priya N → ₹50,000 → Rahul K → ₹20,000 → Account at Other Bank A". */
function PathList({ paths, nodes, currency, onSelect }: { paths: TracePath[]; nodes: Map<string, GraphNode>; currency: string; onSelect: (id: string) => void }) {
  const name = (id: string) => {
    const n = nodes.get(id);
    return (n && cleanName(n.label)) || id;
  };
  return (
    <ol className="route-list">
      {paths.map((p, i) => {
        const first = nodes.get(p.txn_ids[0]);
        const start = first?.type === "transaction" ? first.data.debit_account_id : null;
        return (
          <li key={i} className="route">
            <span className="route-steps">
              {start && (
                <button type="button" className="route-name" onClick={() => onSelect(start)} title={start}>
                  {name(start)}
                </button>
              )}
              {p.txn_ids.map((t) => {
                const tn = nodes.get(t);
                const to = tn?.type === "transaction" ? tn.data.credit_account_id : null;
                return (
                  <span key={t} className="route-step">
                    <span className="route-arrow" aria-hidden="true">
                      →
                    </span>
                    <span className="sr-only">sent</span>
                    <button type="button" className="route-amount num" onClick={() => onSelect(t)} title={`Payment ${t}`}>
                      {tn?.type === "transaction" ? formatMoney(tn.data.amount_minor, tn.data.currency || currency) : t}
                    </button>
                    {to && to !== p.endpoint_account_id && (
                      <>
                        <span className="route-arrow" aria-hidden="true">
                          →
                        </span>
                        <span className="sr-only">to</span>
                        <button type="button" className="route-name" onClick={() => onSelect(to)} title={to}>
                          {name(to)}
                        </button>
                      </>
                    )}
                  </span>
                );
              })}
              <span className="route-arrow" aria-hidden="true">
                →
              </span>
              <span className="sr-only">to</span>
              <button type="button" className="route-name route-end" onClick={() => onSelect(p.endpoint_account_id)} title={p.endpoint_account_id}>
                {name(p.endpoint_account_id)}
              </button>
            </span>
            <span className="chip chip-neutral chip-sm">Trail stops: {ENDPOINT_BADGE[p.endpoint] ?? humanize(p.endpoint)}</span>
          </li>
        );
      })}
    </ol>
  );
}
