import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { LogIn, ShieldAlert, Route as RouteIcon, FileCheck2, Scale } from "lucide-react";
import { useAuth } from "./AuthProvider";
import { useAuthConfig } from "../../api/hooks";
import { errorMessage } from "../../api/client";
import { ThemeToggle } from "../../lib/theme";
import { Skeleton } from "../../components/Primitives";
import { Logo } from "../shell/Logo";
import { SyntheticBanner } from "../../components/Domain";

export default function LoginPage() {
  const { user, login, sessionExpired } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const from = (loc.state as { from?: string } | null)?.from ?? "/overview";
  const cfg = useAuthConfig();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (user) return <Navigate to={from} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!username.trim() || !password) {
      setError("Enter a username and password.");
      return;
    }
    setBusy(true);
    try {
      await login(username.trim(), password);
      nav(from, { replace: true });
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
    <div className="login-page">
      <SyntheticBanner />
      <div className="login-topbar">
        <ThemeToggle />
      </div>
      <div className="login-grid">
        <section className="login-intro" aria-labelledby="product-name">
          <Logo size={40} />
          <h1 id="product-name" className="login-product">
            FundTrace
          </h1>
          <p className="login-tagline">Follow the money, show the proof, mark the guesses.</p>
          <p className="login-lede">
            AI-assisted dispute investigation: reconstruct a disputed payment's observable trail, see the evidence behind every
            signal, and review a report in which every claim cites a record.
          </p>
          <ul className="login-points">
            <li>
              <RouteIcon size={18} aria-hidden="true" /> Traceable-amount ranges, not "amounts add up"
            </li>
            <li>
              <FileCheck2 size={18} aria-hidden="true" /> Every AI claim linked to a source record and fact-checked
            </li>
            <li>
              <Scale size={18} aria-hidden="true" /> Signals for review — the investigator decides
            </li>
          </ul>
        </section>

        <section className="login-card card" aria-labelledby="signin-title">
          <h2 id="signin-title" className="login-card-title">
            Sign in
          </h2>
          <div className="synthetic-notice" role="note">
            <ShieldAlert size={16} aria-hidden="true" />
            <span>
              <strong>Synthetic data only.</strong> Every customer, account and transaction here is generated for this demo. Nothing comes
              from a real bank.
            </span>
          </div>
          {sessionExpired && <p className="inline-note">Your session ended. Please sign in again.</p>}
          <form onSubmit={submit} noValidate>
            <label className="field">
              <span className="field-label">Username</span>
              <input
                className="input"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoFocus
                name="username"
              />
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
              <LogIn size={16} aria-hidden="true" />
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
        </section>
      </div>
    </div>
  );
}
