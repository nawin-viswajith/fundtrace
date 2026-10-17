import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { ExternalLink, FileSearch, FileText, Send, ShieldAlert, Trash2 } from "lucide-react";
import { canSupervise, useAuth } from "../auth/AuthProvider";
import { useEvidence, useInvalidateCase, useCaseAction } from "../../api/hooks";
import { api } from "../../api/endpoints";
import { errorMessage } from "../../api/client";
import { useWorkspace } from "../case/workspace";
import { Card, EmptyState, ErrorState, InlineError, LoadingBlock, Note, Time } from "../../components/Primitives";
import { Chip } from "../../components/Chip";
import { IdChip } from "../../components/Domain";
import { Modal } from "../../components/Overlay";
import { useToast } from "../../components/Toast";
import { CHECKLIST_STATUS, RESULT_TONE } from "../../lib/labels";
import { formatBytes, humanize, shortHash } from "../../lib/format";
import type { ChecklistItem, EvidenceItem } from "../../types/api";
import { UploadBox } from "./UploadBox";

export function EvidenceTab() {
  const { caseId } = useWorkspace();
  const q = useEvidence(caseId);
  const [requestFor, setRequestFor] = useState<ChecklistItem | null>(null);
  if (q.isLoading) return <LoadingBlock label="Loading evidence" lines={8} />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load evidence" />;
  const d = q.data;
  if (!d) return null;
  const ck = d.checklist;

  return (
    <div className="evidence-layout">
      <div className="stack-lg">
        <Card
          title="Evidence checklist"
          subtitle={
            <>
              <span className="num">
                {ck.present} / {ck.required}
              </span>{" "}
              required items present. {ck.note}
            </>
          }
        >
          <ul className="checklist">
            {ck.items.map((it) => {
              const s = CHECKLIST_STATUS[it.status] ?? { label: humanize(it.status), tone: "neutral" as const };
              const canRequest = it.status === "missing";
              return (
                <li key={it.key} className={`check-item check-${it.status}`}>
                  <div className="check-main">
                    <div className="check-head">
                      <span className="check-label">{it.label}</span>
                      {!it.required && <span className="muted small">optional</span>}
                      <Chip tone={s.tone} size="sm">
                        {s.label}
                      </Chip>
                    </div>
                    <p className="small muted">{it.why_it_matters}</p>
                  </div>
                  {canRequest && (
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => setRequestFor(it)}>
                      <Send size={14} aria-hidden="true" /> Request
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {d.requests.length > 0 && (
            <>
              <h4 className="h-sub">Evidence requests</h4>
              <ul className="plain-list request-list">
                {d.requests.map((r) => (
                  <li key={r.id}>
                    <strong>{ck.items.find((i) => i.key === r.checklist_key)?.label ?? humanize(r.checklist_key)}</strong> from {r.requested_from} ·{" "}
                    <Chip tone="warn" size="sm">
                      {humanize(r.status)}
                    </Chip>{" "}
                    <Time iso={r.created_at} />
                    {r.note && <span className="cell-sub">“{r.note}”</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>

        <Card title="Evidence items" subtitle="Files received for this case. Document contents are untrusted until compared with the ledger.">
          {d.evidence.length === 0 ? (
            <EmptyState title="No evidence yet" icon={<FileText size={22} />}>
              Upload the customer's receipt, screenshot or statement, or request it from the checklist.
            </EmptyState>
          ) : (
            <ul className="evidence-list">
              {d.evidence.map((ev) => (
                <EvidenceCard key={ev.id} ev={ev} />
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="stack-lg">
        <UploadBox checklist={ck.items} />
        <Card title="Consistency checks" subtitle="Cross-source comparisons made by code">
          {d.consistency.checks.length === 0 ? (
            <p className="muted small">No checks could be run yet.</p>
          ) : (
            <ul className="dim-list dim-list-detail">
              {d.consistency.checks.map((c, i) => (
                <li key={i}>
                  <div className="dim-li-head">
                    <span>{c.check}</span>
                    <Chip tone={RESULT_TONE[c.result] ?? "neutral"} size="sm">
                      {humanize(c.result)}
                    </Chip>
                  </div>
                  <span className="small muted">{c.detail}</span>
                  {c.source_ids.length > 0 && (
                    <span className="id-list">
                      {c.source_ids.map((s) => (
                        <IdChip key={s} id={s} />
                      ))}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      {requestFor && <RequestDialog item={requestFor} onClose={() => setRequestFor(null)} />}
    </div>
  );
}

function EvidenceCard({ ev }: { ev: EvidenceItem }) {
  const { caseId } = useWorkspace();
  const invalidate = useInvalidateCase(caseId);
  const toast = useToast();
  const analyse = useMutation({
    mutationFn: () => api.analyseEvidence(caseId, ev.id),
    onSuccess: async (r) => {
      await invalidate();
      if (r.status === "analysed") toast.show(`${ev.filename} analysed and compared with the ledger`);
      else toast.show(r.note ?? "Not analysed", "neutral");
    },
    onError: (e) => toast.show(errorMessage(e), "bad"),
  });
  const { user } = useAuth();
  const [deletion, setDeletion] = useState<null | "request" | "approve" | "cancel">(null);
  const rec = ev.reconciliation;
  const notAnalysed = ev.analysis_status !== "analysed";
  const injected = rec?.embedded_instructions_detected || ev.extracted?.embedded_instructions_detected;
  const retention = ev.retention_status ?? "active";
  if (retention === "deleted")
    return (
      <li className="evidence-card evidence-deleted">
        <div className="evidence-head">
          <div className="evidence-title">
            <Trash2 size={16} aria-hidden="true" />
            <strong className="break">{ev.filename}</strong>
            <IdChip id={ev.id} />
          </div>
          <Chip tone="neutral" size="sm">
            File deleted
          </Chip>
        </div>
        <p className="small muted">
          Deleted {ev.deleted_at && <Time iso={ev.deleted_at} />}
          {ev.retention_note && <> — “{ev.retention_note}”</>}. The file and anything read from it were removed; the record and its
          sha256 <span className="mono" title={ev.sha256}>{shortHash(ev.sha256, 12)}</span> stay in the audit trail.
        </p>
      </li>
    );
  return (
    <li className="evidence-card">
      <div className="evidence-head">
        <div className="evidence-title">
          <FileText size={16} aria-hidden="true" />
          <strong className="break">{ev.filename}</strong>
          <IdChip id={ev.id} />
        </div>
        <div className="evidence-actions">
          <a className="btn btn-ghost btn-sm" href={api.evidenceFileUrl(caseId, ev.id)} target="_blank" rel="noopener noreferrer">
            <ExternalLink size={14} aria-hidden="true" /> View file
          </a>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => analyse.mutate()} disabled={analyse.isPending}>
            <FileSearch size={14} aria-hidden="true" /> {analyse.isPending ? "Analysing…" : notAnalysed ? "Analyse" : "Re-analyse"}
          </button>
          {retention === "active" && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDeletion("request")}>
              <Trash2 size={14} aria-hidden="true" /> Request deletion
            </button>
          )}
        </div>
      </div>
      {retention === "deletion_requested" && (
        <Note tone="warn" icon={<Trash2 size={15} />}>
          <strong>Deletion requested</strong>
          {ev.retention_note && <> — “{ev.retention_note}”</>}.{" "}
          {canSupervise(user) ? (
            <span className="inline-actions">
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => setDeletion("approve")}>
                Approve deletion
              </button>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDeletion("cancel")}>
                Keep file
              </button>
            </span>
          ) : (
            <span className="muted">Waiting for a supervisor.</span>
          )}
        </Note>
      )}
      {deletion && <DeletionDialog ev={ev} decision={deletion} onClose={() => setDeletion(null)} />}
      <p className="small muted">
        {humanize(ev.kind)} · {ev.mime} · {formatBytes(ev.size)} · sha256 <span className="mono" title={ev.sha256}>{shortHash(ev.sha256, 12)}</span> · uploaded by{" "}
        {ev.uploaded_by} <Time iso={ev.uploaded_at} />
        {ev.checklist_key && <> · for “{humanize(ev.checklist_key)}”</>}
      </p>
      {notAnalysed ? (
        <p className="not-analysed">
          <strong>{ev.analysis_status === "failed" ? "Analysis failed" : "Not analysed"}</strong>
          {ev.analysis_note ? ` — ${ev.analysis_note.replace(/^Not analysed\s*[—-]\s*/, "")}` : " — no analysis has been run yet"}
        </p>
      ) : (
        <p className="small">
          <Chip tone={rec && rec.contradictions > 0 ? "bad" : "good"} size="sm">
            {rec?.summary ?? "Analysed"}
          </Chip>{" "}
          <span className="muted">{ev.analysis_note}</span>
        </p>
      )}
      {injected && (
        <Note tone="bad" icon={<ShieldAlert size={15} />}>
          <strong>This document contains text addressed to an AI or reviewer.</strong> It was treated as data and ignored. Treat the document
          with extra care.
        </Note>
      )}
      {rec?.tamper_indicators && rec.tamper_indicators.length > 0 && (
        <Note tone="warn">Possible tampering indicators: {rec.tamper_indicators.join("; ")}</Note>
      )}
      {rec && rec.checks.length > 0 && (
        <div className="table-wrap">
          <table className="mini-table recon-table">
            <caption className="sr-only">Extracted fields compared with the ledger</caption>
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Document says</th>
                <th scope="col">Ledger says</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {rec.checks.map((c, i) => (
                <tr key={i} className={`recon-${c.result}`}>
                  <th scope="row">{humanize(c.field)}</th>
                  <td>{c.document_value ?? <span className="muted">not found</span>}</td>
                  <td>
                    {c.ledger_value ?? <span className="muted">—</span>} <span className="cell-sub mono">{c.ledger_id}</span>
                  </td>
                  <td>
                    <Chip tone={RESULT_TONE[c.result] ?? "neutral"} size="sm">
                      {c.result === "contradicts" ? "Contradicts" : c.result === "matches" ? "Matches" : "Unverifiable"}
                    </Chip>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted">Read by AI, compared by {rec.compared_by}.</p>
        </div>
      )}
      {ev.extracted?.summary && <p className="small">AI reading: {ev.extracted.summary}</p>}
      <InlineError error={analyse.error} />
    </li>
  );
}

function RequestDialog({ item, onClose }: { item: ChecklistItem; onClose: () => void }) {
  const { caseId } = useWorkspace();
  const action = useCaseAction(caseId);
  const toast = useToast();
  const [from, setFrom] = useState(item.key.includes("bank") ? "receiving bank" : item.key.includes("merchant") ? "merchant" : "customer");
  const [note, setNote] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    action.mutate(
      { type: "request_evidence", checklist_key: item.key, requested_from: from.trim() || "customer", note: note.trim() || undefined },
      {
        onSuccess: () => {
          toast.show(`Requested “${item.label}” from ${from}`);
          onClose();
        },
      },
    );
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={`Request: ${item.label}`}
      description={item.why_it_matters}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="req-form" className="btn btn-primary" disabled={action.isPending}>
            {action.isPending ? "Sending…" : "Record request"}
          </button>
        </>
      }
    >
      <form id="req-form" onSubmit={submit}>
        <label className="field">
          <span className="field-label">Request from</span>
          <input className="input" list="req-from-options" value={from} onChange={(e) => setFrom(e.target.value)} maxLength={64} />
          <datalist id="req-from-options">
            <option value="customer" />
            <option value="receiving bank" />
            <option value="merchant" />
            <option value="payment switch" />
            <option value="internal operations" />
          </datalist>
        </label>
        <label className="field">
          <span className="field-label">Note (optional)</span>
          <textarea className="textarea" rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />
        </label>
        <InlineError error={action.error} />
      </form>
    </Modal>
  );
}

const DELETION_COPY = {
  request: { title: "Request deletion", button: "Request deletion", help: "A supervisor must approve. The record and its hash stay in the audit trail." },
  approve: { title: "Approve deletion", button: "Delete file", help: "Deletes the file and anything read from it. This cannot be undone; the record and hash are kept." },
  cancel: { title: "Keep this file", button: "Cancel request", help: "The deletion request is withdrawn and the file stays." },
} as const;

function DeletionDialog({ ev, decision, onClose }: { ev: EvidenceItem; decision: "request" | "approve" | "cancel"; onClose: () => void }) {
  const { caseId } = useWorkspace();
  const action = useCaseAction(caseId);
  const toast = useToast();
  const [note, setNote] = useState("");
  const copy = DELETION_COPY[decision];
  const submit = (e: FormEvent) => {
    e.preventDefault();
    action.mutate(
      { type: "evidence_deletion", evidence_id: ev.id, decision, note: note.trim() },
      {
        onSuccess: () => {
          toast.show(decision === "approve" ? `${ev.filename} deleted` : decision === "request" ? "Deletion requested" : "Request cancelled");
          onClose();
        },
      },
    );
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={`${copy.title}: ${ev.filename}`}
      description={copy.help}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Back
          </button>
          <button type="submit" form="del-form" className={decision === "approve" ? "btn btn-danger" : "btn btn-primary"} disabled={action.isPending || note.trim().length < 10}>
            {action.isPending ? "Saving…" : copy.button}
          </button>
        </>
      }
    >
      <form id="del-form" onSubmit={submit}>
        <label className="field">
          <span className="field-label">Reason (at least 10 characters)</span>
          <textarea className="textarea" rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} required />
        </label>
        <InlineError error={action.error} />
      </form>
    </Modal>
  );
}
