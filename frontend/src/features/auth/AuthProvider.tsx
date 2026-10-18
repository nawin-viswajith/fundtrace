import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/endpoints";
import { ApiError, UNAUTHORIZED_EVENT } from "../../api/client";
import type { LoginResult, User } from "../../types/api";
import { LoadingBlock } from "../../components/Primitives";

interface AuthState {
  user: User | null;
  status: "loading" | "ready";
  /** First factor. Returns the session user, or the second step the server asks for. */
  login: (username: string, password: string) => Promise<LoginResult>;
  loginWithFirebase: (idToken: string) => Promise<LoginResult>;
  /** Called once the second step (MFA code or enrolment) opened a session, or when the user's MFA state changes. */
  setSessionUser: (user: User) => void;
  logout: () => Promise<void>;
  sessionExpired: boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<"loading" | "ready">("loading");
  const [sessionExpired, setSessionExpired] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .me()
      .then((r) => alive && setUser(r.user))
      .catch((e) => {
        if (!(e instanceof ApiError) || e.status !== 401) console.warn("session probe failed", e);
      })
      .finally(() => alive && setStatus("ready"));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const h = () => {
      setUser((u) => {
        if (u) setSessionExpired(true);
        return null;
      });
      qc.clear();
    };
    window.addEventListener(UNAUTHORIZED_EVENT, h);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, h);
  }, [qc]);

  const setSessionUser = useCallback(
    (u: User) => {
      qc.clear();
      setSessionExpired(false);
      setUser(u);
    },
    [qc],
  );

  const login = useCallback(
    async (username: string, password: string) => {
      const r = await api.login(username, password);
      if ("user" in r) setSessionUser(r.user);
      return r;
    },
    [setSessionUser],
  );

  const loginWithFirebase = useCallback(
    async (idToken: string) => {
      const r = await api.firebaseLogin(idToken);
      if ("user" in r) setSessionUser(r.user);
      return r;
    },
    [setSessionUser],
  );

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
      qc.clear();
    }
  }, [qc]);

  const value = useMemo(
    () => ({ user, status, login, loginWithFirebase, setSessionUser, logout, sessionExpired }),
    [user, status, login, loginWithFirebase, setSessionUser, logout, sessionExpired],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export function useUser(): User {
  const { user } = useAuth();
  if (!user) throw new Error("No user");
  return user;
}

export const canSupervise = (u: User | null) => !!u && (u.role === "supervisor" || u.role === "admin");

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, status } = useAuth();
  const loc = useLocation();
  if (status === "loading")
    return (
      <div className="boot">
        <LoadingBlock label="Checking session" lines={3} />
      </div>
    );
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  if (user.role === "customer") return <Navigate to="/portal" replace />; // bank customers only see the portal
  return <>{children}</>;
}
