import { useState, type FormEvent } from "react";
import { Link2, ShieldAlert, ShieldCheck, StickyNote } from "lucide-react";
import { useAudit, useCaseAction, useMeta } from "../../api/hooks";
import { useWorkspace } from "../case/workspace";
import { Card, EmptyState, ErrorState, InlineError, LoadingBlock, Money, Skeleton, Time } from "../../components/Primitives";
import { Chip } from "../../components/Chip";
import { IdChip } from "../../components/Domain";
import { useToast } from "../../components/Toast";
import { formatUTC, humanize, shortHash } from "../../lib/format";

export function summarizeDetails(d: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(d)) {
    if (v === null || v === undefined || v === "") continue;
    let s: string;
    if (typeof v === "object") s = Array.isArray(v) ? v.join(", ") : JSON.stringify(v);
    else s = String(v);
    if (/sha256|hash/.test(k) && s.length > 16) s = s.slice(0, 12) + "…";
    if (s.length > 80) s = s.slice(0, 77) + "…";
    parts.push(`${humanize(k).toLowerCase()}: ${s}`);
  }
  return parts.join(" · ");
}

export function ActionsAuditTab() {
  const { caseId, ctx } = useWorkspace();
  const meta = useMeta();
  const audit = useAudit(caseId);
  const action = useCaseAction(caseId);
  const toast = useToast();
  const [note, setNote] = useState("");
  const c = ctx.case;
  const decided = ctx.holds.filter((h) => h.status !== "recommended");

  const addNote = (e: FormEvent) => {
    e.preventDefault();
    if (note.trim().length < 2) return;
    action.mutate(
      { type: "note", body: note.trim() },
      {
        onSuccess: () => {
          setNote("");
          toast.show("Note added");
        },
      },
    );
  };

  return (
    <div className="stack-lg">
      <div className="two-col">
        <Card title="Notes" subtitle="Investigator notes are untrusted text: they are fenced as data if the AI reads them.">
          {ctx.notes.length === 0 ? (
            <p className="muted small">No notes yet.</p>
          ) : (
            <ul className="note-list">
              {ctx.notes.map((n) => (
                <li key={n.id}>
                  <p className="note-body">{n.body}</p>
                  <p className="small muted">
                    {n.author} · <Time iso={n.created_at} />
                  </p>
                </li>
              ))}
            </ul>
          )}
          <form onSubmit={addNote} className="stack">
            <label className="field">
              <span className="field-label">Add a note</span>
              <textarea className="textarea" rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={5000} disabled={!ctx.can_edit} />
            </label>
            <InlineError error={action.error} />
            <button type="submit" className="btn btn-secondary" disabled={note.trim().length < 2 || action.isPending || !ctx.can_edit}>
              <StickyNote size={15} aria-hidden="true" /> {action.isPending ? "Saving…" : "Add note"}
            </button>
          </form>
        </Card>

        <div className="stack-lg">
          <Card title="Decision">
            {c.decision ? (
              <div className="stack">
                <p>
                  <strong>{meta.data?.decisions[c.decision] ?? humanize(c.decision)}</strong>{" "}
                  {c.decided_at && (
                    <span className="muted">
                      · <Time iso={c.decided_at} />
                    </span>
                  )}
                </p>
                {c.decision_rationale && <blockquote className="quote">{c.decision_rationale}</blockquote>}
              </div>
            ) : (
              <p className="muted small">
                No decision recorded. Move the case to Ready for review, then use “Record decision” in the header.
              </p>
            )}
          </Card>
          <Card title="Evidence requests">
            {ctx.evidence_requests.length === 0 ? (
              <p className="muted small">No evidence requested yet.</p>
            ) : (
              <ul className="plain-list">
                {ctx.evidence_requests.map((r) => (
                  <li key={r.id}>
                    {humanize(r.checklist_key)} from {r.requested_from} · <Chip size="sm" tone="warn">{humanize(r.status)}</Chip> <Time iso={r.created_at} />
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Hold decisions">
            {decided.length === 0 ? (
              <p className="muted small">No hold recommendations decided yet. See Overview → Hold recommendations.</p>
            ) : (
              <ul className="plain-list">
                {decided.map((h) => (
                  <li key={h.id}>
                    <IdChip id={h.account_id} /> <Chip size="sm" tone={h.status === "requested" ? "good" : "neutral"}>{h.status === "requested" ? "Hold requested" : "Declined"}</Chip>{" "}
                    <Money minor={h.amount_minor} currency={h.currency} /> {h.decided_at && <Time iso={h.decided_at} />}
                    {h.decision_note && <span className="cell-sub">“{h.decision_note}”</span>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>

      <Card
        title="Audit trail"
        subtitle="Every consequential action, hash-chained: each event's hash covers the previous one, so any edit breaks the chain."
        actions={
          audit.data ? (
            audit.data.verification.valid ? (
              <span className="verify-badge verify-ok">
                <ShieldCheck size={15} aria-hidden="true" /> Audit chain verified — {audit.data.verification.events} events
              </span>
            ) : (
              <span className="verify-badge verify-bad">
                <ShieldAlert size={15} aria-hidden="true" /> Chain broken at event {audit.data.verification.broken_at}
              </span>
            )
          ) : audit.isLoading ? (
            <Skeleton height={24} className="skeleton-badge" />
          ) : null
        }
      >
        {audit.isLoading ? (
          <LoadingBlock label="Loading audit trail" lines={6} />
        ) : audit.error ? (
          <ErrorState error={audit.error} onRetry={() => audit.refetch()} title="Couldn't load the audit trail" />
        ) : !audit.data || audit.data.events.length === 0 ? (
          <EmptyState title="No audit events">Nothing has been recorded for this case yet.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table table-compact audit-table">
              <caption className="sr-only">Audit events</caption>
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Actor</th>
                  <th scope="col">Action</th>
                  <th scope="col">Details</th>
                  <th scope="col">Trace</th>
                  <th scope="col">Hash</th>
                </tr>
              </thead>
              <tbody>
                {[...audit.data.events].reverse().map((e) => (
                  <tr key={e.id} className={audit.data.verification.broken_at === e.id ? "row-broken" : ""}>
                    <td data-label="Time">
                      <Time iso={e.created_at} seconds />
                    </td>
                    <td data-label="Actor">
                      {e.actor} <span className={`role-tag role-${e.actor_role}`}>{e.actor_role}</span>
                    </td>
                    <td data-label="Action">
                      <strong>{humanize(e.action)}</strong>
                    </td>
                    <td data-label="Details" className="small details-cell">
                      {summarizeDetails(e.details) || <span className="muted">—</span>}
                    </td>
                    <td data-label="Trace" className="mono small">
                      {e.trace_id ? shortHash(e.trace_id, 10) : <span className="muted">—</span>}
                    </td>
                    <td data-label="Hash" className="mono small" title={`hash ${e.hash}\nprev ${e.prev_hash}\n${formatUTC(e.created_at)}`}>
                      <Link2 size={11} aria-hidden="true" /> {shortHash(e.hash, 10)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
