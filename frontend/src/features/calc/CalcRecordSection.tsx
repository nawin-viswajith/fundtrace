/* "How these figures were calculated": the forensic calculation record in plain words.

   Bank staff need three answers here, without reading JSON: which named methods produced the
   figures (and which version of them), whether the arithmetic passed its checks, and whether
   someone else could get the same result. Every check shows its outcome as words and an icon,
   never colour alone. */

import { CircleCheck, CircleMinus, CircleX, Download, RefreshCw, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import type { Attribution } from "../../types/api";
import { errorMessage } from "../../api/client";
import { formatIST, formatMoney } from "../../lib/format";
import { Note, Spinner } from "../../components/Primitives";
import { useDownloadCalc, useVerifyCalc, type AmountRange, type CalcParams, type CalcRecord, type CheckStatus } from "./api";

export const CHECK_STATUS_TEXT: Record<CheckStatus, string> = {
  pass: "Passed",
  warn: "Check this",
  fail: "Failed",
  not_applicable: "Not applicable",
};

const STATUS_ICON: Record<CheckStatus, ReactNode> = {
  pass: <CircleCheck size={15} />,
  warn: <TriangleAlert size={15} />,
  fail: <CircleX size={15} />,
  not_applicable: <CircleMinus size={15} />,
};

export function StatusTag({ status }: { status: CheckStatus }) {
  return (
    <span className={`calc-status calc-status-${status}`}>
      <span aria-hidden="true">{STATUS_ICON[status]}</span>
      {CHECK_STATUS_TEXT[status]}
    </span>
  );
}

/** §7.6: when the bank's systems disagree on a payment's amount, show the range and which amount the figures use. */
export function SourceRangeNote({ ranges }: { ranges: AmountRange[] }) {
  const shown = ranges.filter((r) => r.role !== "other_activity");
  if (!shown.length) return null;
  return (
    <div className="calc-range-note" role="note">
      <TriangleAlert size={15} aria-hidden="true" />
      <div>
        {shown.map((r) => (
          <p key={r.txn_id}>
            <strong>
              {r.role === "disputed" ? "The bank's systems disagree on this payment" : `The bank's systems disagree on payment ${r.txn_id}`}:{" "}
              <span className="num">
                {formatMoney(r.min_minor, r.currency)}–{formatMoney(r.max_minor, r.currency)}
              </span>
              .
            </strong>{" "}
            Figures below use the {r.used_system_label} amount <span className="num">{formatMoney(r.used_minor, r.currency)}</span>, the record the
            ledger keeps as the main one.
            <span className="calc-range-who">
              {r.reported.map((s) => (
                <span key={`${s.system}:${s.record_id}`}>
                  {s.system_label}: <span className="num">{formatMoney(s.amount_minor, r.currency)}</span>{" "}
                  <span className="mono muted">({s.record_id})</span>
                </span>
              ))}
            </span>
          </p>
        ))}
      </div>
    </div>
  );
}

/** True when the record's figures are the ones shown in the money panel (same search settings). */
export function sameFigures(rec: CalcRecord, att: Attribution): boolean {
  if (rec.outputs.disputed_amount_minor !== att.disputed_amount_minor) return false;
  return rec.methods.every((m) => {
    const a = att.buckets?.[m.id] ?? {};
    const b = rec.outputs.buckets?.[m.id] ?? {};
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    return [...keys].every((k) => (a as Record<string, number | null>)[k] === (b as Record<string, number | null>)[k]);
  });
}

interface Props {
  caseId: string;
  params: CalcParams;
  att: Attribution;
  record: CalcRecord | undefined;
  loading: boolean;
  error: unknown;
}

export function CalcRecordSection({ caseId, params, att, record, loading, error }: Props) {
  const verify = useVerifyCalc(caseId, params);
  const download = useDownloadCalc(caseId, params);

  const summary = record?.checks_summary;
  const summaryText = summary
    ? summary.fail
      ? `${summary.fail} check${summary.fail === 1 ? "" : "s"} failed`
      : summary.warn
        ? `${summary.warn} check${summary.warn === 1 ? "" : "s"} to look at`
        : "all checks passed"
    : null;

  return (
    <details className="disclosure calc-record">
      <summary>
        How these figures were calculated
        {summaryText && <span className="calc-summary-hint"> · {summaryText}</span>}
      </summary>
      <div className="disclosure-body">
        {loading && !record && <Spinner label="Loading the calculation record" />}
        {error != null && !record && <Note tone="bad">Could not load the calculation record: {errorMessage(error)}</Note>}
        {record && (
          <>
            <p className="small">
              These figures come from fixed, tested arithmetic on the bank's records, not from AI. This record lists the methods, the exact records
              used and checks on the arithmetic, so anyone can work the figures out again and get the same result.
            </p>
            {!sameFigures(record, att) && (
              <Note tone="warn">
                This record uses the search settings{" "}
                {record.inputs.trace_parameters.depth} steps and {record.inputs.trace_parameters.window_hours} hours. The figures above use different
                settings, so they may not match. Reset the map settings to compare like with like.
              </Note>
            )}

            <h5 className="plain-sub">Methods used</h5>
            <ul className="calc-methods">
              {record.methods.map((m) => (
                <li key={m.id}>
                  <strong>{m.name}</strong> <span className="muted small">(version {m.version})</span>
                  <span className="cell-sub">{m.definition}</span>
                </li>
              ))}
            </ul>
            <p className="muted small">
              Calculation version {record.versions.calc_version} · attribution rules version {record.versions.attribution_version}
            </p>

            <h5 className="plain-sub">Checks on the arithmetic</h5>
            <ul className="calc-checks" aria-label="Checks on the arithmetic">
              {record.checks.map((c) => (
                <li key={c.id} className={`calc-check calc-check-${c.status}`}>
                  <div className="calc-check-head">
                    <StatusTag status={c.status} />
                    <strong>{c.name}</strong>
                  </div>
                  <p className="small">{c.detail}</p>
                  {c.items.some((i) => i.status !== "pass") && (
                    <ul className="calc-check-items">
                      {c.items
                        .filter((i) => i.status !== "pass")
                        .map((i, n) => (
                          <li key={n}>
                            <span className="calc-item-status">{CHECK_STATUS_TEXT[i.status]}:</span> {i.text}
                          </li>
                        ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>

            <details className="disclosure calc-inner">
              <summary>Assumptions and records used</summary>
              <div className="disclosure-body">
                <ul className="plain-list small">
                  {record.assumptions.map((a) => (
                    <li key={a.id}>{a.text}</li>
                  ))}
                </ul>
                <p className="small">
                  {record.inputs.transactions.length} payment record{record.inputs.transactions.length === 1 ? "" : "s"} read (
                  {record.inputs.transactions.filter((t) => t.treatment !== "used").length} left out as failed or reversed), opening balances for{" "}
                  {record.inputs.opening_balances.length} account{record.inputs.opening_balances.length === 1 ? "" : "s"}. Search: up to{" "}
                  {record.inputs.trace_parameters.depth} steps and {record.inputs.trace_parameters.window_hours} hours from{" "}
                  {formatIST(record.inputs.trace_parameters.window_start)}.
                </p>
                <p className="muted small">
                  {record.kinds.inputs} {record.kinds.outputs} {record.kinds.conclusions}
                </p>
              </div>
            </details>

            <div className="calc-fingerprint">
              <span className="small">Record fingerprint ({record.inputs.fingerprint.algorithm})</span>
              <code className="mono" data-testid="calc-fingerprint">
                {record.inputs.fingerprint.value}
              </code>
              <span className="muted small">{record.inputs.fingerprint.covers}</span>
            </div>

            <div className="calc-actions">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => verify.mutate(record.inputs.fingerprint.value)}
                disabled={verify.isPending}
              >
                <RefreshCw size={14} aria-hidden="true" />
                {verify.isPending ? "Checking…" : "Check it gives the same result"}
              </button>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => download.mutate()} disabled={download.isPending}>
                <Download size={14} aria-hidden="true" />
                {download.isPending ? "Preparing…" : "Download calculation record (JSON)"}
              </button>
            </div>
            <div aria-live="polite">
              {verify.data &&
                (verify.data.matches ? (
                  <p className="calc-verify calc-verify-pass">
                    <StatusTag status="pass" /> Same result. Worked out again from the bank's records, and again from this record alone, it gives the
                    same fingerprint and the same figures (checked {formatIST(verify.data.checked_at)}).
                  </p>
                ) : (
                  <div className="calc-verify calc-verify-fail">
                    <p>
                      <StatusTag status="fail" /> Different result. The figures could not be reproduced exactly:
                    </p>
                    <ul className="plain-list small">
                      {verify.data.differences.map((d, i) => (
                        <li key={i}>{d}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              {verify.error != null && <Note tone="bad">Could not run the check: {errorMessage(verify.error)}</Note>}
              {download.isSuccess && <p className="muted small">Downloaded. The download is recorded in the case audit trail.</p>}
              {download.error != null && <Note tone="bad">Could not download: {errorMessage(download.error)}</Note>}
            </div>
          </>
        )}
      </div>
    </details>
  );
}
