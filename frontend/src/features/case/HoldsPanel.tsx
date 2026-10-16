import { useState, type FormEvent } from "react";
import { Hand, ShieldCheck, ShieldX } from "lucide-react";
import { useWorkspace } from "./workspace";
import { useCaseAction } from "../../api/hooks";
import { Card, EmptyState, InlineError, Money, MoneyRange, Note, Time } from "../../components/Primitives";
import { Chip } from "../../components/Chip";
import { IdChip } from "../../components/Domain";
import { Modal } from "../../components/Overlay";
import { useToast } from "../../components/Toast";
import { METHOD_LABELS, METHODS } from "../../lib/labels";
import { formatMoney } from "../../lib/format";
import type { Hold, HoldableAccount } from "../../types/api";

const HOLD_TONE: Record<string, "good" | "warn" | "bad" | "neutral"> = { recommended: "warn", requested: "good", declined: "neutral" };

export function HoldsPanel() {
  const { ctx } = useWorkspace();
  const holdable = ctx.attribution.holdable ?? [];
  const holds = ctx.holds ?? [];
  const [pending, setPending] = useState<{ hold: Hold; decision: "request" | "decline" } | null>(null);
  const cur = ctx.case.currency;

  const rows: { account_id: string; candidate?: HoldableAccount; hold?: Hold }[] = [];
  for (const h of holdable) rows.push({ account_id: h.account_id, candidate: h, hold: holds.find((x) => x.account_id === h.account_id) });
  for (const h of holds) if (!rows.some((r) => r.account_id === h.account_id)) rows.push({ account_id: h.account_id, hold: h });

  return (
    <Card
      title="Hold recommendations"
      subtitle="Golden hour: visible downstream accounts that may still hold disputed funds. Only an investigator can request a hold."
    >
      {rows.length === 0 ? (
        <EmptyState title="No holdable funds visible" icon={<Hand size={22} />}>
          Attribution shows no disputed funds remaining in accounts this bank can see.
        </EmptyState>
      ) : (
        <ul className="hold-list">
          {rows.map(({ account_id, candidate, hold }) => (
            <li key={account_id} className="hold-item">
              <div className="hold-main">
                <div className="hold-title">
                  <strong>{candidate?.label ?? account_id}</strong> <IdChip id={account_id} />
                  {hold ? (
                    <Chip tone={HOLD_TONE[hold.status] ?? "neutral"} size="sm">
                      {hold.status === "requested" ? "Hold requested" : hold.status === "declined" ? "Declined" : "Recommended"}
                    </Chip>
                  ) : (
                    <Chip tone="neutral" size="sm">
                      Candidate
                    </Chip>
                  )}
                </div>
                {candidate && (
                  <p className="hold-range">
                    May still hold <MoneyRange min={candidate.min_minor} max={candidate.max_minor} currency={cur} /> of the disputed funds · balance{" "}
                    <Money minor={candidate.balance_minor} currency={cur} />
                  </p>
                )}
                {candidate && (
                  <div className="method-chips" aria-label="Residual by attribution method">
                    {METHODS.map((m) => (
                      <span key={m} className="method-chip">
                        <span className="muted">{METHOD_LABELS[m]}</span> <span className="num">{formatMoney(candidate.by_method[m], cur)}</span>
                      </span>
                    ))}
                  </div>
                )}
                {hold && (
                  <p className="small muted">
                    {hold.status === "recommended" ? "Recommended" : "Decided"} amount <Money minor={hold.amount_minor} currency={hold.currency} /> ·{" "}
                    {hold.recommended_by}
                    {typeof hold.basis === "object" && hold.basis?.method ? ` · ${hold.basis.method}` : ""}
                    {hold.decided_at && (
                      <>
                        {" "}
                        · decided <Time iso={hold.decided_at} />
                      </>
                    )}
                    {hold.decision_note && <> · “{hold.decision_note}”</>}
                  </p>
                )}
                {!hold && <p className="small muted">No recommendation recorded yet. Generating a report (AI or facts-only) records one for review.</p>}
              </div>
              {hold?.status === "recommended" && ctx.can_edit && (
                <div className="hold-actions">
                  <button type="button" className="btn btn-primary btn-sm" onClick={() => setPending({ hold, decision: "request" })}>
                    <ShieldCheck size={14} aria-hidden="true" /> Approve hold request
                  </button>
                  <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPending({ hold, decision: "decline" })}>
                    <ShieldX size={14} aria-hidden="true" /> Decline
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <Note tone="info">A hold request is a recommendation to act on recorded balances; it does not establish who controlled the funds.</Note>
      {pending && <HoldDialog hold={pending.hold} decision={pending.decision} onClose={() => setPending(null)} />}
    </Card>
  );
}

function HoldDialog({ hold, decision, onClose }: { hold: Hold; decision: "request" | "decline"; onClose: () => void }) {
  const { caseId } = useWorkspace();
  const action = useCaseAction(caseId);
  const toast = useToast();
  const [note, setNote] = useState("");
  const [amount, setAmount] = useState(String(hold.amount_minor / 100));
  const amountMinor = Math.round(Number(amount) * 100);
  const amountOk = decision === "decline" || (Number.isFinite(amountMinor) && amountMinor > 0 && amountMinor <= hold.amount_minor);
  const valid = note.trim().length >= 5 && amountOk;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    action.mutate(
      { type: "hold", hold_id: hold.id, decision, note: note.trim(), amount_minor: decision === "request" ? amountMinor : undefined },
      {
        onSuccess: () => {
          toast.show(decision === "request" ? "Hold request recorded" : "Recommendation declined");
          onClose();
        },
      },
    );
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={decision === "request" ? `Approve hold request on ${hold.account_id}` : `Decline hold on ${hold.account_id}`}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="hold-form" className="btn btn-primary" disabled={!valid || action.isPending}>
            {action.isPending ? "Saving…" : decision === "request" ? "Approve request" : "Decline"}
          </button>
        </>
      }
    >
      <form id="hold-form" onSubmit={submit}>
        {decision === "request" && (
          <label className="field">
            <span className="field-label">Hold amount (₹, up to {formatMoney(hold.amount_minor, hold.currency)})</span>
            <input className="input num" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            {!amountOk && <span className="field-hint bad">Must be positive and not exceed the traceable upper bound.</span>}
          </label>
        )}
        <label className="field">
          <span className="field-label">Note (at least 5 characters)</span>
          <textarea className="textarea" rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
        </label>
        <InlineError error={action.error} />
      </form>
    </Modal>
  );
}
