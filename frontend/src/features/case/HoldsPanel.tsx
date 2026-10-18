import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useWorkspace } from "./workspace";
import { useCaseAction } from "../../api/hooks";
import { EmptyState, InlineError, Money, Note, Time } from "../../components/Primitives";
import { Chip } from "../../components/Chip";
import { IdChip } from "../../components/Domain";
import { Modal } from "../../components/Overlay";
import { useToast } from "../../components/Toast";
import { METHODS } from "../../lib/labels";
import { formatMoney } from "../../lib/format";
import type { Hold, HoldableAccount } from "../../types/api";
import { PlainPanel } from "./PlainPanel";
import { amountRange, displayName } from "./plainSummary";
import { useSharedAccounts } from "../recovery/api";

// For money still *in* an account the bounds flip: spending clean money first ("min" for onward transfers)
// leaves the most disputed money behind. So residuals are labelled by convention, not as lower/upper bound.
const RESIDUAL_METHOD_LABELS: Record<(typeof METHODS)[number], string> = {
  min: "Clean money out first",
  fifo: "First in, first out (FIFO)",
  pro_rata: "Proportional mix (pro-rata)",
  max: "Disputed money out first",
};
const RESIDUAL_METHOD_HELP: Record<(typeof METHODS)[number], string> = {
  min: "assumes the account holder's own money left first, so the most of the customer's money is still here.",
  fifo: "money leaves in the order it arrived.",
  pro_rata: "every payment out carries the same mix as the account balance.",
  max: "assumes the customer's money left first, so the least of it is still here.",
};

const HOLD_STATUS: Record<string, { label: string; tone: "good" | "warn" | "bad" | "neutral" }> = {
  recommended: { label: "Waiting for a decision", tone: "warn" },
  requested: { label: "Hold requested", tone: "good" },
  declined: { label: "Declined", tone: "neutral" },
};

interface Row {
  account_id: string;
  candidate?: HoldableAccount;
  hold?: Hold;
}

function holdName(r: Row): string {
  return displayName(r.candidate?.label) || r.account_id;
}

