import { useMemo, useState, useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useCases } from "../../api/hooks";
import type { CaseFilters } from "../../api/endpoints";
import type { CaseStatus, CaseSummary } from "../../types/api";
import { EmptyState, ErrorState, LoadingBlock, Money, Time } from "../../components/Primitives";
import { PriorityChip, SectionTitle, SlaRemaining, StatusBadge } from "../../components/Domain";
import { STATUS_LABELS_FALLBACK } from "../../lib/labels";
import { caseActionHref, formatAge } from "../../lib/outcomes";
import { canSupervise, useAuth } from "../auth/AuthProvider";
import { GenerateDataDialog } from "./GenerateDataDialog";

export const PAGE_SIZE = 15;

const STATUS_ORDER: CaseStatus[] = ["new", "triage", "investigating", "awaiting_evidence", "ready_for_review", "escalated", "resolved"];
const PRIORITIES = ["P1", "P2", "P3", "P4"];

export default function CaseQueue() {
  const [sp, setSp] = useSearchParams();
  const status = sp.get("status") ?? "";
  const priority = sp.get("priority") ?? "";
  const owner = (sp.get("owner") as CaseFilters["owner"]) ?? "all";
  const q = sp.get("q") ?? "";
  const [qDraft, setQDraft] = useState(q);
  useEffect(() => setQDraft(q), [q]);

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    if (v && !(k === "owner" && v === "all")) next.set(k, v);
    else next.delete(k);
    setSp(next, { replace: true });
  };

  // Debounce search typing into the URL.
  useEffect(() => {
    const t = window.setTimeout(() => {
      if (qDraft !== q) set("q", qDraft.trim());
    }, 300);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qDraft]);

  const base: CaseFilters = { priority: priority || undefined, owner, q: q || undefined };
  const counts = useCases(base);
  const list = useCases(status ? { ...base, status } : base);
  const labels = counts.data?.status_labels ?? STATUS_LABELS_FALLBACK;
  const total = useMemo(() => Object.values(counts.data?.counts ?? {}).reduce((a, b) => a + b, 0), [counts.data]);
  const filtersActive = !!(status || priority || owner !== "all" || q);
  const { user } = useAuth();
  const [genOpen, setGenOpen] = useState(false);

  return (
    <div className="page page-wide">
      <SectionTitle
        actions={
          canSupervise(user) ? (
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setGenOpen(true)}>
              Generate demo disputes
            </button>
          ) : undefined
        }
      >
        Case queue
      </SectionTitle>
      {genOpen && <GenerateDataDialog onClose={() => setGenOpen(false)} />}
      <p className="page-lede">
        Most urgent cases first, then the nearest deadline. Priority (P1 is the most urgent) only sets the order of work; it does not say whether
        the customer is right.
      </p>

      <div className="pill-row" role="group" aria-label="Filter by status">
        <button type="button" className={`pill ${!status ? "is-active" : ""}`} aria-pressed={!status} onClick={() => set("status", "")}>
          All <span className="pill-count num">{counts.data ? total : "–"}</span>
        </button>
        {STATUS_ORDER.map((s) => (
          <button
            key={s}
            type="button"
            className={`pill pill-status-${s} ${status === s ? "is-active" : ""}`}
            aria-pressed={status === s}
            onClick={() => set("status", status === s ? "" : s)}
          >
            {labels[s] ?? s} <span className="pill-count num">{counts.data ? counts.data.counts[s] ?? 0 : "–"}</span>
          </button>
        ))}
      </div>

      <div className="filter-bar">
        <label className="field field-inline">
          <span className="field-label">Priority</span>
          <select className="select" value={priority} onChange={(e) => set("priority", e.target.value)}>
            <option value="">All priorities</option>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="field field-inline">
          <span className="field-label">Assigned to</span>
          <select className="select" value={owner} onChange={(e) => set("owner", e.target.value)}>
            <option value="all">Everyone</option>
            <option value="me">Assigned to me</option>
            <option value="unassigned">Nobody yet</option>
          </select>
        </label>
        <label className="field field-inline field-grow">
          <span className="field-label">Search</span>
          <span className="input-icon">
            <Search size={15} aria-hidden="true" />
            <input
              className="input"
              type="search"
              placeholder="Case number or transaction ID"
              value={qDraft}
              maxLength={64}
              onChange={(e) => setQDraft(e.target.value)}
            />
          </span>
        </label>
        {filtersActive && (
          <button type="button" className="btn btn-ghost" onClick={() => setSp(new URLSearchParams(), { replace: true })}>
            Clear filters
          </button>
        )}
      </div>

      <QueueBody
        key={`${status}|${priority}|${owner}|${q}`}
        loading={list.isLoading}
        error={list.error}
        retry={() => list.refetch()}
        cases={list.data?.cases}
        labels={labels}
        filtersActive={filtersActive}
      />
    </div>
  );
}

