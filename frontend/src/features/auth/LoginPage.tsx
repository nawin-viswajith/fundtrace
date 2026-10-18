import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { useAuth } from "./AuthProvider";
import { useAuthConfig } from "../../api/hooks";
import { api } from "../../api/endpoints";
import { errorMessage } from "../../api/client";
import { ThemeToggle } from "../../lib/theme";
import { Skeleton } from "../../components/Primitives";
import { Logo } from "../shell/Logo";
import type { FirebaseWebConfig, LoginResult, User } from "../../types/api";
import { MfaCodeForm, MfaEnrol, RecoveryCodes } from "./Mfa";
import { firebaseErrorMessage, googleIdToken } from "./firebase";

type Step =
  | { kind: "password" }
  | { kind: "mfa"; token: string }
  | { kind: "enrol"; token: string }
  | { kind: "codes"; codes: string[]; user: User };

export default function LoginPage() {
  const { user, login, loginWithFirebase, setSessionUser, sessionExpired } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const requested = (loc.state as { from?: string } | null)?.from;
  const homeFor = (u: User | null) =>
    u?.role === "customer" ? (requested?.startsWith("/portal") ? requested : "/portal") : requested && !requested.startsWith("/portal") ? requested : "/overview";
  const from = homeFor(user);
  const cfg = useAuthConfig();
  const [step, setStep] = useState<Step>({ kind: "password" });
  const [notice, setNotice] = useState<string | null>(null);

  // While recovery codes are on screen the session already exists; stay here until they are acknowledged.
  if (user && step.kind !== "codes") return <Navigate to={from} replace />;

  const next = (r: LoginResult) => {
    if ("user" in r) nav(homeFor(r.user), { replace: true });
    else if ("mfa_required" in r) setStep({ kind: "mfa", token: r.mfa_token });
    else setStep({ kind: "enrol", token: r.mfa_token });
  };
  const restart = () => {
    setStep({ kind: "password" });
    setNotice(null);
  };

  return (
    <div className="login-page">
      <div className="login-topbar">
        <ThemeToggle />
      </div>
      <div className="login-grid">
        <section className="login-intro" aria-labelledby="product-name">
          <Logo size={32} />
          <h1 id="product-name" className="login-product">
            FundTrace
          </h1>
          <p className="login-tagline">Follow the money, show the proof, mark the guesses.</p>
          <p className="login-lede">
            Reconstruct a disputed payment's trail, see the evidence behind every signal, and review an AI report in which every claim cites a
            record. The investigator decides.
          </p>
        </section>

        <section className="login-card card" aria-labelledby="signin-title">
          {step.kind === "password" && (
            <>
              <h2 id="signin-title" className="login-card-title">
                Sign in
              </h2>
              <p className="synthetic-notice small" role="note">
                <strong>Synthetic data only.</strong> Nothing here comes from a real bank.
              </p>
              {sessionExpired && <p className="inline-note">Your session ended. Please sign in again.</p>}
              <PasswordStep onResult={next} login={login} cfg={cfg} />
              {cfg.data?.firebase && <GoogleButton onToken={async (t) => next(await loginWithFirebase(t))} config={cfg.data.firebase} />}
            </>
          )}

          {step.kind === "mfa" && (
            <>
              <h2 id="signin-title" className="login-card-title">
                Two-step verification
              </h2>
              <MfaVerify
                token={step.token}
                onDone={(u, left) => {
                  setSessionUser(u);
                  if (left !== null && left <= 3) setNotice(`Recovery code used. ${left} left — create new ones under Account security.`);
                }}
              />
              {notice && <p className="inline-note">{notice}</p>}
              <button type="button" className="btn btn-ghost btn-sm btn-block" onClick={restart}>
                Back to sign in
              </button>
            </>
          )}

          {step.kind === "enrol" && (
            <>
              <h2 id="signin-title" className="login-card-title">
                Set up two-step verification
              </h2>
              <p className="small muted">Your role requires an authenticator app. This takes about a minute.</p>
              <MfaEnrol mfaToken={step.token} onEnabled={(u, codes) => setStep({ kind: "codes", codes, user: u })} />
              <button type="button" className="btn btn-ghost btn-sm btn-block" onClick={restart}>
                Back to sign in
              </button>
            </>
          )}

          {step.kind === "codes" && (
            <>
              <h2 id="signin-title" className="login-card-title">
                Recovery codes
              </h2>
              <RecoveryCodes
                codes={step.codes}
                onDone={() => {
                  setSessionUser(step.user);
                  nav(homeFor(step.user), { replace: true });
                }}
                doneLabel="I've saved them — continue"
              />
            </>
          )}
        </section>
      </div>
    </div>
  );
}

