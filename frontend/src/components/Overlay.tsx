import { useEffect, useId, useRef, useState, type ReactNode, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", h);
    return () => document.removeEventListener("keydown", h);
  }, [open, onClose]);
}

const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

function trapTab(e: ReactKeyboardEvent<HTMLElement>, root: HTMLElement | null) {
  if (e.key !== "Tab" || !root) return;
  const items = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE));
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

/* ------------------------------------------------------------------ Popover */
interface PopoverProps {
  trigger: (props: { onClick: () => void; "aria-expanded": boolean; "aria-controls": string; "aria-haspopup": "dialog" }) => ReactNode;
  children: ReactNode | ((close: () => void) => ReactNode);
  label: string;
  align?: "start" | "end";
  className?: string;
  width?: number;
}

export function Popover({ trigger, children, label, align = "start", className = "", width = 340 }: PopoverProps) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const wrap = useRef<HTMLSpanElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const close = () => setOpen(false);
  useEscape(open, close);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", h);
    panel.current?.focus();
    return () => document.removeEventListener("mousedown", h);
  }, [open]);
  return (
    <span className={`popover-wrap ${className}`} ref={wrap}>
      {trigger({ onClick: () => setOpen((o) => !o), "aria-expanded": open, "aria-controls": id, "aria-haspopup": "dialog" })}
      {open && (
        <div
          id={id}
          ref={panel}
          role="dialog"
          aria-label={label}
          tabIndex={-1}
          className={`popover popover-${align}`}
          style={{ width: `min(${width}px, calc(100vw - 32px))` }}
        >
          {typeof children === "function" ? children(close) : children}
        </div>
      )}
    </span>
  );
}

/* ------------------------------------------------------------------ Drawer */
interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  subtitle?: ReactNode;
}

export function Drawer({ open, onClose, title, subtitle, children }: DrawerProps) {
  const ref = useRef<HTMLElement>(null);
  const titleId = useId();
  useEscape(open, onClose);
  useEffect(() => {
    if (open) ref.current?.focus();
  }, [open]);
  if (!open) return null;
  return (
    <aside className="drawer" ref={ref} tabIndex={-1} role="complementary" aria-labelledby={titleId}>
      <header className="drawer-head">
        <div>
          <h3 id={titleId} className="drawer-title">
            {title}
          </h3>
          {subtitle && <div className="drawer-subtitle">{subtitle}</div>}
        </div>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close details">
          <X size={18} />
        </button>
      </header>
      <div className="drawer-body">{children}</div>
    </aside>
  );
}

/* ------------------------------------------------------------------ Modal */
interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
  description?: ReactNode;
}

export function Modal({ open, onClose, title, children, footer, size = "md", description }: ModalProps) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const prevFocus = useRef<HTMLElement | null>(null);
  useEscape(open, onClose);
  useEffect(() => {
    if (!open) return;
    prevFocus.current = document.activeElement as HTMLElement | null;
    const first = ref.current?.querySelector<HTMLElement>("textarea, input, select, button:not(.icon-btn)");
    (first ?? ref.current)?.focus();
    return () => prevFocus.current?.focus?.();
  }, [open]);
  if (!open) return null;
  return createPortal(
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={`modal modal-${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        ref={ref}
        tabIndex={-1}
        onKeyDown={(e) => trapTab(e, ref.current)}
      >
        <header className="modal-head">
          <h2 id={titleId} className="modal-title">
            {title}
          </h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close dialog">
            <X size={18} />
          </button>
        </header>
        {description && <p className="modal-desc">{description}</p>}
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}
