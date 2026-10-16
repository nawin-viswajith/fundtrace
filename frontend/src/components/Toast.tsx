import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { CheckCircle2, AlertTriangle, Info, X } from "lucide-react";

type ToastTone = "good" | "bad" | "neutral";
interface ToastItem {
  id: number;
  text: string;
  tone: ToastTone;
}
interface ToastApi {
  show: (text: string, tone?: ToastTone) => void;
}

const Ctx = createContext<ToastApi>({ show: () => undefined });

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);
  const dismiss = (id: number) => setItems((xs) => xs.filter((x) => x.id !== id));
  const show = useCallback((text: string, tone: ToastTone = "good") => {
    const id = ++seq.current;
    setItems((xs) => [...xs.slice(-3), { id, text, tone }]);
    window.setTimeout(() => dismiss(id), tone === "bad" ? 7000 : 4000);
  }, []);
  const api = useMemo(() => ({ show }), [show]);
  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="toasts" aria-live="polite" aria-atomic="false">
        {items.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone}`} role={t.tone === "bad" ? "alert" : "status"}>
            {t.tone === "bad" ? <AlertTriangle size={16} aria-hidden="true" /> : t.tone === "neutral" ? <Info size={16} aria-hidden="true" /> : <CheckCircle2 size={16} aria-hidden="true" />}
            <span>{t.text}</span>
            <button type="button" className="icon-btn icon-btn-sm" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
