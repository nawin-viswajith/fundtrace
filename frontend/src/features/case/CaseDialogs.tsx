import { useEffect, useState, type FormEvent } from "react";
import { Modal } from "../../components/Overlay";
import { InlineError } from "../../components/Primitives";
import { useToast } from "../../components/Toast";
import { useCaseAction } from "../../api/hooks";
import { useWorkspace } from "./workspace";
import type { CaseStatus } from "../../types/api";

function useResetOnOpen(open: boolean, reset: () => void) {
  useEffect(() => {
    if (open) reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
}

export function StatusDialog({ open, onClose, options, labels }: { open: boolean; onClose: () => void; options: CaseStatus[]; labels: Record<string, string> }) {
  const { caseId, ctx } = useWorkspace();
  const action = useCaseAction(caseId);
  const toast = useToast();
  const [to, setTo] = useState<CaseStatus | "">("");
  const [reason, setReason] = useState("");
  useResetOnOpen(open, () => {
    setTo(options[0] ?? "");
    setReason("");
    action.reset();
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!to) return;
    action.mutate(
      { type: "status", to, reason: reason.trim() || undefined },
      {
        onSuccess: () => {
          toast.show(`Status changed to ${labels[to] ?? to}`);
          onClose();
        },
      },
    );
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Change status"
      description={`Currently ${labels[ctx.case.status] ?? ctx.case.status}. Only transitions allowed from this status are listed. Resolving happens by recording a decision.`}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="status-form" className="btn btn-primary" disabled={!to || action.isPending}>
            {action.isPending ? "Saving…" : "Change status"}
          </button>
        </>
      }
    >
      <form id="status-form" onSubmit={submit}>
        <fieldset className="radio-group">
          <legend className="field-label">Move to</legend>
          {options.map((s) => (
            <label key={s} className="radio">
              <input type="radio" name="to" value={s} checked={to === s} onChange={() => setTo(s)} />
              <span>{labels[s] ?? s}</span>
            </label>
          ))}
        </fieldset>
        <label className="field">
          <span className="field-label">Reason (optional)</span>
          <textarea className="textarea" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} />
        </label>
        <InlineError error={action.error} />
      </form>
    </Modal>
  );
}

export function EscalateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { caseId } = useWorkspace();
  const action = useCaseAction(caseId);
  const toast = useToast();
  const [reason, setReason] = useState("");
  useResetOnOpen(open, () => {
    setReason("");
    action.reset();
  });
  const short = reason.trim().length < 10;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    action.mutate(
      { type: "status", to: "escalated", reason: reason.trim() },
      {
        onSuccess: () => {
          toast.show("Case escalated");
          onClose();
        },
      },
    );
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Escalate case"
      description="Escalation sends the case to a supervisor. Explain why so the reviewer has context."
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="escalate-form" className="btn btn-primary" disabled={short || action.isPending}>
            {action.isPending ? "Escalating…" : "Escalate"}
          </button>
        </>
      }
    >
      <form id="escalate-form" onSubmit={submit}>
        <label className="field">
          <span className="field-label">Reason (at least 10 characters)</span>
          <textarea className="textarea" rows={4} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} required />
          <span className={`field-hint ${short ? "" : "ok"}`}>{reason.trim().length} / 10 minimum</span>
        </label>
        <InlineError error={action.error} />
      </form>
    </Modal>
  );
}

export function DecisionDialog({ open, onClose, decisions }: { open: boolean; onClose: () => void; decisions?: Record<string, string> }) {
  const { caseId, ctx } = useWorkspace();
  const action = useCaseAction(caseId);
  const toast = useToast();
  const [decision, setDecision] = useState("");
  const [rationale, setRationale] = useState("");
  const [override, setOverride] = useState("");
  useResetOnOpen(open, () => {
    setDecision("");
    setRationale("");
    setOverride("");
    action.reset();
  });
  const report = ctx.latest_report;
  const needsOverride = !report || report.review_status === "pending";
  const opts = decisions ?? { uphold_claim: "Uphold claim", partial: "Partially uphold", decline_claim: "Decline claim", refer: "Refer / escalate" };
  const valid = !!decision && rationale.trim().length >= 20 && (!needsOverride || override.trim().length >= 10);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    action.mutate(
      { type: "decision", decision, rationale: rationale.trim(), override_reason: override.trim() || undefined },
      {
        onSuccess: (r) => {
          toast.show(`Decision recorded${r.status ? ` — case is now ${r.status.replace("_", " ")}` : ""}`);
          onClose();
        },
      },
    );
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title="Record decision"
      description="This is the investigator's decision. AI output and risk signals inform it but never make it."
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="decision-form" className="btn btn-primary" disabled={!valid || action.isPending}>
            {action.isPending ? "Recording…" : "Record decision"}
          </button>
        </>
      }
    >
      <form id="decision-form" onSubmit={submit}>
        <fieldset className="radio-group radio-grid">
          <legend className="field-label">Decision</legend>
          {Object.entries(opts).map(([k, label]) => (
            <label key={k} className={`radio radio-card ${decision === k ? "is-checked" : ""}`}>
              <input type="radio" name="decision" value={k} checked={decision === k} onChange={() => setDecision(k)} />
              <span>{label}</span>
            </label>
          ))}
        </fieldset>
        <label className="field">
          <span className="field-label">Rationale (at least 20 characters)</span>
          <textarea className="textarea" rows={4} value={rationale} onChange={(e) => setRationale(e.target.value)} maxLength={4000} />
          <span className={`field-hint ${rationale.trim().length >= 20 ? "ok" : ""}`}>{rationale.trim().length} / 20 minimum</span>
        </label>
        {needsOverride && (
          <div className="override-box">
            <p className="override-note">
              {report
                ? `The latest report (v${report.version}) has not been reviewed yet.`
                : "No investigation report exists for this case yet."}{" "}
              Review it on the AI report tab, or give an override reason.
            </p>
            <label className="field">
              <span className="field-label">Override reason (at least 10 characters)</span>
              <textarea className="textarea" rows={2} value={override} onChange={(e) => setOverride(e.target.value)} maxLength={1000} />
            </label>
          </div>
        )}
        <InlineError error={action.error} />
      </form>
    </Modal>
  );
}
