import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Briefcase, Network, ListChecks, Activity, LogOut, Menu, X } from "lucide-react";
import { useAuth } from "../auth/AuthProvider";
import { ThemeToggle } from "../../lib/theme";
import { SyntheticBanner } from "../../components/Domain";
import { Logo } from "./Logo";

const NAV = [
  { to: "/cases", label: "Cases", icon: Briefcase },
  { to: "/network", label: "Network", icon: Network },
  { to: "/rules", label: "Rules", icon: ListChecks },
  { to: "/ops", label: "AI Ops", icon: Activity },
];

export default function AppShell() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => setMenuOpen(false), [loc.pathname]);

  const doLogout = async () => {
    await logout();
    nav("/login", { replace: true });
  };

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <SyntheticBanner />
      <header className="topbar">
        <button
          type="button"
          className="icon-btn nav-toggle"
          aria-label={menuOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={menuOpen}
          aria-controls="primary-nav"
          onClick={() => setMenuOpen((o) => !o)}
        >
          {menuOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
        <NavLink to="/cases" className="brand" aria-label="FundTrace home">
          <Logo size={26} />
          <span className="brand-name">FundTrace</span>
        </NavLink>
        <div className="topbar-spacer" />
        {user && (
          <div className="user-chip" title={user.full_name}>
            <span className="avatar" aria-hidden="true">
              {user.full_name.charAt(0)}
            </span>
            <span className="user-meta">
              <span className="user-name">{user.full_name.replace(" (synthetic)", "")}</span>
              <span className={`role-tag role-${user.role}`}>{user.role}</span>
            </span>
          </div>
        )}
        <ThemeToggle />
        <button type="button" className="icon-btn" onClick={doLogout} aria-label="Sign out" title="Sign out">
          <LogOut size={18} />
        </button>
      </header>
      <div className="shell-body">
        <nav id="primary-nav" className={`sidenav ${menuOpen ? "is-open" : ""}`} aria-label="Primary">
          <ul>
            {NAV.map(({ to, label, icon: Icon }) => (
              <li key={to}>
                <NavLink to={to} className={({ isActive }) => `navlink ${isActive ? "is-active" : ""}`}>
                  <Icon size={18} aria-hidden="true" />
                  <span>{label}</span>
                </NavLink>
              </li>
            ))}
          </ul>
          <p className="sidenav-foot">Signals prompt review; they are never verdicts. The investigator decides.</p>
        </nav>
        {menuOpen && <div className="nav-scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" />}
        <main id="main" className="main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
