import { useEffect, useState } from "react";
import { useTheme } from "./theme";

/** Resolve CSS custom properties to concrete colours (SVG attributes can't use var()). Re-reads on theme change. */
export function useCssVars<K extends string>(names: Record<K, [string, string]>): Record<K, string> {
  const { theme } = useTheme();
  const read = (): Record<K, string> => {
    const out = {} as Record<K, string>;
    let cs: CSSStyleDeclaration | null = null;
    try {
      cs = getComputedStyle(document.documentElement);
    } catch {
      cs = null;
    }
    for (const k of Object.keys(names) as K[]) {
      const [v, fallback] = names[k];
      out[k] = cs?.getPropertyValue(v).trim() || fallback;
    }
    return out;
  };
  const [vals, setVals] = useState<Record<K, string>>(read);
  useEffect(() => {
    const t = window.setTimeout(() => setVals(read()), 0);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);
  return vals;
}
