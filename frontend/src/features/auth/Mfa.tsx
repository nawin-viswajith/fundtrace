import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../../api/endpoints";
import { InlineError, Note, Skeleton } from "../../components/Primitives";
import { Modal } from "../../components/Overlay";
import type { MfaSetup, User } from "../../types/api";
import { useAuth } from "./AuthProvider";

/** Six-digit authenticator code, or a recovery code when `allowRecovery`. */
export function MfaCodeForm({
  onSubmit,
  busy,
  error,
  allowRecovery = true,
  submitLabel = "Verify",
  autoFocus = true,
}: {
  onSubmit: (code: string) => void;
  busy: boolean;
  error: unknown;
  allowRecovery?: boolean;
  submitLabel?: string;
  autoFocus?: boolean;
}) {
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const valid = recovery ? code.replace(/[^a-z0-9]/gi, "").length === 10 : /^\d{6}$/.test(code.replace(/\s/g, ""));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (valid) onSubmit(code.trim());
  };
  return (
    <form onSubmit={submit} noValidate>
      <label className="field">
        <span className="field-label">{recovery ? "Recovery code" : "6-digit code from your authenticator app"}</span>
        <input
          className="input input-code num"
          inputMode={recovery ? "text" : "numeric"}
          autoComplete="one-time-code"
          placeholder={recovery ? "xxxxx-xxxxx" : "000000"}
          maxLength={recovery ? 11 : 7}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          autoFocus={autoFocus}
          name="code"
        />
      </label>
      <InlineError error={error} />
      <button type="submit" className="btn btn-primary btn-block" disabled={busy || !valid}>
        {busy ? "Checking…" : submitLabel}
      </button>
      {allowRecovery && (
        <button
          type="button"
          className="btn btn-ghost btn-block btn-sm"
          onClick={() => {
            setRecovery((r) => !r);
            setCode("");
          }}
        >
          {recovery ? "Use the authenticator app instead" : "Lost your phone? Use a recovery code"}
        </button>
      )}
    </form>
  );
}

/** Set up an authenticator app: QR code / setup key, then confirm with a code. */
export function MfaEnrol({ mfaToken, onEnabled }: { mfaToken?: string; onEnabled: (user: User, codes: string[]) => void }) {
  const [setup, setSetup] = useState<MfaSetup | null>(null);
  const [setupError, setSetupError] = useState<unknown>(null);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return; // one secret per enrolment (React strict mode mounts twice)
    started.current = true;
    api.mfaSetup(mfaToken).then(setSetup, setSetupError);
  }, [mfaToken]);
  const enable = useMutation({
    mutationFn: (code: string) => api.mfaEnable(code, mfaToken),
    onSuccess: (r) => onEnabled(r.user, r.recovery_codes),
  });
  if (setupError) return <InlineError error={setupError} />;
  if (!setup) return <Skeleton lines={4} />;
  const key = setup.secret.match(/.{1,4}/g)?.join(" ") ?? setup.secret;
  return (
    <div className="mfa-enrol">
      <ol className="mfa-steps">
        <li>
          Scan this code with an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password…).
          {setup.qr_svg && <img className="mfa-qr" src={setup.qr_svg} alt="QR code for your authenticator app" width={180} height={180} />}
          <span className="small muted">
            Can't scan? Enter this key: <code className="mfa-key">{key}</code>{" "}
            <a className="link small" href={setup.otpauth_uri}>
              open in app
            </a>
          </span>
        </li>
        <li>Enter the 6-digit code the app shows.</li>
      </ol>
      <MfaCodeForm onSubmit={(c) => enable.mutate(c)} busy={enable.isPending} error={enable.error} allowRecovery={false} submitLabel="Turn on MFA" />
    </div>
  );
}

/** Shown once: the user must keep these somewhere safe. */
export function RecoveryCodes({ codes, onDone, doneLabel = "I've saved them" }: { codes: string[]; onDone: () => void; doneLabel?: string }) {
  const [copied, setCopied] = useState(false);
  const text = codes.join("\n");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([`FundTrace recovery codes (each works once)\n\n${text}\n`], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "fundtrace-recovery-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="recovery">
      <Note tone="warn">
        <strong>Save these recovery codes now.</strong> Each works once if you lose your phone. They will not be shown again.
      </Note>
      <ul className="recovery-codes mono" aria-label="Recovery codes">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      <div className="inline-actions">
        <button type="button" className="btn btn-secondary btn-sm" onClick={copy}>
          {copied ? "Copied" : "Copy"}
        </button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={download}>
          Download .txt
        </button>
      </div>
      <button type="button" className="btn btn-primary btn-block" onClick={onDone}>
        {doneLabel}
      </button>
    </div>
  );
}

type Panel = "status" | "enrol" | "codes" | "disable" | "regenerate";

/** Account security: turn MFA on or off, replace recovery codes. */
export function SecurityDialog({ onClose }: { onClose: () => void }) {
  const { user, setSessionUser } = useAuth();
  const [panel, setPanel] = useState<Panel>("status");
  const [codes, setCodes] = useState<string[]>([]);
  const [password, setPassword] = useState("");
  const disable = useMutation({
    mutationFn: (code: string) => api.mfaDisable(password, code),
    onSuccess: (r) => {
      setSessionUser(r.user);
      setPanel("status");
    },
  });
  const regenerate = useMutation({
    mutationFn: (code: string) => api.mfaNewRecoveryCodes(code),
    onSuccess: (r) => {
      setCodes(r.recovery_codes);
      setPanel("codes");
    },
  });
  if (!user) return null;
  return (
    <Modal open onClose={onClose} title="Account security" size="sm" description={`${user.username} · ${user.role}`}>
      {panel === "status" && (
        <div className="stack">
          <div className="kv-row">
            <span>Two-step sign-in (MFA)</span>
            <strong>{user.mfa_enabled ? "On" : "Off"}</strong>
          </div>
          {user.mfa_required && <p className="small muted">Required for your role.</p>}
          {!user.mfa_enabled ? (
            <>
              <p className="small muted">After your password, you'll also enter a code from an authenticator app on your phone.</p>
              <button type="button" className="btn btn-primary" onClick={() => setPanel("enrol")}>
                Set up authenticator app
              </button>
            </>
          ) : (
            <div className="inline-actions">
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPanel("regenerate")}>
                New recovery codes
              </button>
              {!user.mfa_required && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPanel("disable")}>
                  Turn off MFA
                </button>
              )}
            </div>
          )}
        </div>
      )}
      {panel === "enrol" && (
        <MfaEnrol
          onEnabled={(u, c) => {
            setSessionUser(u);
            setCodes(c);
            setPanel("codes");
          }}
        />
      )}
      {panel === "codes" && <RecoveryCodes codes={codes} onDone={() => setPanel("status")} doneLabel="Done" />}
      {panel === "regenerate" && (
        <div className="stack">
          <p className="small muted">Your old recovery codes stop working.</p>
          <MfaCodeForm onSubmit={(c) => regenerate.mutate(c)} busy={regenerate.isPending} error={regenerate.error} allowRecovery={false} submitLabel="Replace codes" />
        </div>
      )}
      {panel === "disable" && (
        <div className="stack">
          <label className="field">
            <span className="field-label">Password</span>
            <input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <MfaCodeForm onSubmit={(c) => disable.mutate(c)} busy={disable.isPending} error={disable.error} submitLabel="Turn off MFA" autoFocus={false} />
        </div>
      )}
    </Modal>
  );
}
