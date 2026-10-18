import { useRef } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/endpoints";
import { usePortalDispute } from "../../api/hooks";
import { ErrorState, InlineError, LoadingBlock, Note, Time } from "../../components/Primitives";
import { useToast } from "../../components/Toast";
import type { DlpFinding } from "../../types/api";
import { ArrowLeft, FileText } from "lucide-react";
import { DisputeSummaryCard, PROOF_ACCEPT, StatusSteps } from "./parts";

function UploadButton({ caseId, checklistKey, label }: { caseId: string; checklistKey?: string; label: string }) {
  const ref = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  const toast = useToast();
  const up = useMutation({
    mutationFn: (file: File) => api.portalUpload(caseId, file, checklistKey),
    onSuccess: async (d) => {
      qc.setQueryData(["portal", "dispute", caseId], d);
      await qc.invalidateQueries({ queryKey: ["portal", "disputes"] });
      toast.show("Thank you — we've received your file.");
    },
  });
  return (
    <span className="upload-inline">
      <input
        ref={ref}
        type="file"
        className="sr-only"
        accept={PROOF_ACCEPT}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) up.mutate(f);
          e.target.value = "";
        }}
        aria-label={label}
      />
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => ref.current?.click()} disabled={up.isPending}>
        {up.isPending ? "Uploading…" : label}
      </button>
      <InlineError error={up.error} />
    </span>
  );
}

/** One dispute, as the customer sees it: status, what we need from them, deadlines and what has happened. */
export default function DisputeDetail() {
  const { caseId = "" } = useParams();
  const loc = useLocation();
  const fresh = (loc.state as { justRaised?: boolean; masked?: DlpFinding[]; filesSent?: number; filesFailed?: number } | null) ?? null;
  const q = usePortalDispute(caseId);
  if (q.isLoading) return <LoadingBlock lines={8} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} title="We couldn't find that dispute" />;
  const d = q.data;
  const open = d.status_key !== "resolved";
  return (
    <div className="portal-page">
      <Link to="/portal" className="back-link">
        <ArrowLeft size={16} aria-hidden="true" /> My disputes
      </Link>
      {fresh?.justRaised && (
        <Note tone="good">
          <strong>Your dispute has been raised.</strong> Your reference is <strong>{d.case_id}</strong> — keep it for any call or visit to the bank.
          We'll contact you by your chosen method.
          {fresh.filesSent ? ` We received ${fresh.filesSent} file${fresh.filesSent === 1 ? "" : "s"} from you.` : ""}
        </Note>
      )}
      {fresh?.filesFailed ? (
        <Note tone="warn">
          {fresh.filesFailed} file{fresh.filesFailed === 1 ? "" : "s"} could not be sent. Your dispute is raised; please add {fresh.filesFailed === 1 ? "it" : "them"} again below.
        </Note>
      ) : null}
      {fresh?.masked && fresh.masked.length > 0 && (
        <Note tone="warn">For your safety we hid what looked like an OTP, PIN or card number in your description. Never share these with anyone.</Note>
      )}

      <section className="dispute-hero" aria-labelledby="dispute-title">
        <div className="dispute-hero-top">
          <span>
            <span className="portal-kicker">Dispute {d.case_id}</span>
            <h1 id="dispute-title" className="dispute-hero-title">
              <span className="num">{d.payment.amount}</span> to {d.payment.paid_to}
            </h1>
            <span className="dispute-hero-sub">
              {d.reason} · raised <Time iso={d.raised_at} />
            </span>
          </span>
          <span className={`hero-status step-${d.step}`}>{d.status}</span>
        </div>
        <StatusSteps steps={d.steps} step={d.step} label={d.status} />
        <p className="status-explain">{d.decision ?? d.explain}</p>
      </section>

      {d.requests.length > 0 && (
        <section className="portal-card portal-card-action" aria-labelledby="need-title">
          <h2 id="need-title" className="portal-h2">
            We need something from you
          </h2>
          <ul className="need-list">
            {d.requests.map((r) => (
              <li key={r.id}>
                <span>
                  {r.label}
                  <span className="small muted"> · asked <Time iso={r.requested_at} dateOnly /></span>
                </span>
                <UploadButton caseId={d.case_id} checklistKey={r.checklist_key} label="Upload" />
              </li>
            ))}
          </ul>
          <p className="small muted">Photos, screenshots, PDFs or text files up to 5 MB.</p>
        </section>
      )}

      <div className="portal-two">
        {open && d.deadlines.length > 0 && (
          <section className="portal-card" aria-labelledby="dates-title">
            <h2 id="dates-title" className="portal-h2">
              Our deadlines
            </h2>
            <ul className="date-tiles">
              {d.deadlines.map((x) => {
                const dt = new Date(x.due_at);
                return (
                  <li key={x.label} className="date-tile">
                    <span className="date-box" aria-hidden="true">
                      <span className="date-day">{dt.toLocaleDateString("en-IN", { day: "numeric", timeZone: "Asia/Kolkata" })}</span>
                      <span className="date-mon">{dt.toLocaleDateString("en-IN", { month: "short", timeZone: "Asia/Kolkata" })}</span>
                    </span>
                    <span>
                      <strong>{x.label}</strong>
                      <span className="small muted">
                        by <Time iso={x.due_at} dateOnly />
                      </span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
        <section className="portal-card" aria-labelledby="history-title">
          <h2 id="history-title" className="portal-h2">
            What has happened
          </h2>
          <ol className="timeline">
            {[...d.timeline].reverse().map((t, i) => (
              <li key={i} className={i === 0 ? "is-latest" : ""}>
                <span className="timeline-dot" aria-hidden="true" />
                <span className="timeline-body">
                  <span>{t.text}</span>
                  <Time iso={t.at} className="small muted" />
                </span>
              </li>
            ))}
          </ol>
        </section>
      </div>

      <DisputeSummaryCard
        title="What you told us"
        subtitle={`Reference ${d.case_id}`}
        payment={d.payment}
        description={d.description}
        items={[
          { label: "What happened", value: d.reason },
          ...(d.answers.otp_shared ? [{ label: "Shared an OTP, PIN or password", value: d.answers.otp_shared }] : []),
          ...(d.answers.noticed ? [{ label: "Noticed", value: d.answers.noticed }] : []),
          ...(d.answers.cyber_complaint_ref ? [{ label: "Cyber-crime complaint", value: d.answers.cyber_complaint_ref }] : []),
          ...(d.answers.contact_preference ? [{ label: "Contact me by", value: d.answers.contact_preference }] : []),
        ]}
      >
        <div className="sum-proof">
          <span className="sum-label">Files you sent</span>
          {d.files.length === 0 ? (
            <p className="small muted">None yet. A screenshot, the bank SMS or a receipt helps us check faster.</p>
          ) : (
            <ul className="file-chips">
              {d.files.map((f) => (
                <li key={f.id} className="file-chip">
                  <FileText size={16} aria-hidden="true" />
                  <span>
                    <strong>{f.filename}</strong>
                    <Time iso={f.uploaded_at} className="small muted" />
                  </span>
                </li>
              ))}
            </ul>
          )}
          {open && <UploadButton caseId={d.case_id} label="Send a receipt, screenshot or other proof" />}
        </div>
      </DisputeSummaryCard>
    </div>
  );
}
