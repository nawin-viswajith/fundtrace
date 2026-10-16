import { Info } from "lucide-react";
import type { Attribution, AttributionMethod, TracePath } from "../../types/api";
import { BUCKET_LABELS, ENDPOINT_BADGE, METHOD_LABELS, METHODS } from "../../lib/labels";
import { formatMoney, formatPct, humanize } from "../../lib/format";
import { Card, Note } from "../../components/Primitives";
import { IdChip } from "../../components/Domain";

export function MethodTable({ values, currency, caption }: { values: Partial<Record<AttributionMethod, number>>; currency: string; caption: string }) {
  return (
    <table className="mini-table method-table">
      <caption className="sr-only">{caption}</caption>
      <thead>
        <tr>
          {METHODS.map((m) => (
            <th key={m} scope="col" className="ta-r">
              {METHOD_LABELS[m]}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        <tr>
          {METHODS.map((m) => (
            <td key={m} className="ta-r num">
              {formatMoney(values[m], currency)}
            </td>
          ))}
        </tr>
      </tbody>
    </table>
  );
}

const BUCKET_ORDER = [
  "residual_in_visible_accounts",
  "left_visibility",
  "reached_merchant_or_hub",
  "returned_to_payer",
  "beyond_trace_limits",
  "unaccounted",
] as const;

export function AttributionPanel({ att, paths, onSelect }: { att: Attribution; paths: TracePath[]; onSelect: (id: string) => void }) {
  const cur = att.currency;
  const accounts = Object.entries(att.per_account ?? {});
  return (
    <Card
      title="Where the disputed funds can be traced"
      subtitle={
        <>
          Disputed amount <strong className="num">{formatMoney(att.disputed_amount_minor, cur)}</strong> · balance arithmetic over recorded
          transactions, four methods side by side
        </>
      }
    >
      {!att.evaluable && <Note tone="warn">Attribution is not evaluable for this trail — the data it needs is missing. This is not a negative finding.</Note>}
      <div className="table-wrap">
        <table className="table table-compact attr-table">
          <caption className="sr-only">Attribution buckets by method</caption>
          <thead>
            <tr>
              <th scope="col">Position at window end</th>
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
              <th scope="row">Coverage</th>
              {METHODS.map((m) => (
                <td key={m} className="ta-r num">
                  {formatPct(att.coverage?.[m])}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <p className="method-legend">
        {METHODS.map((m) => (
          <span key={m}>
            <strong>{METHOD_LABELS[m]}:</strong> {att.methods?.[m] ?? m}
          </span>
        ))}
      </p>

      {accounts.length > 0 && (
        <>
          <h4 className="h-sub">Residual in visible accounts</h4>
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
                    Balance at window end
                  </th>
                </tr>
              </thead>
              <tbody>
                {accounts.map(([id, a]) => (
                  <tr key={id}>
                    <th scope="row">
                      <IdChip id={id} onClick={() => onSelect(id)} /> <span className="cell-sub">{a.label}</span>
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

      {paths.length > 0 && (
        <>
          <h4 className="h-sub">Trail paths to endpoints</h4>
          <ul className="path-list">
            {paths.map((p, i) => (
              <li key={i}>
                <span className="path-hops">
                  {p.txn_ids.map((t, j) => (
                    <span key={t}>
                      {j > 0 && <span className="path-arrow" aria-hidden="true">→</span>}
                      <IdChip id={t} onClick={() => onSelect(t)} />
                    </span>
                  ))}
                  <span className="path-arrow" aria-hidden="true">→</span>
                  <IdChip id={p.endpoint_account_id} onClick={() => onSelect(p.endpoint_account_id)} />
                </span>
                <span className="chip chip-neutral chip-sm">{ENDPOINT_BADGE[p.endpoint] ?? humanize(p.endpoint)}</span>
              </li>
            ))}
          </ul>
          <p className="muted small">{paths[0].note}</p>
        </>
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
        {att.caveat}
      </Note>
    </Card>
  );
}
