import type { ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { errorMessage } from "../api/client";
import { formatIST, formatMoney, formatMoneyRange, formatUTC } from "../lib/format";

export function Money({ minor, currency = "INR", className = "" }: { minor: number | null | undefined; currency?: string; className?: string }) {
  return <span className={`num ${className}`}>{formatMoney(minor, currency)}</span>;
}

export function MoneyRange({ min, max, currency = "INR" }: { min: number | null | undefined; max: number | null | undefined; currency?: string }) {
  return <span className="num">{formatMoneyRange(min, max, currency)}</span>;
}

/** IST on screen, UTC on hover. */
export function Time({ iso, seconds, dateOnly, className = "" }: { iso: string | null | undefined; seconds?: boolean; dateOnly?: boolean; className?: string }) {
  if (!iso) return <span className="muted">—</span>;
  return (
    <time dateTime={iso} title={formatUTC(iso)} className={`num ${className}`}>
      {formatIST(iso, { seconds, dateOnly })}
    </time>
  );
}

interface CardProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
  id?: string;
}

export function Card({ title, subtitle, actions, children, className = "", as = "section", id }: CardProps) {
  const Tag = as;
  return (
    <Tag className={`card ${className}`} id={id} aria-label={typeof title === "string" ? title : undefined}>
      {(title || actions) && (
        <header className="card-head">
          <div className="card-titles">
            {title && <h3 className="card-title">{title}</h3>}
            {subtitle && <p className="card-subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </Tag>
  );
}

export function EmptyState({ title, children, icon, action }: { title: string; children?: ReactNode; icon?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty-state" role="status">
      {icon && (
        <div className="empty-icon" aria-hidden="true">
          {icon}
        </div>
      )}
      <p className="empty-title">{title}</p>
      {children && <div className="empty-body">{children}</div>}
      {action && <div className="empty-action">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry, title = "Couldn't load this" }: { error: unknown; onRetry?: () => void; title?: string }) {
  return (
    <div className="error-state" role="alert">
      <AlertTriangle size={20} aria-hidden="true" />
      <div>
        <p className="error-title">{title}</p>
        <p className="error-body">{errorMessage(error)}</p>
      </div>
      {onRetry && (
        <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function InlineError({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p className="inline-error" role="alert">
      <AlertTriangle size={14} aria-hidden="true" /> {errorMessage(error)}
    </p>
  );
}

export function Skeleton({ lines = 3, height, className = "" }: { lines?: number; height?: number; className?: string }) {
  if (height) return <div className={`skeleton ${className}`} style={{ height }} aria-hidden="true" />;
  return (
    <div className={`skeleton-stack ${className}`} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton skeleton-line" style={{ width: `${92 - ((i * 17) % 40)}%` }} />
      ))}
    </div>
  );
}

export function LoadingBlock({ label = "Loading", lines = 4 }: { label?: string; lines?: number }) {
  return (
    <div className="loading-block" role="status" aria-live="polite">
      <span className="sr-only">{label}…</span>
      <Skeleton lines={lines} />
    </div>
  );
}

export function Spinner({ size = 16, label }: { size?: number; label?: string }) {
  return (
    <span className="spinner-wrap" role={label ? "status" : undefined}>
      <span className="spinner" style={{ width: size, height: size }} aria-hidden="true" />
      {label && <span className="sr-only">{label}</span>}
    </span>
  );
}

export function Note({ children, tone = "neutral", icon }: { children: ReactNode; tone?: "neutral" | "warn" | "bad" | "info" | "good"; icon?: ReactNode }) {
  return (
    <div className={`note note-${tone}`}>
      {icon && <span className="note-icon" aria-hidden="true">{icon}</span>}
      <div>{children}</div>
    </div>
  );
}

export function KeyValues({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([k, v], i) => (
        <div className="kv-row" key={i}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Meter({ value, max = 1, tone = "accent", label }: { value: number; max?: number; tone?: string; label: string }) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100));
  return (
    <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-label={label}>
      <div className={`meter-fill meter-${tone}`} style={{ width: `${pct}%` }} />
    </div>
  );
}
