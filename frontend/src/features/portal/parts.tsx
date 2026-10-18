import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { LoadingBlock, Time } from "../../components/Primitives";
import type { PortalPayment } from "../../types/api";

/** Customer-only pages: staff are sent to the bank view, signed-out visitors to sign in. */
export function RequireCustomer({ children }: { children: ReactNode }) {
  const { user, status } = useAuth();
  const loc = useLocation();
  if (status === "loading")
    return (
      <div className="boot">
        <LoadingBlock label="Checking session" lines={3} />
      </div>
    );
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (user.role !== "customer") return <Navigate to="/overview" replace />;
  return <>{children}</>;
}

/** One payment from the customer's account, as a selectable card or a plain summary. */
export function PaymentCard({
  p,
  selected,
  onSelect,
  disabledNote,
}: {
  p: PortalPayment;
  selected?: boolean;
  onSelect?: () => void;
  disabledNote?: string;
}) {
  const body = (
    <>
      <span className="pay-amount num">{p.amount}</span>
      <span className="pay-main">
        <span className="pay-to">To {p.paid_to}</span>
        <span className="pay-meta">
          {p.channel} · <Time iso={p.occurred_at} />
          {p.reference ? <> · Ref {p.reference}</> : null}
          {p.paid_to_bank ? <> · {p.paid_to_bank.replace(/\s*\(synthetic\)\s*$/i, "")}</> : null}
        </span>
        {disabledNote && <span className="pay-note">{disabledNote}</span>}
      </span>
      {p.status !== "posted" && <span className="pay-status">{p.status === "pending" ? "Pending" : p.status === "failed" ? "Failed" : "Reversed"}</span>}
    </>
  );
  if (!onSelect) return <div className="pay-card">{body}</div>;
  return (
    <button
      type="button"
      className={`pay-card pay-card-btn ${selected ? "is-selected" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
      disabled={!!disabledNote}
    >
      {body}
    </button>
  );
}

/** Received → Being investigated → Final review → Decided, with the current step marked. */
export function StatusSteps({ steps, step, label }: { steps: string[]; step: number; label: string }) {
  return (
    <ol className="status-steps" aria-label={`Status: ${label}`}>
      {steps.map((s, i) => {
        const n = i + 1;
        const state = n < step ? "done" : n === step ? "current" : "todo";
        return (
          <li key={s} className={`status-step is-${state}`} aria-current={state === "current" ? "step" : undefined}>
            <span className="status-dot" aria-hidden="true">
              {state === "done" ? "✓" : n}
            </span>
            <span className="status-label">{n === step ? label : s}</span>
          </li>
        );
      })}
    </ol>
  );
}

export function firstName(name: string): string {
  return name.split(" ")[0] ?? name;
}