export function HoldsPanel() {
  const { ctx, caseId } = useWorkspace();
  const shared = useSharedAccounts(caseId).data?.accounts ?? [];
  const holdable = ctx.attribution.holdable ?? [];
  const holds = ctx.holds ?? [];
  const [pending, setPending] = useState<{ hold: Hold; name: string; decision: "request" | "decline" } | null>(null);
  const cur = ctx.case.currency;

  const rows: Row[] = [];
  for (const h of holdable) rows.push({ account_id: h.account_id, candidate: h, hold: holds.find((x) => x.account_id === h.account_id) });
  for (const h of holds) if (!rows.some((r) => r.account_id === h.account_id)) rows.push({ account_id: h.account_id, hold: h });
  const waiting = rows.filter((r) => r.hold?.status === "recommended").length;

  return (
    <PlainPanel
      id="case-holds"
      title="Money that could be held"
      subtitle={
        <>
          Money may still be recoverable. These accounts at this bank may still have some of the customer's money. The system suggests a hold; an
          investigator must approve or decline each one.
          {waiting > 0 && (
            <>
              {" "}
              <strong>{waiting === 1 ? "1 suggestion is" : `${waiting} suggestions are`} waiting for a decision.</strong>
            </>
          )}
        </>
      }
    >
      {rows.length === 0 ? (
        <EmptyState title="No money left to hold">
          The trace shows none of the customer's money still sitting in accounts at this bank.
        </EmptyState>
      ) : (
        <ul className="hold-list plain-holds">
          {rows.map((r) => {
            const { account_id, candidate, hold } = r;
            const name = holdName(r);
            const st = hold ? HOLD_STATUS[hold.status] ?? { label: hold.status, tone: "neutral" as const } : { label: "No suggestion yet", tone: "neutral" as const };
            return (
              <li key={account_id} className="hold-item">
                <div className="hold-main">
                  <p className="hold-sentence">
                    {candidate ? (
                      <>
                        <strong>{name}</strong> may still hold <strong className="num">{amountRange(candidate.min_minor, candidate.max_minor, cur)}</strong> of
                        the customer's money.
                      </>
                    ) : (
                      <>
                        A hold was suggested on <strong>{name}</strong>'s account.
                      </>
                    )}{" "}
                    {hold && hold.status === "recommended" && (
                      <>
                        Suggested hold: <strong className="num">{formatMoney(hold.amount_minor, hold.currency)}</strong>.
                      </>
                    )}
                  </p>
                  <div className="hold-meta small">
                    <Chip tone={st.tone} size="sm">
                      {st.label}
                    </Chip>
                    {candidate && (
                      <span className="muted">
                        Account balance <Money minor={candidate.balance_minor} currency={cur} />
                      </span>
                    )}
                    <span className="muted">
                      Account <IdChip id={account_id} />
                    </span>
                  </div>
                  {hold && hold.status !== "declined" && <SharedNote others={shared.find((x) => x.account_id === account_id)?.other_cases} />}
                  {hold && hold.status !== "recommended" && (
                    <p className="small">
                      {hold.status === "requested" ? "Hold requested for " : "Suggested hold of "}
                      <Money minor={hold.amount_minor} currency={hold.currency} />
                      {hold.status === "declined" && " was declined"}
                      {hold.decided_at && (
                        <>
                          {" "}
                          on <Time iso={hold.decided_at} />
                        </>
                      )}
                      .{hold.decision_note && <span className="muted"> Reason: “{hold.decision_note}”</span>}
                    </p>
                  )}
                  {!hold && (
                    <p className="small muted">
                      No hold has been suggested yet. Running the AI investigation (or the records-only report) adds a suggestion here for you to
                      review.
                    </p>
                  )}
                  <details className="disclosure">
                    <summary>Show how this was worked out</summary>
                    <div className="disclosure-body small">
                      {candidate ? (
                        <>
                          <p>
                            The customer's money mixed with other money in this account, so the records can't say exactly how much of it is still
                            there. The system counts it four ways:
                          </p>
                          <table className="mini-table hold-method-table">
                            <tbody>
                              {METHODS.map((m) => (
                                <tr key={m}>
                                  <th scope="row">
                                    {RESIDUAL_METHOD_LABELS[m]}
                                    <span className="muted hold-method-help"> — {RESIDUAL_METHOD_HELP[m]}</span>
                                  </th>
                                  <td className="ta-r num">{formatMoney(candidate.by_method[m], cur)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                          <p>
                            The suggested hold uses the highest of these, and is never more than the account balance (
                            <Money minor={candidate.balance_minor} currency={cur} />
                            ).
                          </p>
                        </>
                      ) : (
                        <p>This account no longer shows any of the customer's money in the latest trace.</p>
                      )}
                      {hold && (
                        <p className="muted">
                          Suggested by {hold.recommended_by}
                          {typeof hold.basis === "object" && hold.basis?.method ? ` · basis: ${hold.basis.method}` : ""} · <Time iso={hold.created_at} />
                        </p>
                      )}
                    </div>
                  </details>
                </div>
                {hold?.status === "recommended" && ctx.can_edit && (
                  <div className="hold-actions">
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      aria-label={`Approve hold on ${name}'s account`}
                      onClick={() => setPending({ hold, name, decision: "request" })}
                    >
                      Approve hold
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      aria-label={`Decline hold on ${name}'s account`}
                      onClick={() => setPending({ hold, name, decision: "decline" })}
                    >
                      Decline
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      <Note tone="info">Approving asks for a hold on the recorded balance. It does not prove who controlled the money.</Note>
      {pending && <HoldDialog hold={pending.hold} name={pending.name} decision={pending.decision} onClose={() => setPending(null)} />}
    </PlainPanel>
  );
}

/** One plain line when other open cases also suggest holding this account's money (the same money, counted twice). */
function SharedNote({ others }: { others?: string[] }) {
  if (!others?.length) return null;
  const named = others.filter((c) => c !== "restricted");
  const hidden = others.length - named.length;
  const parts = [...named, ...(hidden ? [hidden === 1 ? "1 case you can't open" : `${hidden} cases you can't open`] : [])];
  return (
    <p className="small recovery-hint">
      This account's money is also claimed in {parts.join(", ")} — <Link to="/network#recovery">see how it would be split</Link>.
    </p>
  );
}

function HoldDialog({ hold, name, decision, onClose }: { hold: Hold; name: string; decision: "request" | "decline"; onClose: () => void }) {
  const { caseId } = useWorkspace();
  const action = useCaseAction(caseId);
  const toast = useToast();
  const [note, setNote] = useState("");
  const [amount, setAmount] = useState(String(hold.amount_minor / 100));
  const amountMinor = Math.round(Number(amount) * 100);
  const amountOk = decision === "decline" || (Number.isFinite(amountMinor) && amountMinor > 0 && amountMinor <= hold.amount_minor);
  const valid = note.trim().length >= 5 && amountOk;
  const max = formatMoney(hold.amount_minor, hold.currency);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    action.mutate(
      { type: "hold", hold_id: hold.id, decision, note: note.trim(), amount_minor: decision === "request" ? amountMinor : undefined },
      {
        onSuccess: () => {
          toast.show(decision === "request" ? "Hold request recorded" : "Suggestion declined");
          onClose();
        },
      },
    );
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={decision === "request" ? `Approve a hold on ${name}'s account` : `Decline the hold on ${name}'s account`}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="hold-form" className="btn btn-primary" disabled={!valid || action.isPending}>
            {action.isPending ? "Saving…" : decision === "request" ? "Approve hold" : "Decline"}
          </button>
        </>
      }
    >
      <form id="hold-form" onSubmit={submit}>
        <p className="small muted">
          Account <IdChip id={hold.account_id} />
        </p>
        {decision === "request" && (
          <label className="field">
            <span className="field-label">Amount to hold (₹, up to {max})</span>
            <input className="input num" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            {!amountOk && <span className="field-hint bad">Enter an amount above ₹0 and no more than {max}.</span>}
          </label>
        )}
        <label className="field">
          <span className="field-label">Reason (at least 5 characters)</span>
          <textarea className="textarea" rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
        </label>
        <InlineError error={action.error} />
      </form>
    </Modal>
  );
}
