import type { ReactNode } from "react";
import { PROVENANCE, PROVENANCE_ORDER, STATUS_LABELS_FALLBACK } from "../lib/labels";
import { formatHours, slaTone } from "../lib/format";
import { Popover } from "./Overlay";

/** Plain-language legend for the five provenance labels, shared by graph, report and chips. */
export function ProvenanceLegend({ compact = false, showLines = true }: { compact?: boolean; showLines?: boolean }) {
  return (
    <ul className={`prov-legend ${compact ? "is-compact" : ""}`} aria-label="What the lines and labels mean">
      {PROVENANCE_ORDER.map((p) => {
        const s = PROVENANCE[p];
        return (
          <li key={p} className="prov-legend-item">
            {showLines ? (
              <svg width="34" height="10" aria-hidden="true" className="prov-legend-line">
                <line
                  x1="1"
                  y1="5"
                  x2="33"
                  y2="5"
                  stroke={`var(--prov-${p})`}
                  strokeWidth={s.strokeWidth + 0.5}
                  strokeDasharray={s.dash}
                  strokeLinecap="round"
                />
              </svg>
            ) : (
              <span className={`prov-swatch prov-swatch-${p}`} aria-hidden="true" />
            )}
            <span>
              <strong>{s.label}:</strong> <span className="muted">{s.meaning.charAt(0).toLowerCase() + s.meaning.slice(1)}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export function PriorityChip({ priority, reasons }: { priority: string; reasons?: string[] }) {
  const chip = (props: Record<string, unknown> = {}) => (
    <button type="button" className={`chip chip-btn prio prio-${priority}`} {...props} aria-label={`Priority ${priority}. Show reasons`}>
      {priority}
    </button>
  );
  if (!reasons?.length) return <span className={`chip prio prio-${priority}`}>{priority}</span>;
  return (
    <Popover label={`Why ${priority}`} trigger={(p) => chip(p)} width={360}>
      <div className="popover-section">
        <p className="popover-heading">Why {priority}</p>
        <ul className="reason-list">
          {reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
        <p className="popover-foot">Priority orders the queue. It is not a judgement on the claim.</p>
      </div>
    </Popover>
  );
}

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  return <span className={`status-badge status-${status}`}>{label ?? STATUS_LABELS_FALLBACK[status] ?? status}</span>;
}

export function SlaRemaining({ hours, label }: { hours: number | null | undefined; label?: string }) {
  const tone = slaTone(hours);
  if (tone === "none") return <span className="muted">—</span>;
  return (
    <span className={`sla sla-${tone}`} title={label}>
      <span className="num">{tone === "breached" ? formatHours(hours) : `${formatHours(hours)} left`}</span>
    </span>
  );
}

export function IdChip({ id, onClick, title }: { id: string; onClick?: () => void; title?: string }) {
  if (onClick)
    return (
      <button type="button" className="id-chip id-chip-btn" onClick={onClick} title={title ?? `Open ${id}`}>
        {id}
      </button>
    );
  return (
    <code className="id-chip" title={title}>
      {id}
    </code>
  );
}

export function IdList({ ids, onSelect }: { ids: string[]; onSelect?: (id: string) => void }) {
  if (!ids.length) return <span className="muted">none</span>;
  return (
    <span className="id-list">
      {ids.map((id) => (
        <IdChip key={id} id={id} onClick={onSelect ? () => onSelect(id) : undefined} />
      ))}
    </span>
  );
}

export function SectionTitle({ children, actions }: { children: ReactNode; actions?: ReactNode }) {
  return (
    <div className="section-title">
      <h2>{children}</h2>
      {actions && <div className="section-actions">{actions}</div>}
    </div>
  );
}
