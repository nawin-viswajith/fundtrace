import { useRef } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/endpoints";
import { usePortalDispute } from "../../api/hooks";
import { ErrorState, InlineError, LoadingBlock, Note, Time } from "../../components/Primitives";
import { useToast } from "../../components/Toast";
import type { DlpFinding } from "../../types/api";
import { PaymentCard, StatusSteps } from "./parts";

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
        accept=".png,.jpg,.jpeg,.pdf,.txt,image/png,image/jpeg,application/pdf,text/plain"
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
  const fresh = (loc.state as { justRaised?: boolean; masked?: DlpFinding[] } | null) ?? null;
  const q = usePortalDispute(caseId);
  if (q.isLoading) return <LoadingBlock lines={8} />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => q.refetch()} title="We couldn't find that dispute" />;
  const d = q.data;
  const open = d.status_key !== "resolved";
  return (
    <div className="portal-page">
      <Link to="/portal" className="back-link">
        ← My disputes
      </Link>
      {fresh?.justRaised && (
        <Note tone="good">
          <strong>Your dispute has been raised.</strong> Your reference is <strong>{d.case_id}</strong> — keep it for any call or visit to the bank.
          We'll contact you by your chosen method.
        </Note>
      )}
      {fresh?.masked && fresh.masked.length > 0 && (
        <Note tone="warn">For your safety we hid what looked like an OTP, PIN or card number in your description. Never share these with anyone.</Note>
      )}
      <h1 className="portal-h1">
        {d.payment.amount} to {d.payment.paid_to}
      </h1>
      <p className="portal-lede">
        {d.reason} · reference {d.case_id} · raised <Time iso={d.raised_at} />
      </p>

      <section className="portal-card" aria-labelledby="status-title">
        <h2 id="status-title" className="portal-h2">
          Where your dispute is
        </h2>
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
            <ul className="deadline-list">
              {d.deadlines.map((x) => (
                <li key={x.label}>
                  <span>{x.label}</span>
                  <strong>
                    by <Time iso={x.due_at} dateOnly />
                  </strong>
                </li>
              ))}
            </ul>
          </section>
        )}
        <section className="portal-card" aria-labelledby="history-title">
          <h2 id="history-title" className="portal-h2">
            What has happened
          </h2>
          <ol className="history">
            {[...d.timeline].reverse().map((t, i) => (
              <li key={i}>
                <Time iso={t.at} />
                <span>{t.text}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>

      <section className="portal-card" aria-labelledby="details-title">
        <h2 id="details-title" className="portal-h2">
          What you told us
        </h2>
        <PaymentCard p={d.payment} />
        <dl className="review-list">
          <div>
            <dt>What happened</dt>
            <dd>{d.reason}</dd>
          </div>
          {d.answers.otp_shared && (
            <div>
              <dt>Shared an OTP, PIN or password</dt>
              <dd>{d.answers.otp_shared}</dd>
            </div>
          )}
          {d.answers.noticed && (
            <div>
              <dt>Noticed</dt>
              <dd>{d.answers.noticed}</dd>
            </div>
          )}
          {d.answers.cyber_complaint_ref && (
            <div>
              <dt>Cyber-crime complaint</dt>
              <dd>{d.answers.cyber_complaint_ref}</dd>
            </div>
          )}
          <div>
            <dt>Your description</dt>
            <dd className="review-text">{d.description}</dd>
          </div>
          {d.answers.contact_preference && (
            <div>
              <dt>Contact me by</dt>
              <dd>{d.answers.contact_preference}</dd>
            </div>
          )}
        </dl>
        <h3 className="portal-h3">Files you sent</h3>
        {d.files.length === 0 ? (
          <p className="small muted">None yet.</p>
        ) : (
          <ul className="plain-list small">
            {d.files.map((f) => (
              <li key={f.id}>
                {f.filename} · <Time iso={f.uploaded_at} />
              </li>
            ))}
          </ul>
        )}
        {open && <UploadButton caseId={d.case_id} label="Send a receipt, screenshot or other proof" />}
      </section>
    </div>
  );
}
