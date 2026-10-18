import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/endpoints";
import { usePortalMe, usePortalPayments } from "../../api/hooks";
import { ErrorState, InlineError, LoadingBlock, Note } from "../../components/Primitives";
import type { PortalPayment, PortalProfile } from "../../types/api";
import { DisputeSummaryCard, PaymentCard, ProofPicker, sendProof, type PendingProof } from "./parts";

const STEPS = ["Payment", "What happened", "Details", "Check and submit"];

interface FormState {
  payment: PortalPayment | null;
  reason: string;
  otp_shared: string;
  noticed: string;
  cyber: "" | "yes" | "not_yet";
  cyber_ref: string;
  description: string;
  contact: string;
  declaration: boolean;
}

const EMPTY: FormState = {
  payment: null,
  reason: "",
  otp_shared: "",
  noticed: "",
  cyber: "",
  cyber_ref: "",
  description: "",
  contact: "",
  declaration: false,
};

/** Fixed choices as large, easy-to-tap radio boxes. */
function Choices({
  legend,
  name,
  value,
  options,
  onChange,
  hint,
}: {
  legend: string;
  name: string;
  value: string;
  options: { value: string; label: string; help?: string }[];
  onChange: (v: string) => void;
  hint?: ReactNode;
}) {
  return (
    <fieldset className="choices">
      <legend className="choices-legend">{legend}</legend>
      {hint && <p className="small muted choices-hint">{hint}</p>}
      {options.map((o) => (
        <label key={o.value} className={`choice ${value === o.value ? "is-on" : ""}`}>
          <input type="radio" name={name} value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} />
          <span>
            <span className="choice-label">{o.label}</span>
            {o.help && <span className="choice-help">{o.help}</span>}
          </span>
        </label>
      ))}
    </fieldset>
  );
}

export function stepErrors(step: number, f: FormState, me: PortalProfile): string | null {
  const fraud = me.reasons.find((r) => r.key === f.reason)?.asks_otp ?? false;
  if (step === 0 && !f.payment) return "Choose the payment you want to dispute.";
  if (step === 1 && !f.reason) return "Choose what happened.";
  if (step === 2) {
    if (fraud && !f.otp_shared) return "Tell us whether you shared an OTP, PIN or password.";
    if (!f.noticed) return "Tell us when you noticed the payment.";
    if (fraud && !f.cyber) return "Tell us whether you have reported this to the cyber-crime helpline.";
    if (fraud && f.cyber === "yes" && !/^[A-Za-z0-9/\-_. ]{4,40}$/.test(f.cyber_ref.trim())) return "Enter the complaint number (4–40 letters or numbers).";
    if (f.description.trim().length < 20) return "Describe what happened in at least 20 characters.";
    if (!f.contact) return "Choose how we should contact you.";
  }
  if (step === 3 && !f.declaration) return "Please confirm the declaration.";
  return null;
}

