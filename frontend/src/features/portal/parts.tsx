import { useRef, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Bot, ClipboardCheck, FileText, ImageIcon, Pencil, Upload, UserRound, X } from "lucide-react";
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

export interface SummaryItem {
  label: string;
  value: ReactNode;
  onChange?: () => void;
}

/** "Check your dispute": the payment, the customer's answers and their own words, each with a way to change it. */
export function DisputeSummaryCard({
  payment,
  onChangePayment,
  items,
  description,
  onChangeDescription,
  title = "Check your dispute",
  subtitle = "Nothing has been sent yet.",
  children,
}: {
  title?: string;
  subtitle?: string;
  children?: ReactNode;
  payment: PortalPayment;
  onChangePayment?: () => void;
  items: SummaryItem[];
  description: string;
  onChangeDescription?: () => void;
}) {
  return (
    <section className="sum-card" aria-labelledby="sum-title">
      <header className="sum-head">
        <span className="sum-head-icon" aria-hidden="true">
          <ClipboardCheck size={20} />
        </span>
        <span>
          <strong id="sum-title">{title}</strong>
          <span className="sum-head-sub">{subtitle}</span>
        </span>
      </header>
      <div className="sum-pay">
        <span className="sum-label">Payment you are disputing</span>
        <span className="sum-pay-row">
          <span className="sum-amount num">{payment.amount}</span>
          <span className="sum-pay-main">
            <strong>To {payment.paid_to}</strong>
            <span className="small muted">
              {payment.channel} · <Time iso={payment.occurred_at} />
              {payment.reference ? <> · Ref {payment.reference}</> : null}
            </span>
          </span>
          {onChangePayment && <ChangeLink label="the payment" onClick={onChangePayment} />}
        </span>
      </div>
      <dl className="sum-grid">
        {items.map((it) => (
          <div key={it.label} className="sum-tile">
            <dt className="sum-label">{it.label}</dt>
            <dd>{it.value}</dd>
            {it.onChange && <ChangeLink label={it.label.toLowerCase()} onClick={it.onChange} />}
          </div>
        ))}
      </dl>
      <div className="sum-desc">
        <span className="sum-label">In your words</span>
        <blockquote className="review-text">{description}</blockquote>
        {onChangeDescription && <ChangeLink label="your description" onClick={onChangeDescription} />}
      </div>
      {children}
    </section>
  );
}

function ChangeLink({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" className="sum-change" onClick={onClick} aria-label={`Change ${label}`}>
      <Pencil size={14} aria-hidden="true" /> Change
    </button>
  );
}

/** What a customer's file is, in their words (keys match the bank's evidence checklist). */
export const PROOF_KINDS: [string, string][] = [
  ["customer_evidence", "Receipt, screenshot or bank SMS"],
  ["cyber_complaint_ack", "Cyber-crime complaint acknowledgement"],
  ["communication_trail", "Messages or call details from the other person"],
  ["merchant_response", "Order details or messages with the seller"],
];
export const PROOF_ACCEPT = ".png,.jpg,.jpeg,.pdf,.txt,image/png,image/jpeg,application/pdf,text/plain";
const PROOF_MAX_FILES = 5;
const PROOF_MAX_BYTES = 5 * 1024 * 1024;

export interface PendingProof {
  id: string;
  file: File;
  kind: string;
}

function sizeLabel(n: number): string {
  return n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Files chosen before the dispute exists; they are sent right after it is raised. */
export function ProofPicker({ files, onChange }: { files: PendingProof[]; onChange: (next: PendingProof[]) => void }) {
  const ref = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const add = (list: FileList | null) => {
    if (!list) return;
    const next = [...files];
    let msg: string | null = null;
    for (const f of Array.from(list)) {
      if (next.length >= PROOF_MAX_FILES) msg = `You can add up to ${PROOF_MAX_FILES} files.`;
      else if (f.size > PROOF_MAX_BYTES) msg = `"${f.name}" is larger than 5 MB.`;
      else if (!/\.(png|jpe?g|pdf|txt)$/i.test(f.name)) msg = `"${f.name}" is not a photo, PDF or text file.`;
      else next.push({ id: `${f.name}-${f.size}-${f.lastModified}-${next.length}`, file: f, kind: "customer_evidence" });
    }
    setProblem(msg);
    onChange(next);
  };
  return (
    <div className="proof">
      <button type="button" className="proof-drop" onClick={() => ref.current?.click()}>
        <span className="proof-drop-icon" aria-hidden="true">
          <Upload size={22} />
        </span>
        <span>
          <strong>Add a photo, PDF or text file</strong>
          <span className="small muted">A screenshot of the payment, the bank SMS, a receipt or your complaint. Up to 5 files, 5 MB each.</span>
        </span>
      </button>
      <input ref={ref} type="file" multiple className="sr-only" accept={PROOF_ACCEPT} aria-label="Add files" onChange={(e) => (add(e.target.files), (e.target.value = ""))} />
      {problem && (
        <p className="inline-error" role="alert">
          {problem}
        </p>
      )}
      {files.length > 0 && (
        <ul className="proof-list" aria-label="Files to send">
          {files.map((p) => (
            <li key={p.id} className="proof-item">
              <span className="proof-file-icon" aria-hidden="true">
                {/\.pdf$/i.test(p.file.name) ? <FileText size={18} /> : /\.txt$/i.test(p.file.name) ? <FileText size={18} /> : <ImageIcon size={18} />}
              </span>
              <span className="proof-file">
                <strong>{p.file.name}</strong>
                <span className="small muted">{sizeLabel(p.file.size)}</span>
              </span>
              <label className="proof-kind">
                <span className="sr-only">What is {p.file.name}?</span>
                <select className="select" value={p.kind} onChange={(e) => onChange(files.map((x) => (x.id === p.id ? { ...x, kind: e.target.value } : x)))}>
                  {PROOF_KINDS.map(([k, l]) => (
                    <option key={k} value={k}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" className="icon-btn" aria-label={`Remove ${p.file.name}`} onClick={() => onChange(files.filter((x) => x.id !== p.id))}>
                <X size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Send the chosen files to a newly raised dispute; returns how many could not be sent. */
export async function sendProof(caseId: string, files: PendingProof[], upload: (id: string, f: File, kind: string) => Promise<unknown>): Promise<number> {
  let failed = 0;
  for (const p of files) {
    try {
      await upload(caseId, p.file, p.kind);
    } catch {
      failed += 1;
    }
  }
  return failed;
}

/** Square avatars: the bank's assistant, or the customer's initial. */
export function ChatAvatar({ who, name }: { who: "bot" | "me"; name?: string }) {
  return who === "bot" ? (
    <span className="pavatar pavatar-bot" aria-hidden="true">
      <Bot size={18} />
    </span>
  ) : (
    <span className="pavatar pavatar-me" aria-hidden="true">
      {(name ?? "You").trim().charAt(0).toUpperCase() || <UserRound size={16} />}
    </span>
  );
}
