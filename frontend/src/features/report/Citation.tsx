import { Eye } from "lucide-react";
import { Popover } from "../../components/Overlay";
import { isGraphId } from "../../lib/labels";
import { humanize } from "../../lib/format";
import type { SnapshotRecord } from "../../types/api";

function renderValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.length ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ") : "—";
  if (typeof v === "object") return JSON.stringify(v);
  if (typeof v === "boolean") return v ? "yes" : "no";
  const str = String(v);
  // Untrusted text is fenced in the snapshot; show the fence in plain words.
  const m = /^<untrusted>([\s\S]*)<\/untrusted>$/.exec(str.trim());
  return m ? `[untrusted, customer-provided] ${m[1]}` : str;
}

export function RecordView({ id, record, strict = true }: { id: string; record: SnapshotRecord | undefined; strict?: boolean }) {
  if (!record)
    return (
      <div className="record-view">
        <p className="popover-heading mono">{id}</p>
        {strict ? (
          <p className="small bad-text">This record is not in the case records, so the sentence that links to it is flagged as possibly wrong.</p>
        ) : (
          <p className="small muted">This record is part of the case, but its details were not included with this answer. Find it on the money trail or timeline.</p>
        )}
      </div>
    );
  const entries = Object.entries(record);
  return (
    <div className="record-view">
      <p className="popover-heading mono">{id}</p>
      <dl className="kv kv-tight">
        {entries.map(([k, v]) => (
          <div className="kv-row" key={k}>
            <dt>{humanize(k)}</dt>
            <dd className={typeof v === "number" ? "num" : ""}>{renderValue(v)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

interface CitationProps {
  id: string;
  record: SnapshotRecord | undefined;
  onShowOnGraph?: (id: string) => void;
  /** When true (reports), a citation without a record is shown as invalid. */
  strict?: boolean;
}

/** A citation chip; clicking opens the cited snapshot record. */
export function Citation({ id, record, onShowOnGraph, strict = true }: CitationProps) {
  const missing = !record && strict;
  return (
    <Popover
      label={`Record ${id}`}
      width={380}
      trigger={(p) => (
        <button type="button" className={`cite-chip ${missing ? "is-missing" : ""}`} {...p} aria-label={`Citation ${id}${missing ? " (not in snapshot)" : ""}. Show record`}>
          {id}
        </button>
      )}
    >
      {(close) => (
        <>
          <RecordView id={id} record={record} strict={strict} />
          {onShowOnGraph && isGraphId(id) && !missing && (record || !strict) && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                close();
                onShowOnGraph(id);
              }}
            >
              <Eye size={14} aria-hidden="true" /> Show on the money trail
            </button>
          )}
        </>
      )}
    </Popover>
  );
}
