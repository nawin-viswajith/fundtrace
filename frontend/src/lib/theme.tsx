import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Moon, Sun } from "lucide-react";

export type Theme = "light" | "dark";
const KEY = "ft-theme";

/** Light is the product default; an explicit choice (stored) always wins. */
export const DEFAULT_THEME: Theme = "light";

export function readStoredTheme(): Theme | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

interface ThemeApi {
  theme: Theme;
  toggle: () => void;
}
const Ctx = createContext<ThemeApi>({ theme: DEFAULT_THEME, toggle: () => undefined });

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme() ?? DEFAULT_THEME);
  const [explicit, setExplicit] = useState<boolean>(() => readStoredTheme() !== null);

  // Tokens default to light on :root; data-theme is only written once the user has chosen.
  useEffect(() => {
    if (explicit) document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
  }, [theme, explicit]);

  const toggle = useCallback(() => {
    setTheme((t) => {
      const next: Theme = t === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch {
        /* storage unavailable: the theme still applies for this session */
      }
      return next;
    });
    setExplicit(true);
  }, []);

  const api = useMemo(() => ({ theme, toggle }), [theme, toggle]);
  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button type="button" className="icon-btn" onClick={toggle} aria-label={`Switch to ${next} theme`} title={`Switch to ${next} theme`}>
      {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}
