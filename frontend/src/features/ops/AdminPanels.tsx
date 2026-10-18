import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/endpoints";
import { useAdminUsers, useIngestEvents, useSecurityStatus } from "../../api/hooks";
import { Card, EmptyState, ErrorState, InlineError, KeyValues, LoadingBlock, Time } from "../../components/Primitives";
import { Chip } from "../../components/Chip";
import { Modal } from "../../components/Overlay";
import { useToast } from "../../components/Toast";
import type { AdminUser, IngestEvent } from "../../types/api";

/** Encryption, DLP, MFA and integration status (supervisor and admin). */
export function SecurityCard() {
  const q = useSecurityStatus();
  return (
    <Card title="Security controls" subtitle="How personal data is protected in this deployment.">
      {q.isLoading ? (
        <LoadingBlock lines={4} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : q.data ? (
        <KeyValues
          rows={[
            [
              "Field encryption",
              <>
                {q.data.encryption.algorithm} · key <span className="mono">{q.data.encryption.active_key}</span> ({q.data.encryption.key_source}) ·{" "}
                {q.data.encryption.fields.length} fields
                <span className="cell-sub mono">{q.data.encryption.fields.join(", ")}</span>
              </>,
            ],
            [
              "Sensitive-data scan",
              <>
                {q.data.dlp.backend === "gcp" ? "Cloud DLP" : q.data.dlp.backend === "off" ? "Off" : "Built-in detectors"}
                <span className="cell-sub">Masked in notes and AI input: {q.data.dlp.masked_in_notes_and_llm_input.join(", ")}</span>
              </>,
            ],
            [
              "Two-step sign-in",
              <>
                {q.data.mfa.enrolled} of {q.data.mfa.users} users enrolled ·{" "}
                {q.data.mfa.required_roles.length ? `required for ${q.data.mfa.required_roles.join(", ")}` : "optional for all roles"}
              </>,
            ],
            ["Google sign-in (Firebase)", q.data.firebase_sign_in ? "On" : "Off"],
            ["Ledger ingest (Pub/Sub push)", q.data.pubsub_ingest ? "On" : "Off — statement upload only"],
          ]}
        />
      ) : null}
    </Card>
  );
}

/** Users and their MFA state; an admin can reset a lost authenticator. */
export function UsersCard() {
  const q = useAdminUsers();
  const [reset, setReset] = useState<AdminUser | null>(null);
  return (
    <Card title="Users and two-step sign-in" subtitle="Reset MFA only after confirming the person's identity another way.">
      {q.isLoading ? (
        <LoadingBlock lines={4} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <div className="table-wrap">
          <table className="table table-compact">
            <thead>
              <tr>
                <th scope="col">User</th>
                <th scope="col">Role</th>
                <th scope="col">MFA</th>
                <th scope="col" className="ta-r">Recovery codes</th>
                <th scope="col" />
              </tr>
            </thead>
            <tbody>
              {q.data?.users.map((u) => (
                <tr key={u.id}>
                  <td data-label="User">
                    <span className="mono">{u.username}</span>
                    <span className="cell-sub">{u.full_name}</span>
                  </td>
                  <td data-label="Role">{u.role}</td>
                  <td data-label="MFA">
                    {u.mfa_enabled ? "On" : u.mfa_required ? <Chip tone="warn" size="sm">Required, not enrolled</Chip> : <span className="muted">Off</span>}
                  </td>
                  <td data-label="Recovery codes" className="ta-r num">
                    {u.recovery_codes_left ?? "—"}
                  </td>
                  <td className="ta-r">
                    {u.mfa_enabled && (
                      <button type="button" className="btn btn-ghost btn-sm" onClick={() => setReset(u)}>
                        Reset MFA
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {reset && <ResetMfaDialog user={reset} onClose={() => setReset(null)} />}
    </Card>
  );
}

function ResetMfaDialog({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => api.adminResetMfa(user.id, reason.trim()),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["admin"] });
      toast.show(`MFA reset for ${user.username}. They will set it up again at next sign-in.`);
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate();
  };
  return (
    <Modal
      open
      onClose={onClose}
      title={`Reset MFA: ${user.username}`}
      description="Removes their authenticator and recovery codes. Recorded in the audit trail with your reason."
      size="sm"
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" form="mfa-reset" className="btn btn-danger" disabled={m.isPending || reason.trim().length < 10}>
            {m.isPending ? "Resetting…" : "Reset MFA"}
          </button>
        </>
      }
    >
      <form id="mfa-reset" onSubmit={submit}>
        <label className="field">
          <span className="field-label">Reason (at least 10 characters)</span>
          <textarea className="textarea" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={255} />
        </label>
        <InlineError error={m.error} />
      </form>
    </Modal>
  );
}

const STATUS_TONE: Record<string, "good" | "warn" | "bad"> = { processed: "good", partial: "warn", rejected: "bad" };

/** Ledger deliveries (Pub/Sub and uploads). Admins can load a statement file. */
export function IngestCard({ canUpload }: { canUpload: boolean }) {
  const q = useIngestEvents();
  const [open, setOpen] = useState<IngestEvent | null>(null);
  return (
    <Card
      title="Ledger ingest"
      subtitle={
        q.data?.pubsub_enabled
          ? "Deliveries from the Pub/Sub ledger topic and uploaded statements."
          : "Pub/Sub push is not configured here; admins can upload statement files."
      }
    >
      {canUpload && q.data && <UploadStatement formats={q.data.formats} />}
      {q.isLoading ? (
        <LoadingBlock lines={4} />
      ) : q.error ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : !q.data?.events.length ? (
        <EmptyState title="No deliveries yet">Records published to the ledger topic or uploaded here appear in this list.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table table-compact">
            <thead>
              <tr>
                <th scope="col">Received</th>
                <th scope="col">Channel</th>
                <th scope="col">Format</th>
                <th scope="col">Status</th>
                <th scope="col" className="ta-r">In</th>
                <th scope="col" className="ta-r">New</th>
                <th scope="col" className="ta-r">Merged</th>
                <th scope="col" className="ta-r">Dupes</th>
                <th scope="col" className="ta-r">Rejected</th>
                <th scope="col">Cases updated</th>
              </tr>
            </thead>
            <tbody>
              {q.data.events.map((e) => (
                <tr key={e.id}>
                  <td data-label="Received">
                    <Time iso={e.received_at} seconds />
                    <span className="cell-sub">{e.received_by}</span>
                  </td>
                  <td data-label="Channel">
                    {e.channel}
                    <span className="cell-sub mono">{e.source_system}</span>
                  </td>
                  <td data-label="Format" className="mono small">
                    {e.format}
                  </td>
                  <td data-label="Status">
                    <Chip tone={STATUS_TONE[e.status] ?? "neutral"} size="sm">
                      {e.status}
                    </Chip>
                    {e.error && <span className="cell-sub">{e.error}</span>}
                  </td>
                  <td data-label="In" className="ta-r num">{e.records_in}</td>
                  <td data-label="New" className="ta-r num">{e.created}</td>
                  <td data-label="Merged" className="ta-r num">{e.merged}</td>
                  <td data-label="Dupes" className="ta-r num">{e.duplicates}</td>
                  <td data-label="Rejected" className="ta-r num">
                    {e.rejected.length > 0 ? (
                      <button type="button" className="link-btn num" onClick={() => setOpen(e)}>
                        {e.rejected.length}
                      </button>
                    ) : (
                      0
                    )}
                  </td>
                  <td data-label="Cases updated">
                    {e.cases_refreshed.length
                      ? e.cases_refreshed.slice(0, 3).map((c) => (
                          <Link key={c} to={`/cases/${c}`} className="link mono small">
                            {c}{" "}
                          </Link>
                        ))
                      : <span className="muted">—</span>}
                    {e.cases_refreshed.length > 3 && <span className="muted small">+{e.cases_refreshed.length - 3}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && (
        <Modal open onClose={() => setOpen(null)} title={`Rejected records (delivery ${open.id})`} size="md">
          <ul className="plain-list">
            {open.rejected.map((r, i) => (
              <li key={i}>
                <span className="mono">{r.source}</span> — {r.reason}
              </li>
            ))}
          </ul>
        </Modal>
      )}
    </Card>
  );
}

function UploadStatement({ formats }: { formats: Record<string, string> }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState("iso20022.camt.053");
  const [source, setSource] = useState("core");
  const m = useMutation({
    mutationFn: () => api.ingestFile(file as File, format, source.trim()),
    onSuccess: async (r) => {
      await qc.invalidateQueries({ queryKey: ["ingest"] });
      await qc.invalidateQueries({ queryKey: ["admin"] });
      const e = r.event;
      toast.show(
        r.already_processed
          ? "This file was already loaded; nothing changed."
          : `${e.created} new, ${e.merged} merged, ${e.duplicates} duplicate, ${e.rejected.length} rejected`,
        e.status === "processed" ? "good" : "neutral",
      );
    },
  });
  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    if (file) m.mutate();
  };
  return (
    <form className="ingest-upload" onSubmit={submit}>
      <label className="field">
        <span className="field-label">Statement or record file</span>
        <input className="input" type="file" accept=".xml,.csv,.json,text/csv,application/xml,application/json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      <label className="field">
        <span className="field-label">Format</span>
        <select className="select" value={format} onChange={(e) => setFormat(e.target.value)}>
          {Object.entries(formats).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span className="field-label">Source system</span>
        <input className="input" value={source} onChange={(e) => setSource(e.target.value)} maxLength={32} />
      </label>
      <button type="submit" className="btn btn-primary" disabled={!file || m.isPending}>
        {m.isPending ? "Loading…" : "Load file"}
      </button>
      <InlineError error={m.error} />
    </form>
  );
}
