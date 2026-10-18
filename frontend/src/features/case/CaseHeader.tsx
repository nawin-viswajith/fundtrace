import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useCaseAction, useMeta } from "../../api/hooks";
import { useAuth, canSupervise } from "../auth/AuthProvider";
import { useWorkspace } from "./workspace";
import { Money, Time } from "../../components/Primitives";
import { PriorityChip, SlaRemaining, StatusBadge, IdChip } from "../../components/Domain";
import { useToast } from "../../components/Toast";
import { STATUS_LABELS_FALLBACK } from "../../lib/labels";
import { StatusDialog, EscalateDialog, DecisionDialog } from "./CaseDialogs";
import { CategoryDialog } from "./CategoryDialog";
import { errorMessage } from "../../api/client";
import { humanize } from "../../lib/format";

export function CaseHeader({ compact = false }: { compact?: boolean }) {
  const { ctx, caseId } = useWorkspace();
  const [expanded, setExpanded] = useState(false);
  const showFacts = !compact || expanded;
  const { user } = useAuth();
  const meta = useMeta();
  const action = useCaseAction(caseId);
  const toast = useToast();
  const [dialog, setDialog] = useState<null | "status" | "escalate" | "decision" | "category">(null);
  const c = ctx.case;
  const t = ctx.disputed_transaction;
  const labels = meta.data?.status_labels ?? STATUS_LABELS_FALLBACK;
  const sup = canSupervise(user);
  const isMine = !!user && c.owner?.id === user.id;
  const canEdit = ctx.can_edit;
  const nonEscalate = ctx.allowed_transitions.filter((s) => s !== "escalated");
  const canEscalate = ctx.allowed_transitions.includes("escalated");

  const assign = (userId: number | null, msg: string) =>
    action.mutate(
      { type: "assign", user_id: userId },
      { onSuccess: () => toast.show(msg), onError: (e) => toast.show(errorMessage(e), "bad") },
    );

  return (
    <section className="case-header card" aria-labelledby="case-title">
      <div className="case-header-top">
        <div className="case-title-block">
          <div className="case-title-row">
            <h1 id="case-title" className="case-title">
              {c.id}
            </h1>
            <StatusBadge status={c.status} label={labels[c.status]} />
            <PriorityChip priority={c.priority} reasons={c.priority_reasons} />
          </div>
          <p className="case-category">
            {c.category_label}
            <span className="muted">
              {" "}
              · {c.category_source === "investigator" ? "category set by an investigator" : c.category_source === "ai" ? "category suggested by AI" : "category set when the dispute was raised"}
              {c.is_synthetic && <span title="Generated for the demo"> · synthetic</span>}
            </span>{" "}
            <button type="button" className="link-btn small" onClick={() => setDialog("category")}>
              Suggest a category
            </button>
          </p>
        </div>
        <div className="case-actions" role="group" aria-label="Case actions">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setDialog("status")}
            disabled={!canEdit || nonEscalate.length === 0}
          >
            Change status
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => setDialog("escalate")} disabled={!canEdit || !canEscalate}>
            Escalate
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setDialog("decision")}
            disabled={!canEdit || c.status !== "ready_for_review"}
            title={c.status !== "ready_for_review" ? "Move the case to Ready for review before recording a decision" : undefined}
          >
            Record decision
          </button>
        </div>
      </div>

      {compact && (
        <div className="case-facts-compact">
          <span className="fact-value">
            <Money minor={t.amount_minor} currency={t.currency} className="fact-amount-sm" />
            <span className={`txn-status txn-${t.status}`}>{t.status}</span>
          </span>
          <IdChip id={t.id} />
          <span className="muted">
            {t.channel} · <Time iso={t.occurred_at} />
          </span>
          <span className="muted">· {c.owner ? c.owner.full_name.replace(" (synthetic)", "") : "Unassigned"}</span>
          {ctx.sla.milestones[0] && c.status !== "resolved" && (
            <span className="muted">
              · {ctx.sla.milestones[0].label} <SlaRemaining hours={ctx.sla.milestones[0].remaining_hours} />
            </span>
          )}
          <button
            type="button"
            className="btn btn-ghost btn-sm case-facts-toggle"
            aria-expanded={expanded}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? <ChevronUp size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}
            {expanded ? "Hide details" : "Details"}
          </button>
        </div>
      )}

      {showFacts && (
      <div className="case-facts">
        <div className="fact">
          <span className="fact-label">Disputed payment</span>
          <span className="fact-value">
            <Money minor={t.amount_minor} currency={t.currency} className="fact-amount" />
            <span className={`txn-status txn-${t.status}`}>{t.status}</span>
          </span>
          <span className="fact-sub">
            <IdChip id={t.id} /> {t.channel} · ref{" "}
            {t.reference ? <span className="mono">{t.reference}</span> : <span className="warn-text">missing</span>}
          </span>
          <span className="fact-sub">
            <Time iso={t.occurred_at} />
          </span>
        </div>
        <div className="fact">
          <span className="fact-label">Handled by</span>
          <span className="fact-value">{c.owner ? c.owner.full_name.replace(" (synthetic)", "") : <span className="muted">Unassigned</span>}</span>
          <span className="fact-sub owner-actions">
            {!sup && !c.owner && (
              <button type="button" className="btn btn-secondary btn-sm" disabled={action.isPending} onClick={() => assign(user?.id ?? null, "Case claimed")}>
                Claim case
              </button>
            )}
            {!sup && isMine && (
              <button type="button" className="btn btn-ghost btn-sm" disabled={action.isPending} onClick={() => assign(null, "Case released")}>
                Release
              </button>
            )}
            {sup && (
              <label className="sr-label-wrap">
                <span className="sr-only">Assign to</span>
                <select
                  className="select select-sm"
                  value={c.owner?.id ?? ""}
                  disabled={action.isPending || !meta.data}
                  onChange={(e) => {
                    const v = e.target.value ? Number(e.target.value) : null;
                    assign(v, v ? "Case assigned" : "Case unassigned");
                  }}
                >
                  <option value="">Unassigned</option>
                  {meta.data?.assignees.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.full_name.replace(" (synthetic)", "")} ({a.role})
                    </option>
                  ))}
                </select>
              </label>
            )}
          </span>
        </div>
        <div className="fact fact-wide">
          <span className="fact-label" title={`Deadline policy ${ctx.sla.policy}`}>Deadlines (SLA)</span>
          <ul className="sla-list">
            {ctx.sla.milestones.map((m) => (
              <li key={m.key}>
                <span className="sla-name" title={m.clause_id ? `Clause ${m.clause_id}` : undefined}>
                  {m.label}
                </span>
                <Time iso={m.due_at} dateOnly />
                {c.status === "resolved" ? <span className="muted">—</span> : <SlaRemaining hours={m.remaining_hours} />}
              </li>
            ))}
          </ul>
          <span className="fact-sub muted">{ctx.sla.note}</span>
        </div>
        <div className="fact">
          <span className="fact-label">Reported by the customer</span>
          <span className="fact-value">
            <Time iso={c.reported_at} />
          </span>
          <span className="fact-sub">Customer {c.customer_id}</span>
        </div>
      </div>
      )}

      {c.decision && (
        <div className="decision-banner" role="status">
          <span>
            Decision recorded: <strong>{meta.data?.decisions[c.decision] ?? humanize(c.decision)}</strong>
            {c.decided_at && (
              <>
                {" "}
                on <Time iso={c.decided_at} />
              </>
            )}
            {c.decision_rationale && <span className="muted"> — “{c.decision_rationale}”</span>}
          </span>
        </div>
      )}
      {!canEdit && (
        <p className="inline-note">
          You can view this case but not change it.
        </p>
      )}

      <StatusDialog open={dialog === "status"} onClose={() => setDialog(null)} options={nonEscalate} labels={labels} />
      <EscalateDialog open={dialog === "escalate"} onClose={() => setDialog(null)} />
      <DecisionDialog open={dialog === "decision"} onClose={() => setDialog(null)} decisions={meta.data?.decisions} />
      {dialog === "category" && (
        <CategoryDialog caseId={c.id} currentCategory={c.category} categories={meta.data?.categories} canEdit={ctx.can_edit} onClose={() => setDialog(null)} />
      )}
    </section>
  );
}
