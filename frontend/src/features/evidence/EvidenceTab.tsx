import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { FileText, ShieldAlert } from "lucide-react";
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
import { DlpLine, EvidenceScorePanel, ScoreBadge } from "./EvidenceScore";
import { checklistLabel, checklistLabelByKey, checklistWhy, fieldLabel, kindLabel, matchLabel, plainCheckName, plainDetail, reconSummary } from "./plainEvidence";

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
              <strong className="num">
                {ck.present} of {ck.required}
              </strong>{" "}
              needed items are in. A missing item makes the file less complete — it does not count for or against the customer.
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
                      <span className="check-label" title={it.label}>
                        {checklistLabel(it)}
                      </span>
                      {!it.required && <span className="muted small">optional</span>}
                      <Chip tone={s.tone} size="sm">
                        {s.label}
                      </Chip>
                    </div>
                    <p className="small muted">{checklistWhy(it)}</p>
                  </div>
                  {canRequest && (
                    <button type="button" className="btn btn-secondary btn-sm" onClick={() => setRequestFor(it)} aria-label={`Request: ${checklistLabel(it)}`}>
                      Request
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {d.requests.length > 0 && (
            <>
              <h4 className="plain-sub">Requests sent</h4>
              <ul className="plain-list request-list">
                {d.requests.map((r) => (
                  <li key={r.id}>
                    <strong>{checklistLabelByKey(r.checklist_key, ck.items)}</strong> from {r.requested_from} ·{" "}
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

        <Card title="Files received" subtitle="Treat what a document says with care until it has been compared with the bank's record.">
          {d.evidence.length === 0 ? (
            <EmptyState title="No files yet" icon={<FileText size={22} />}>
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
        <Card title="Do the records agree?" subtitle="The system compares what the customer and documents say with the bank's records.">
          {d.consistency.checks.length === 0 ? (
            <p className="muted small">Nothing could be compared yet.</p>
          ) : (
            <ul className="dim-list dim-list-detail">
              {d.consistency.checks.map((c, i) => (
                <li key={i}>
                  <div className="dim-li-head">
                    <span title={c.check}>{plainCheckName(c.check, d.evidence)}</span>
                    <Chip tone={RESULT_TONE[c.result] ?? "neutral"} size="sm">
                      {matchLabel(c.result)}
                    </Chip>
                  </div>
                  <span className="small muted" title={c.detail}>
                    {plainDetail(c.detail)}
                  </span>
                  {c.source_ids.length > 0 && (
                    <span className="id-list id-list-quiet">
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
      if (r.status === "analysed") toast.show(`${ev.filename} was read and compared with the bank's record`);
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
            <strong className="break">{ev.filename}</strong>
            <IdChip id={ev.id} />
          </div>
          <Chip tone="neutral" size="sm">
            File deleted
          </Chip>
        </div>
        <p className="small muted">
          Deleted {ev.deleted_at && <Time iso={ev.deleted_at} />}
          {ev.retention_note && <> — “{ev.retention_note}”</>}. The file and anything read from it were removed. A note that it existed, and its
          fingerprint (SHA-256 <span className="mono" title={ev.sha256}>{shortHash(ev.sha256, 12)}</span>), stay in the audit trail.
        </p>
      </li>
    );
  return (
    <li className="evidence-card">
      <div className="evidence-head">
        <div className="evidence-title">
          <strong className="break">{ev.filename}</strong>
          <IdChip id={ev.id} />
          {ev.score && <ScoreBadge score={ev.score} />}
        </div>
        <div className="evidence-actions">
          <a className="btn btn-ghost btn-sm" href={api.evidenceFileUrl(caseId, ev.id)} target="_blank" rel="noopener noreferrer">
            View file
          </a>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => analyse.mutate()} disabled={analyse.isPending}>
            {analyse.isPending ? "Analysing…" : notAnalysed ? "Analyse" : "Re-analyse"}
          </button>
          {retention === "active" && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setDeletion("request")}>
              Request deletion
            </button>
          )}
        </div>
      </div>
      {retention === "deletion_requested" && (
        <Note tone="warn">
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
        {kindLabel(ev.kind)} · added on <Time iso={ev.uploaded_at} /> by {ev.uploaded_by}
        {ev.checklist_key && <> · for “{checklistLabelByKey(ev.checklist_key, [])}”</>}
      </p>
      {ev.dlp && <DlpLine dlp={ev.dlp} />}
      {notAnalysed ? (
        <p className="not-analysed">
          <strong>{ev.analysis_status === "failed" ? "Couldn't read this file" : "Not analysed yet"}</strong>
          {ev.analysis_note
            ? ` — ${ev.analysis_note.replace(/^Not analysed\s*[—-]\s*/, "")}`
            : " — press Analyse to have the AI read it and the system compare it with the bank's record."}
        </p>
      ) : (
        <p className="small">
          <Chip tone={rec && rec.contradictions > 0 ? "bad" : "good"} size="sm">
            {rec ? reconSummary(rec) : "Analysed"}
          </Chip>
        </p>
      )}
      {injected && (
        <Note tone="bad" icon={<ShieldAlert size={15} />}>
          <strong>This document contains text addressed to an AI or reviewer.</strong> It was treated as data and ignored. Treat the document
          with extra care.
        </Note>
      )}
      {rec?.tamper_indicators && rec.tamper_indicators.length > 0 && (
        <Note tone="warn">Signs the document may have been edited: {rec.tamper_indicators.join("; ")}</Note>
      )}
      {rec && rec.checks.length > 0 && (
        <div className="table-wrap">
          <table className="mini-table recon-table">
            <caption className="sr-only">Details read from the document, compared with the bank's record</caption>
            <thead>
              <tr>
                <th scope="col">Detail</th>
                <th scope="col">Document says</th>
                <th scope="col">Bank record says</th>
                <th scope="col">Result</th>
              </tr>
            </thead>
            <tbody>
              {rec.checks.map((c, i) => (
                <tr key={i} className={`recon-${c.result}`}>
                  <th scope="row">{fieldLabel(c.field)}</th>
                  <td>{c.document_value ?? <span className="muted">Not found in the document</span>}</td>
                  <td>
                    {c.ledger_value ?? <span className="muted">—</span>} <span className="cell-sub mono">{c.ledger_id}</span>
                  </td>
                  <td>
                    <Chip tone={RESULT_TONE[c.result] ?? "neutral"} size="sm">
                      {matchLabel(c.result)}
                    </Chip>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted" title={`Compared by ${rec.compared_by}`}>
            The AI read the document. The system (not the AI) compared it with the bank's record.
          </p>
        </div>
      )}
      {ev.score && <EvidenceScorePanel score={ev.score} />}
      {ev.extracted?.summary && (
        <p className="small">
          <strong>What the AI read:</strong> {ev.extracted.summary}
        </p>
      )}
      <details className="disclosure">
        <summary>Show file details</summary>
        <div className="disclosure-body">
          <dl className="kv">
            <div className="kv-row">
              <dt>Evidence ID</dt>
              <dd className="mono">{ev.id}</dd>
            </div>
            <div className="kv-row">
              <dt>File type and size</dt>
              <dd>
                {ev.mime} · {formatBytes(ev.size)}
              </dd>
            </div>
            <div className="kv-row">
              <dt>File fingerprint (SHA-256)</dt>
              <dd className="mono break">{ev.sha256}</dd>
            </div>
            {ev.dlp?.note && (
              <div className="kv-row">
                <dt>Personal-data check note</dt>
                <dd>{ev.dlp.note}</dd>
              </div>
            )}
            {ev.analysis_note && !notAnalysed && (
              <div className="kv-row">
                <dt>Analysis note</dt>
                <dd>{ev.analysis_note}</dd>
              </div>
            )}
            {rec && (
              <div className="kv-row">
                <dt>Comparison result (system wording)</dt>
                <dd>
                  {rec.summary} · compared by {rec.compared_by}
                </dd>
              </div>
            )}
          </dl>
        </div>
      </details>
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
          toast.show(`Requested “${checklistLabel(item)}” from ${from}`);
          onClose();
        },
      },
    );
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={`Request: ${checklistLabel(item)}`}
      description={checklistWhy(item)}
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
          <span className="field-label">Who to ask</span>
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
  request: { title: "Request deletion", button: "Request deletion", help: "A supervisor must approve. A note that the file existed, and its fingerprint, stay in the audit trail." },
  approve: { title: "Approve deletion", button: "Delete file", help: "Deletes the file and anything read from it. This cannot be undone. A note that it existed, and its fingerprint, are kept." },
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
