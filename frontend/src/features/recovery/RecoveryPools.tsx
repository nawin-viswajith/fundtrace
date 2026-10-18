import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { AlertTriangle, Info, Lock, Scale } from "lucide-react";
import { Card, EmptyState, ErrorState, InlineError, LoadingBlock, Money, Note, Time } from "../../components/Primitives";
import { IdChip, SectionTitle } from "../../components/Domain";
import { Modal } from "../../components/Overlay";
import { useToast } from "../../components/Toast";
import { formatMoney } from "../../lib/format";
import { amountRange, displayName } from "../case/plainSummary";
import {
  useRecordSplit,
  useRecoveryHistory,
  useRecoveryPool,
  useRecoveryPools,
  type RecoveryBasis,
  type RecoveryPool,
  type RecoveryRecord,
} from "./api";

const BASIS_LABELS: Record<RecoveryBasis, string> = {
  traced: "Money traced into this account",
  disputed: "Full amount disputed",
};

/**
 * "Money recovered from shared accounts": accounts at this bank that may hold money from two or more
 * open disputes. Each case's own hold suggestion counts the same money, so here the money actually in
 * the account is shown once and split pro-rata between the cases. The split is worked out on the
 * server (exact paise); this screen only shows it. Recording a split moves no money.
 */
export function RecoveryPools({ canRecord }: { canRecord: boolean }) {
  const q = useRecoveryPools();
  const { hash } = useLocation();
  const ready = !!q.data;
  useEffect(() => {
    // the case screen links here as /network#recovery: bring the section into view once it has loaded
    if (ready && hash === "#recovery") document.getElementById("recovery")?.scrollIntoView?.({ block: "start" });
  }, [ready, hash]);
  return (
    <section className="recovery" id="recovery" aria-label="Money recovered from shared accounts">
      <SectionTitle>Money recovered from shared accounts</SectionTitle>
      <p className="page-lede">
        Some accounts received money from more than one open dispute. Each case suggests its own hold, so the same money can be counted several
        times. Here the money actually in the account is shown once and split between the cases in proportion to their claims. It is a worked
        example for review, not a decision.
      </p>
      {q.isLoading ? (
        <LoadingBlock label="Working out shared accounts" lines={4} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load shared accounts" />
      ) : !q.data ? null : q.data.pools.length === 0 ? (
        <EmptyState title="No shared accounts" icon={<Scale size={22} />}>
          No account at this bank holds money from two or more open disputes.
        </EmptyState>
      ) : (
        <div className="recovery-list">
          {q.data.pools.map((p) => (
            <PoolCard key={p.account_id} pool={p} canRecord={canRecord} />
          ))}
        </div>
      )}
    </section>
  );
}

function CaseCell({ caseId }: { caseId: string }) {
  if (caseId === "restricted")
    return (
      <span className="id-chip id-restricted" title="Assigned to another investigator">
        <Lock size={11} aria-hidden="true" /> restricted
      </span>
    );
  return (
    <Link to={`/cases/${caseId}`} className="id-chip id-chip-btn">
      {caseId}
    </Link>
  );
}

