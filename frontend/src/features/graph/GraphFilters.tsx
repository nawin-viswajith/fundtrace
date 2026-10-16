import type { GraphQueryParams, TxnStatus } from "../../types/api";
import { humanize } from "../../lib/format";

const WINDOWS = [
  { v: 24, label: "24 hours" },
  { v: 72, label: "3 days" },
  { v: 168, label: "7 days" },
  { v: 720, label: "30 days" },
];
const STATUSES: TxnStatus[] = ["posted", "pending", "failed", "reversed"];
const DEFAULT_RELS = ["sent", "received_by", "possible_onward_funding", "reversal_of", "supports", "contradicts", "relates_to"];

interface Props {
  value: GraphQueryParams;
  onChange: (p: GraphQueryParams) => void;
  relations?: string[];
  maxDepth?: number;
}

function toggle<T>(arr: T[], v: T): T[] {
  return arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v];
}

export function GraphFilters({ value, onChange, relations = DEFAULT_RELS, maxDepth = 5 }: Props) {
  const set = (patch: Partial<GraphQueryParams>) => onChange({ ...value, ...patch });
  return (
    <div className="graph-filters" role="group" aria-label="Trail filters">
      <fieldset className="seg">
        <legend className="field-label">Direction</legend>
        <div className="seg-buttons">
          {(["backward", "both", "forward"] as const).map((d) => (
            <label key={d} className={`seg-btn ${value.direction === d ? "is-active" : ""}`}>
              <input type="radio" name="direction" value={d} checked={value.direction === d} onChange={() => set({ direction: d })} />
              {d === "backward" ? "Backward" : d === "forward" ? "Forward" : "Both"}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="field field-inline">
        <span className="field-label">Depth</span>
        <select className="select select-sm" value={value.depth} onChange={(e) => set({ depth: Number(e.target.value) })}>
          {Array.from({ length: maxDepth }, (_, i) => i + 1).map((d) => (
            <option key={d} value={d}>
              {d} hop{d > 1 ? "s" : ""}
            </option>
          ))}
        </select>
      </label>
      <label className="field field-inline">
        <span className="field-label">Window</span>
        <select className="select select-sm" value={value.window_hours} onChange={(e) => set({ window_hours: Number(e.target.value) })}>
          {WINDOWS.map((w) => (
            <option key={w.v} value={w.v}>
              {w.label}
            </option>
          ))}
        </select>
      </label>
      <details className="more-filters">
        <summary>
          Status &amp; relationship filters
          {value.status.length + value.rel.length > 0 && <span className="tab-badge">{value.status.length + value.rel.length}</span>}
        </summary>
        <div className="more-filters-body">
      <fieldset className="chip-filter">
        <legend className="field-label">Transaction status {value.status.length === 0 && <span className="muted">(all)</span>}</legend>
        <div className="toggle-chips">
          {STATUSES.map((s) => (
            <label key={s} className={`toggle-chip ${value.status.includes(s) ? "is-on" : ""}`}>
              <input type="checkbox" checked={value.status.includes(s)} onChange={() => set({ status: toggle(value.status, s) })} />
              {humanize(s)}
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="chip-filter">
        <legend className="field-label">Relationships {value.rel.length === 0 && <span className="muted">(all)</span>}</legend>
        <div className="toggle-chips">
          {relations.map((r) => (
            <label key={r} className={`toggle-chip ${value.rel.includes(r) ? "is-on" : ""}`}>
              <input type="checkbox" checked={value.rel.includes(r)} onChange={() => set({ rel: toggle(value.rel, r) })} />
              {humanize(r)}
            </label>
          ))}
        </div>
      </fieldset>
        </div>
      </details>
    </div>
  );
}
