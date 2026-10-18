import { Link, Outlet, useNavigate } from "react-router-dom";
import { LogOut } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { ThemeToggle } from "../../lib/theme";

/** Layout for bank customers: a simple, friendly frame for raising and following disputes. */
export default function PortalShell() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const signOut = async () => {
    await logout();
    nav("/login", { replace: true });
  };
  return (
    <div className="portal">
      <header className="portal-top">
        <Link to="/portal" className="portal-brand" aria-label="Demo Bank customer help, home">
          <span className="portal-logo" aria-hidden="true">
            DB
          </span>
          <span>
            <strong>Demo Bank</strong>
            <span className="portal-brand-sub">Help with a payment</span>
          </span>
        </Link>
        <Link to="/portal/help" className="icon-btn portal-help-link">
          Help
        </Link>
        <span className="portal-user">{user?.full_name.replace(/\s*\(synthetic\)\s*$/i, "")}</span>
        <ThemeToggle />
        <button type="button" className="icon-btn" onClick={signOut} aria-label="Sign out" title="Sign out">
          <LogOut size={18} />
        </button>
      </header>
      <main className="portal-main" id="main">
        <Outlet />
      </main>
      <footer className="portal-foot">
        <p>
          Demo Bank never asks for your OTP, PIN or password. If someone does, it is a scam — call the national cyber-crime helpline on 1930.
        </p>
        <button type="button" className="link-btn small" onClick={signOut}>
          Switch to the bank's dispute team view (sign out)
        </button>
      </footer>
    </div>
  );
}