function PasswordStep({
  onResult,
  login,
  cfg,
}: {
  onResult: (r: LoginResult) => void;
  login: (u: string, p: string) => Promise<LoginResult>;
  cfg: ReturnType<typeof useAuthConfig>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!username.trim() || !password) {
      setError("Enter a username and password.");
      return;
    }
    setBusy(true);
    try {
      onResult(await login(username.trim(), password));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const fill = (u: string) => {
    setUsername(u);
    if (cfg.data?.demo_password) setPassword(cfg.data.demo_password);
    setError(null);
  };

  return (
    <>
      <form onSubmit={submit} noValidate>
        <label className="field">
          <span className="field-label">Username</span>
          <input className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus name="username" />
        </label>
        <label className="field">
          <span className="field-label">Password</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            name="password"
          />
        </label>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <div className="demo-accounts">
        <p className="demo-title">Demo accounts</p>
        {cfg.isLoading && <Skeleton lines={2} />}
        {cfg.data && (
          <>
            <ul className="demo-list">
              {cfg.data.demo_users.map((u) => (
                <li key={u.username}>
                  <button type="button" className="demo-user" onClick={() => fill(u.username)} aria-label={`Fill in ${u.username}`}>
                    <code>{u.username}</code>
                    <span className={`role-tag role-${u.role}`}>{u.role}</span>
                  </button>
                </li>
              ))}
            </ul>
            {cfg.data.demo_customers && cfg.data.demo_customers.length > 0 && (
              <>
                <p className="demo-title demo-title-sub">Bank customers (raise and follow a dispute)</p>
                <ul className="demo-list">
                  {cfg.data.demo_customers.map((u) => (
                    <li key={u.username}>
                      <button type="button" className="demo-user" onClick={() => fill(u.username)} aria-label={`Fill in ${u.username}`}>
                        <code>{u.username}</code>
                        <span className="role-tag role-customer">customer</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {cfg.data.demo_password ? (
              <p className="demo-pw">
                Password for all: <code>{cfg.data.demo_password}</code>
              </p>
            ) : (
              <p className="demo-pw muted">Ask the presenter for the demo password.</p>
            )}
          </>
        )}
        {cfg.isError && <p className="muted">Demo account list unavailable.</p>}
      </div>
    </>
  );
}

function MfaVerify({ token, onDone }: { token: string; onDone: (u: User, recoveryLeft: number | null) => void }) {
  const verify = useMutation({
    mutationFn: (code: string) => api.mfaVerify(token, code),
    onSuccess: (r) => onDone(r.user, r.recovery_codes_left),
  });
  return <MfaCodeForm onSubmit={(c) => verify.mutate(c)} busy={verify.isPending} error={verify.error} />;
}

function GoogleButton({ config, onToken }: { config: FirebaseWebConfig; onToken: (t: string) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const click = async () => {
    setBusy(true);
    setError(null);
    let token: string;
    try {
      token = await googleIdToken(config);
    } catch (e) {
      setError(firebaseErrorMessage(e));
      setBusy(false);
      return;
    }
    try {
      await onToken(token);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="login-alt">
      <div className="divider-text" role="separator">
        <span>or</span>
      </div>
      <button type="button" className="btn btn-secondary btn-block" onClick={click} disabled={busy}>
        {busy ? "Waiting for Google…" : "Sign in with Google"}
      </button>
      {error && (
        <p className="inline-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