export default function DisputeForm() {
  const me = usePortalMe();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [step, setStep] = useState(0);
  const [f, setF] = useState<FormState>(EMPTY);
  const [q, setQ] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [proof, setProof] = useState<PendingProof[]>([]);
  const payments = usePortalPayments(q.trim());
  const submit = useMutation({
    mutationFn: async () => {
      const d = await api.portalRaise({
        txn_id: f.payment!.id,
        reason: f.reason,
        description: f.description.trim(),
        otp_shared: f.otp_shared || null,
        noticed: f.noticed,
        cyber_complaint_ref: f.cyber === "yes" ? f.cyber_ref.trim() : null,
        contact_preference: f.contact,
        declaration: f.declaration,
        channel: "portal_form",
      });
      const failed = await sendProof(d.case_id, proof, api.portalUpload);
      return { d, failed };
    },
    onSuccess: async ({ d, failed }) => {
      await qc.invalidateQueries({ queryKey: ["portal"] });
      nav(`/portal/disputes/${d.case_id}`, { state: { justRaised: true, masked: d.masked ?? [], filesSent: proof.length - failed, filesFailed: failed } });
    },
  });

  if (me.isLoading) return <LoadingBlock lines={6} />;
  if (me.error || !me.data) return <ErrorState error={me.error} onRetry={() => me.refetch()} />;
  const profile = me.data;
  const reason = profile.reasons.find((r) => r.key === f.reason);
  const fraud = reason?.asks_otp ?? false;
  const set = (patch: Partial<FormState>) => {
    setF((prev) => ({ ...prev, ...patch }));
    setErr(null);
  };
  const next = () => {
    const e = stepErrors(step, f, profile);
    if (e) return setErr(e);
    if (step < 3) setStep(step + 1);
    else submit.mutate();
  };
  const opts = (m: Record<string, string>) => Object.entries(m).map(([value, label]) => ({ value, label }));

  return (
    <div className="portal-page">
      <header className="portal-hello">
        <p className="portal-kicker">Raise a dispute</p>
        <h1 className="portal-h1">Fill in a form</h1>
      </header>
      <ol className="wizard-steps" aria-label="Steps">
        {STEPS.map((s, i) => (
          <li key={s} className={i === step ? "is-current" : i < step ? "is-done" : ""} aria-current={i === step ? "step" : undefined}>
            <span className="num">{i + 1}</span> {s}
          </li>
        ))}
      </ol>

      <section className="portal-card" aria-labelledby="step-title">
        <h2 id="step-title" className="portal-h2">
          {["Which payment is this about?", "What happened?", "A few more details", "Check your answers"][step]}
        </h2>

        {step === 0 && (
          <>
            <label className="field">
              <span className="field-label">Search by who you paid, the amount or the reference</span>
              <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Rahul, 15000 or 6289…" maxLength={64} />
            </label>
            {payments.isLoading ? (
              <LoadingBlock lines={4} />
            ) : payments.error ? (
              <ErrorState error={payments.error} onRetry={() => payments.refetch()} />
            ) : !payments.data?.transactions.length ? (
              <p className="muted">No payments found{q ? " for that search" : " in the last 4 months"}.</p>
            ) : (
              <div className="pay-list" role="list">
                {payments.data.transactions.map((p) => (
                  <div role="listitem" key={p.id}>
                    <PaymentCard
                      p={p}
                      selected={f.payment?.id === p.id}
                      onSelect={() => set({ payment: p })}
                      disabledNote={p.dispute_case_id ? `Already disputed (${p.dispute_case_id})` : undefined}
                    />
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {step === 1 && (
          <Choices
            legend="Choose the one that fits best"
            name="reason"
            value={f.reason}
            options={profile.reasons.map((r) => ({ value: r.key, label: r.label, help: r.help }))}
            onChange={(v) => set({ reason: v })}
          />
        )}

        {step === 2 && (
          <div className="stack-lg">
            {fraud && (
              <Choices
                legend="Did you share an OTP, PIN or password with anyone around the time of this payment?"
                name="otp"
                value={f.otp_shared}
                options={opts(profile.options.otp_shared)}
                onChange={(v) => set({ otp_shared: v })}
                hint="Please answer honestly — sharing one doesn't stop you raising a dispute."
              />
            )}
            <Choices legend="When did you first notice this payment?" name="noticed" value={f.noticed} options={opts(profile.options.noticed)} onChange={(v) => set({ noticed: v })} />
            {fraud && (
              <>
                <Choices
                  legend="Have you reported this to the national cyber-crime helpline (1930 or cybercrime.gov.in)?"
                  name="cyber"
                  value={f.cyber}
                  options={[
                    { value: "yes", label: "Yes, I have a complaint number" },
                    { value: "not_yet", label: "Not yet" },
                  ]}
                  onChange={(v) => set({ cyber: v as FormState["cyber"] })}
                />
                {f.cyber === "yes" && (
                  <label className="field">
                    <span className="field-label">Complaint (acknowledgement) number</span>
                    <input className="input" value={f.cyber_ref} onChange={(e) => set({ cyber_ref: e.target.value })} maxLength={40} />
                  </label>
                )}
                {f.cyber === "not_yet" && <Note tone="info">Please call 1930 or report at cybercrime.gov.in soon — it helps us ask other banks to hold the money.</Note>}
              </>
            )}
            <label className="field">
              <span className="field-label">In a few sentences, what happened? Use your own words.</span>
              <textarea className="textarea" rows={5} value={f.description} onChange={(e) => set({ description: e.target.value })} maxLength={2000} />
              <span className="small muted">
                {f.description.trim().length < 20 ? `At least 20 characters (${f.description.trim().length} so far).` : `${f.description.length} / 2000`} Never
                include OTPs, PINs, passwords or full card numbers.
              </span>
            </label>
            <Choices legend="How should we contact you?" name="contact" value={f.contact} options={opts(profile.options.contact_preference)} onChange={(v) => set({ contact: v })} />
          </div>
        )}

        {step === 3 && f.payment && (
          <div className="stack-lg">
            <DisputeSummaryCard
              payment={f.payment}
              onChangePayment={() => setStep(0)}
              description={f.description}
              onChangeDescription={() => setStep(2)}
              items={[
                { label: "What happened", value: reason?.label, onChange: () => setStep(1) },
                ...(fraud ? [{ label: "Shared an OTP, PIN or password", value: profile.options.otp_shared[f.otp_shared], onChange: () => setStep(2) }] : []),
                { label: "Noticed", value: profile.options.noticed[f.noticed], onChange: () => setStep(2) },
                ...(fraud ? [{ label: "Cyber-crime complaint", value: f.cyber === "yes" ? f.cyber_ref : "Not reported yet", onChange: () => setStep(2) }] : []),
                { label: "Contact me by", value: profile.options.contact_preference[f.contact], onChange: () => setStep(2) },
              ]}
            >
              <div className="sum-proof">
                <span className="sum-label">Proof (optional, but it helps us check faster)</span>
                <ProofPicker files={proof} onChange={setProof} />
              </div>
            </DisputeSummaryCard>
            <label className="declaration">
              <input type="checkbox" checked={f.declaration} onChange={(e) => set({ declaration: e.target.checked })} />
              <span>The information I have given is true to the best of my knowledge. I understand the bank will look at its records of this payment.</span>
            </label>
          </div>
        )}

        {err && (
          <p className="inline-error" role="alert">
            {err}
          </p>
        )}
        <InlineError error={submit.error} />
        <div className="wizard-actions">
          {step > 0 && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setErr(null);
                setStep(step - 1);
              }}
            >
              Back
            </button>
          )}
          <button type="button" className="btn btn-primary" onClick={next} disabled={submit.isPending}>
            {step < 3 ? "Continue" : submit.isPending ? "Sending…" : "Submit dispute"}
          </button>
        </div>
      </section>
    </div>
  );
}