export function PoolCard({ pool, canRecord }: { pool: RecoveryPool; canRecord: boolean }) {
  const [basis, setBasis] = useState<RecoveryBasis>(pool.basis);
  const [recording, setRecording] = useState(false);
  const other = useRecoveryPool(pool.account_id, basis, basis !== pool.basis);
  const shown = basis === pool.basis ? pool : other.data;
  const name = displayName(pool.label) || pool.account_id;
  const cur = pool.currency;
  const n = pool.claims.length;

  return (
    <Card
      className="recovery-card"
      title={`${name}'s account`}
      subtitle={
        <>
          <IdChip id={pool.account_id} /> · money from {n} open cases
        </>
      }
    >
      <div className="recovery-figure">
        <span className="recovery-figure-label">Money actually in the account</span>
        <Money minor={pool.available_minor} currency={cur} className="recovery-figure-value" />
        {pool.available_source ? (
          <span className="small muted">
            Balance on record as of <Time iso={pool.available_source.as_of} /> (taken from the most recent trace among these cases, {pool.available_source.case_id}).
          </span>
        ) : (
          <span className="small muted">The balance of this account is not known from the records.</span>
        )}
      </div>

      {pool.double_counting.exceeds && (
        <Note tone="warn" icon={<AlertTriangle size={15} />}>
          The hold suggestions in these {n} cases add up to <Money minor={pool.double_counting.hold_total_minor} currency={cur} className="strong" />, but
          only <Money minor={pool.available_minor} currency={cur} className="strong" /> is in the account. The same money is being counted more than once,
          so do not hold more than <Money minor={pool.available_minor} currency={cur} /> in total.
        </Note>
      )}

      <fieldset className="recovery-basis">
        <legend className="field-label">Count each case's claim as</legend>
        <div className="seg-buttons">
          {(["traced", "disputed"] as const).map((b) => (
            <label key={b} className={`seg-btn ${basis === b ? "is-active" : ""}`}>
              <input type="radio" name={`basis-${pool.account_id}`} value={b} checked={basis === b} onChange={() => setBasis(b)} />
              {BASIS_LABELS[b]}
            </label>
          ))}
        </div>
        <p className="small muted">{pool.bases[basis]}</p>
      </fieldset>

      {other.error && basis !== pool.basis ? (
        <ErrorState error={other.error} onRetry={() => other.refetch()} title="Couldn't work out this split" />
      ) : !shown ? (
        <LoadingBlock label="Working out the split" lines={3} />
      ) : (
        <SplitTable pool={shown} />
      )}

      <div className="recovery-explain small">
        <p>
          <strong>How the split works:</strong> {pool.formula_plain}
        </p>
        <p className="muted">These figures are estimates. Things to keep in mind:</p>
        <ul className="recovery-assumptions">
          {pool.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
        <details className="disclosure">
          <summary>Show how this was worked out</summary>
          <div className="disclosure-body">
            <p>
              Method <code>{(shown ?? pool).method}</code>: <code>{(shown ?? pool).formula}</code>
            </p>
            <p>{pool.available_source?.description}</p>
            <p>
              Records used: <span className="id-list">{(shown ?? pool).input_ids.map((i) => <IdChip key={i} id={i} />)}</span>
            </p>
          </div>
        </details>
      </div>

      {pool.last_recorded && <LastRecorded rec={pool.last_recorded} />}
      <History accountId={pool.account_id} />

      {canRecord && shown && shown.available_minor !== null && (
        <div className="recovery-actions">
          <button type="button" className="btn btn-primary btn-sm" onClick={() => setRecording(true)}>
            Record this split
          </button>
          <span className="small muted">Keeps this split on file for these cases. It does not move any money.</span>
        </div>
      )}
      {recording && shown && <RecordDialog pool={shown} name={name} onClose={() => setRecording(false)} />}
    </Card>
  );
}

function SplitTable({ pool }: { pool: RecoveryPool }) {
  const cur = pool.currency;
  const total = pool.claims.reduce((s, c) => s + (c.allocated_minor ?? 0), 0);
  return (
    <>
      <div className="table-wrap">
        <table className="table table-compact recovery-table" aria-label={`How ${displayName(pool.label) || pool.account_id}'s money would be split`}>
          <thead>
            <tr>
              <th scope="col">Case</th>
              <th scope="col">Status</th>
              <th scope="col" className="ta-r">
                Amount disputed
              </th>
              <th scope="col" className="ta-r">
                May still be in this account
              </th>
              <th scope="col" className="ta-r">
                Claim used
              </th>
              <th scope="col" className="ta-r">
                Share of the money
              </th>
            </tr>
          </thead>
          <tbody>
            {pool.claims.map((c, i) => (
              <tr key={`${c.case_id}-${i}`}>
                <th scope="row">
                  <CaseCell caseId={c.case_id} />
                </th>
                <td>{c.status_label}</td>
                <td className="ta-r">
                  <Money minor={c.disputed_amount_minor} currency={cur} />
                </td>
                <td className="ta-r num">{amountRange(c.traced_min_minor, c.traced_max_minor, cur)}</td>
                <td className="ta-r">
                  <Money minor={c.eligible_minor} currency={cur} />
                </td>
                <td className="ta-r">
                  <Money minor={c.allocated_minor} currency={cur} className="strong" />
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="row-total">
              <th scope="row" colSpan={4}>
                Total
              </th>
              <td className="ta-r">
                <Money minor={pool.total_eligible_minor} currency={cur} />
              </td>
              <td className="ta-r">
                <Money minor={pool.available_minor === null ? null : total} currency={cur} />
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      {(pool.left_over_minor ?? 0) > 0 && (
        <p className="small">
          <Money minor={pool.left_over_minor} currency={cur} /> is more than all the claims together, so it is not shared out.
        </p>
      )}
    </>
  );
}

function LastRecorded({ rec }: { rec: RecoveryRecord }) {
  return (
    <Note tone="info" icon={<Info size={15} />}>
      A split was last recorded by {rec.recorded_by} on <Time iso={rec.recorded_at} /> ({BASIS_LABELS[rec.basis].toLowerCase()},{" "}
      {formatMoney(rec.available_minor, rec.currency)} in the account). Reason: “{rec.note}”. {rec.effect}
    </Note>
  );
}

function History({ accountId }: { accountId: string }) {
  const [open, setOpen] = useState(false);
  const q = useRecoveryHistory(accountId, open);
  return (
    <details className="disclosure recovery-history" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>Earlier recorded splits</summary>
      <div className="disclosure-body small">
        {q.isLoading ? (
          <LoadingBlock label="Loading" lines={2} />
        ) : q.error ? (
          <InlineError error={q.error} />
        ) : !q.data?.records.length ? (
          <p className="muted">No split has been recorded for this account yet.</p>
        ) : (
          <ul className="recovery-history-list">
            {q.data.records.map((r) => (
              <li key={r.id}>
                <Time iso={r.recorded_at} /> · {r.recorded_by} · {BASIS_LABELS[r.basis].toLowerCase()} ·{" "}
                {r.allocations.map((a) => `${a.case_id} ${formatMoney(a.allocated_minor, r.currency)}`).join(", ")}
                <span className="muted"> — “{r.note}”</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}

function RecordDialog({ pool, name, onClose }: { pool: RecoveryPool; name: string; onClose: () => void }) {
  const rec = useRecordSplit(pool.account_id);
  const toast = useToast();
  const [note, setNote] = useState("");
  const valid = note.trim().length >= 10;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    rec.mutate(
      { basis: pool.basis, note: note.trim() },
      {
        onSuccess: (out) => {
          toast.show(`Split recorded. ${out.record.effect}`);
          onClose();
        },
      },
    );
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={`Record the split of ${name}'s account`}
      description="This keeps the split below on file for each of these cases and in the audit trail. It does not move, hold or release any money."
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="recovery-record-form" className="btn btn-primary" disabled={!valid || rec.isPending}>
            {rec.isPending ? "Saving…" : "Record this split"}
          </button>
        </>
      }
    >
      <form id="recovery-record-form" onSubmit={submit}>
        <ul className="recovery-record-summary small">
          {pool.claims.map((c, i) => (
            <li key={`${c.case_id}-${i}`}>
              {c.case_id}: <Money minor={c.allocated_minor} currency={pool.currency} className="strong" /> of a{" "}
              <Money minor={c.eligible_minor} currency={pool.currency} /> claim
            </li>
          ))}
        </ul>
        <p className="small muted">Claims counted as: {BASIS_LABELS[pool.basis].toLowerCase()}.</p>
        <label className="field">
          <span className="field-label">Reason (at least 10 characters)</span>
          <textarea className="textarea" rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
        </label>
        <InlineError error={rec.error} />
      </form>
    </Modal>
  );
}