interface BodyProps {
  loading: boolean;
  error: unknown;
  retry: () => void;
  cases: CaseSummary[] | undefined;
  labels: Record<string, string>;
  filtersActive: boolean;
}

export function QueueBody({ loading, error, retry, cases, labels, filtersActive }: BodyProps) {
  const nav = useNavigate();
  const [page, setPage] = useState(0);
  const total = cases?.length ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  if (loading) return <LoadingBlock label="Loading cases" lines={8} />;
  if (error) return <ErrorState error={error} onRetry={retry} title="Couldn't load the case queue" />;
  if (!cases || cases.length === 0)
    return (
      <EmptyState title={filtersActive ? "No cases match these filters" : "No cases in your queue"}>
        {filtersActive
          ? "Try clearing a filter, or search for a different case number or transaction ID."
          : "New disputes you can access will appear here."}
      </EmptyState>
    );
  const start = current * PAGE_SIZE;
  const rows = cases.slice(start, start + PAGE_SIZE);
  return (
    <div className="queue-wrap">
      <div className="table-wrap queue-table-wrap">
        <table className="table queue-table">
          <caption className="sr-only">Dispute cases</caption>
          <thead>
            <tr>
              <th scope="col">Case</th>
              <th scope="col">Type of dispute</th>
              <th scope="col" className="ta-r">
                Amount
              </th>
              <th scope="col">
                <span className="th-help" title="How urgent the case is. P1 is the most urgent, P4 the least.">
                  Priority
                </span>
              </th>
              <th scope="col">Status</th>
              <th scope="col">Assigned to</th>
              <th scope="col">
                <span className="th-help" title="Time left before the bank's deadline (SLA) for this case">
                  Deadline (SLA)
                </span>
              </th>
              <th scope="col">
                <span className="th-help" title="How long ago the customer reported the dispute">
                  Reported
                </span>
              </th>
              <th scope="col">Next step</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="row-link" onClick={() => nav(`/cases/${c.id}`)}>
                <td data-label="Case">
                  <Link to={`/cases/${c.id}`} className="case-link" onClick={(e) => e.stopPropagation()}>
                    {c.id}
                  </Link>
                  <div className="cell-sub mono">{c.disputed_txn_id}</div>
                </td>
                <td data-label="Type of dispute">{c.category_label}</td>
                <td data-label="Amount" className="ta-r">
                  <Money minor={c.amount_minor} currency={c.currency} className="strong" />
                </td>
                <td data-label="Priority" onClick={(e) => e.stopPropagation()}>
                  <PriorityChip priority={c.priority} reasons={c.priority_reasons} />
                </td>
                <td data-label="Status">
                  <StatusBadge status={c.status} label={labels[c.status]} />
                </td>
                <td data-label="Assigned to">{c.owner ? c.owner.full_name.replace(" (synthetic)", "") : <span className="muted">Nobody yet</span>}</td>
                <td data-label="Deadline (SLA)">
                  {c.status === "resolved" ? (
                    <span className="muted">Closed</span>
                  ) : (
                    <span className="sla-cell">
                      <SlaRemaining hours={c.sla_remaining_hours} label="Time left before the deadline (SLA)" />
                      {c.sla_next_label && <span className="muted small sla-next">{c.sla_next_label}</span>}
                    </span>
                  )}
                </td>
                <td data-label="Reported">
                  <span className="age-cell">
                    <span>
                      <span className="num">{formatAge(c.age_hours)}</span>
                      {c.age_hours !== null && c.age_hours !== undefined && " ago"}
                    </span>
                    <span className="cell-sub">
                      <Time iso={c.reported_at} dateOnly />
                    </span>
                  </span>
                </td>
                <td data-label="Next step">
                  {c.next_action && c.status !== "resolved" ? (
                    <Link to={caseActionHref(c)} className="next-action-link" onClick={(e) => e.stopPropagation()}>
                      {c.next_action.label}
                    </Link>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <nav className="pager" aria-label="Case queue pages">
        <span className="pager-range num" aria-live="polite">
          {start + 1}–{start + rows.length} of {total}
        </span>
        <div className="pager-buttons">
          <button type="button" className="btn btn-secondary btn-sm" disabled={current === 0} onClick={() => setPage(current - 1)}>
            <ChevronLeft size={14} aria-hidden="true" /> Prev
          </button>
          <span className="pager-page small muted num">
            Page {current + 1} of {pages}
          </span>
          <button type="button" className="btn btn-secondary btn-sm" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
            Next <ChevronRight size={14} aria-hidden="true" />
          </button>
        </div>
      </nav>
    </div>
  );
}
