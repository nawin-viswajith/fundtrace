import { useMemo, useState, useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight, ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import { useCases } from "../../api/hooks";
import type { CaseFilters } from "../../api/endpoints";
import type { CaseStatus, CaseSummary } from "../../types/api";
import { EmptyState, ErrorState, LoadingBlock, Money, Time } from "../../components/Primitives";
import { PriorityChip, SectionTitle, SlaRemaining, StatusBadge } from "../../components/Domain";
import { STATUS_LABELS_FALLBACK } from "../../lib/labels";
import { caseActionHref, formatAge } from "../../lib/outcomes";

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

  return (
    <div className="page page-wide">
      <SectionTitle>Case queue</SectionTitle>
      <p className="page-lede">Sorted by priority and due time. Priority orders the work; it is not a judgement on the claim.</p>

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
          <span className="field-label">Status</span>
          <select className="select" value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">All statuses</option>
            {STATUS_ORDER.map((s) => (
              <option key={s} value={s}>
                {labels[s] ?? s}
              </option>
            ))}
          </select>
        </label>
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
          <span className="field-label">Owner</span>
          <select className="select" value={owner} onChange={(e) => set("owner", e.target.value)}>
            <option value="all">Everyone</option>
            <option value="me">Assigned to me</option>
            <option value="unassigned">Unassigned</option>
          </select>
        </label>
        <label className="field field-inline field-grow">
          <span className="field-label">Search</span>
          <span className="input-icon">
            <Search size={15} aria-hidden="true" />
            <input
              className="input"
              type="search"
              placeholder="Case ID or transaction ID"
              value={qDraft}
              maxLength={64}
              onChange={(e) => setQDraft(e.target.value)}
            />
          </span>
        </label>
        {filtersActive && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSp(new URLSearchParams(), { replace: true })}>
            <X size={14} aria-hidden="true" /> Clear filters
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
          ? "Try clearing a filter or searching for a different case or transaction ID."
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
              <th scope="col">Category</th>
              <th scope="col" className="ta-r">
                Amount
              </th>
              <th scope="col">Priority</th>
              <th scope="col">Status</th>
              <th scope="col">Owner</th>
              <th scope="col">SLA</th>
              <th scope="col">Age</th>
              <th scope="col">Next action</th>
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
                <td data-label="Category">{c.category_label}</td>
                <td data-label="Amount" className="ta-r">
                  <Money minor={c.amount_minor} currency={c.currency} className="strong" />
                </td>
                <td data-label="Priority" onClick={(e) => e.stopPropagation()}>
                  <PriorityChip priority={c.priority} reasons={c.priority_reasons} />
                </td>
                <td data-label="Status">
                  <StatusBadge status={c.status} label={labels[c.status]} />
                </td>
                <td data-label="Owner">{c.owner ? c.owner.full_name.replace(" (synthetic)", "") : <span className="muted">Unassigned</span>}</td>
                <td data-label="SLA">
                  {c.status === "resolved" ? (
                    <span className="muted">Closed</span>
                  ) : (
                    <span className="sla-cell">
                      <SlaRemaining hours={c.sla_remaining_hours} />
                      {c.sla_next_label && <span className="muted small sla-next">{c.sla_next_label}</span>}
                    </span>
                  )}
                </td>
                <td data-label="Age">
                  <span className="age-cell">
                    <span className="num">{formatAge(c.age_hours)}</span>
                    <span className="cell-sub">
                      <Time iso={c.reported_at} dateOnly />
                    </span>
                  </span>
                </td>
                <td data-label="Next action">
                  {c.next_action && c.status !== "resolved" ? (
                    <Link to={caseActionHref(c)} className="next-action-link" onClick={(e) => e.stopPropagation()}>
                      {c.next_action.label}
                      <ArrowRight size={13} aria-hidden="true" />
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
