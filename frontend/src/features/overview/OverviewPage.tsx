import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { AlarmClock, ArrowRight, Briefcase, CircleAlert, History, Hourglass, IndianRupee, Info, UserX } from "lucide-react";
import { useOverview } from "../../api/hooks";
import type { CaseBrief, Measurement, MeasurementKey, OverviewResponse, RecentActivity } from "../../types/api";
import { Card, EmptyState, ErrorState, Skeleton, Time } from "../../components/Primitives";
import { PriorityChip, SectionTitle, SlaRemaining, StatusBadge } from "../../components/Domain";
import { Chip } from "../../components/Chip";
import { caseActionHref } from "../../lib/outcomes";
import {
  activityLabel,
  formatMeasurement,
  MEASUREMENT_GROUPS,
  MEASUREMENT_INFO,
  measurementBasis,
  NOT_ENOUGH_DATA,
} from "../../lib/outcomes";

const PRIORITIES = ["P1", "P2", "P3", "P4"] as const;


export default function OverviewPage() {
  const q = useOverview();
  return (
    <div className="page page-wide overview">
      <SectionTitle>Overview</SectionTitle>
      <p className="page-lede">What needs attention now, and how investigations in this deployment are going.</p>
      {q.isLoading ? (
        <OverviewSkeleton />
      ) : q.error || !q.data ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load the overview" />
      ) : (
        <OverviewBody data={q.data} />
      )}
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="stack-lg" role="status" aria-live="polite">
      <span className="sr-only">Loading overview…</span>
      <div className="ov-kpis">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} height={96} />
        ))}
      </div>
      <div className="ov-columns">
        <Skeleton height={320} />
        <Skeleton height={320} />
      </div>
      <Skeleton height={200} />
    </div>
  );
}

export function OverviewBody({ data }: { data: OverviewResponse }) {
  return (
    <div className="stack-lg">
      <KpiRow data={data} />
      <div className="ov-columns">
        <NeedsAttention focus={data.focus} atRisk={data.at_risk} />
        <GoldenHourPanel cases={data.golden_hour} />
      </div>
      <OutcomesSection outcomes={data.outcomes} />
      <RecentActivityCard items={data.recent_activity} />
    </div>
  );
}

/* ------------------------------------------------------------------ KPIs */
interface TileProps {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon: ReactNode;
  to?: string;
  tone?: "default" | "warn" | "bad";
  children?: ReactNode;
}

function KpiTile({ label, value, sub, icon, to, tone = "default", children }: TileProps) {
  const body = (
    <>
      <span className="ov-kpi-label">
        <span className="ov-kpi-icon" aria-hidden="true">
          {icon}
        </span>
        {label}
      </span>
      <span className="ov-kpi-value num">{value}</span>
      {sub && <span className="ov-kpi-sub">{sub}</span>}
    </>
  );
  return (
    <div className={`ov-kpi ov-kpi-${tone} ${to ? "is-link" : ""}`}>
      {to ? (
        to.startsWith("#") ? (
          <a href={to} className="ov-kpi-main">
            {body}
          </a>
        ) : (
          <Link to={to} className="ov-kpi-main">
            {body}
          </Link>
        )
      ) : (
        <div className="ov-kpi-main">{body}</div>
      )}
      {children}
    </div>
  );
}

function KpiRow({ data }: { data: OverviewResponse }) {
  const c = data.counts;
  return (
    <section aria-label="Key figures" className="ov-kpis">
      <KpiTile label="Open cases" value={c.open} icon={<Briefcase size={15} />} to="/cases">
        <ul className="ov-prio-breakdown" aria-label="Open cases by priority">
          {PRIORITIES.map((p) => (
            <li key={p}>
              <Link to={`/cases?priority=${p}`} className={`ov-prio prio-${p}`} aria-label={`${c.by_priority[p] ?? 0} ${p} cases`}>
                <span>{p}</span>
                <span className="num">{c.by_priority[p] ?? 0}</span>
              </Link>
            </li>
          ))}
        </ul>
      </KpiTile>
      <KpiTile
        label="Golden-hour cases"
        value={c.golden_hour}
        icon={<Hourglass size={15} />}
        sub="Hold recommendations awaiting approval"
        to="#golden-hour"
        tone={c.golden_hour > 0 ? "warn" : "default"}
      />
      <KpiTile
        label="SLA at risk"
        value={c.sla_at_risk_72h}
        icon={<AlarmClock size={15} />}
        sub={"Resolution due within 72\u00a0h"}
        tone={c.sla_at_risk_72h > 0 ? "warn" : "default"}
      />
      <KpiTile
        label="SLA breached"
        value={c.sla_breached}
        icon={<CircleAlert size={15} />}
        sub="Open and past the due date"
        tone={c.sla_breached > 0 ? "bad" : "default"}
      />
      <KpiTile label="Unassigned" value={c.unassigned} icon={<UserX size={15} />} sub="Open cases with no owner" to="/cases?owner=unassigned" />
      <KpiTile label="Open disputed amount" value={c.disputed_open_amount_label} icon={<IndianRupee size={15} />} sub="Across all open cases" />
    </section>
  );
}

/* ------------------------------------------------------------------ case lists */
function NextActionLink({ c }: { c: CaseBrief }) {
  if (!c.next_action) return <span className="muted">—</span>;
  return (
    <Link to={caseActionHref(c)} className="btn btn-secondary btn-sm ov-next">
      {c.next_action.label}
      <ArrowRight size={14} aria-hidden="true" />
    </Link>
  );
}

function CaseRow({ c }: { c: CaseBrief }) {
  return (
    <li className="ov-case">
      <div className="ov-case-main">
        <div className="ov-case-title">
          <PriorityChip priority={c.priority} reasons={c.priority_reasons} />
          <Link to={`/cases/${c.id}`} className="case-link">
            {c.id}
          </Link>
          <span className="ov-case-cat">{c.category_label}</span>
        </div>
        <div className="ov-case-meta">
          <span className="num strong">{c.amount_label}</span>
          <StatusBadge status={c.status} />
          <SlaRemaining hours={c.sla_remaining_hours} label="Resolution due" />
        </div>
      </div>
      <NextActionLink c={c} />
    </li>
  );
}

export function NeedsAttention({ focus, atRisk }: { focus: CaseBrief[]; atRisk: CaseBrief[] }) {
  const focusIds = new Set(focus.map((c) => c.id));
  const extraRisk = atRisk.filter((c) => !focusIds.has(c.id));
  return (
    <Card title="Needs attention" subtitle="Highest priority first, then the earliest due date" actions={<Link to="/cases" className="link small">All cases <ArrowRight size={13} aria-hidden="true" /></Link>}>
      {focus.length === 0 ? (
        <EmptyState title="Nothing needs attention">There are no open cases you can access.</EmptyState>
      ) : (
        <ul className="ov-case-list">
          {focus.map((c) => (
            <CaseRow key={c.id} c={c} />
          ))}
        </ul>
      )}
      {extraRisk.length > 0 && (
        <>
          <h4 className="h-sub">Also due within 72 h</h4>
          <ul className="ov-case-list">
            {extraRisk.map((c) => (
              <CaseRow key={c.id} c={c} />
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

const goldenReason = (c: CaseBrief) => c.priority_reasons.find((r) => r.toLowerCase().startsWith("golden hour"))?.replace(/^golden hour:\s*/i, "");

export function GoldenHourPanel({ cases }: { cases: CaseBrief[] }) {
  return (
    <Card
      id="golden-hour"
      className="ov-golden"
      title={
        <span className="ov-title-icon">
          <Hourglass size={16} aria-hidden="true" /> Golden hour
        </span>
      }
      subtitle="Funds that may still be recoverable. Holds are recommendations; an investigator must approve each one."
    >
      {cases.length === 0 ? (
        <EmptyState title="No holds waiting for approval" icon={<Hourglass size={22} />}>
          When a trail shows disputed money may still sit in accounts this bank can see, FundTrace recommends a hold. Those cases appear here until an
          investigator approves or declines the hold.
        </EmptyState>
      ) : (
        <ul className="ov-case-list ov-golden-list">
          {cases.map((c) => {
            const reason = goldenReason(c);
            return (
              <li key={c.id} className="ov-golden-item">
                <div className="ov-case-title">
                  <PriorityChip priority={c.priority} reasons={c.priority_reasons} />
                  <Link to={`/cases/${c.id}`} className="case-link">
                    {c.id}
                  </Link>
                  <span className="num strong ov-golden-amount">{c.amount_label}</span>
                </div>
                {reason && <p className="ov-golden-reason">{reason.charAt(0).toUpperCase() + reason.slice(1)}</p>}
                {c.next_action && (
                  <Link to={caseActionHref(c)} className="next-action-link">
                    {c.next_action.label}
                    <ArrowRight size={13} aria-hidden="true" />
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ outcomes */
export function MeasurementCard({ mkey, m }: { mkey: MeasurementKey; m: Measurement | undefined }) {
  const info = MEASUREMENT_INFO[mkey];
  const value = formatMeasurement(m);
  const safeguard = mkey === "automated_claim_rejections" || mkey === "unsupported_claims_in_accepted_reports";
  return (
    <article className="ov-measure" aria-label={info.label}>
      <h4 className="ov-measure-label">{info.label}</h4>
      {value === null ? (
        <p className="ov-measure-value is-empty">{NOT_ENOUGH_DATA}</p>
      ) : (
        <p className="ov-measure-value num">
          {value}
          {safeguard && m?.status === "ok" && (
            <Chip tone={m.value === 0 ? "good" : "bad"} size="sm">
              {m.value === 0 ? "On target" : "Needs review"}
            </Chip>
          )}
        </p>
      )}
      {m && <p className="ov-measure-n">{measurementBasis(mkey, m.n)}</p>}
      {m?.note && <p className="ov-measure-note">{m.note}</p>}
    </article>
  );
}

export function OutcomesSection({ outcomes }: { outcomes: OverviewResponse["outcomes"] }) {
  return (
    <section className="ov-outcomes" aria-labelledby="ov-outcomes-title">
      <div className="ov-section-head">
        <h3 id="ov-outcomes-title" className="ov-section-title">
          Outcome measurements
        </h3>
        <p className="muted small">
          Measured from recorded activity in this deployment · <span className="num">{outcomes.cases.decided}</span> decided of{" "}
          <span className="num">{outcomes.cases.total}</span> cases
        </p>
      </div>
      {MEASUREMENT_GROUPS.map((g) => (
        <div key={g.title} className="ov-measure-group">
          <h4 className="h-sub">{g.title}</h4>
          {g.hint && <p className="muted small ov-group-hint">{g.hint}</p>}
          <div className="ov-measure-grid">
            {g.keys.map((k) => (
              <MeasurementCard key={k} mkey={k} m={outcomes.measurements[k]} />
            ))}
          </div>
        </div>
      ))}
      <p className="ov-footnote">
        <Info size={13} aria-hidden="true" />
        <span>
          {outcomes.note} Updated <Time iso={outcomes.generated_at} />.
        </span>
      </p>
    </section>
  );
}

/* ------------------------------------------------------------------ activity */
export function RecentActivityCard({ items }: { items: RecentActivity[] }) {
  return (
    <Card
      title={
        <span className="ov-title-icon">
          <History size={16} aria-hidden="true" /> Recent activity
        </span>
      }
      subtitle="Investigator actions on cases you can access"
    >
      {items.length === 0 ? (
        <EmptyState title="No activity recorded yet" icon={<History size={22} />}>
          Notes, assignments, reviews and decisions will be listed here as they happen.
        </EmptyState>
      ) : (
        <ol className="ov-activity">
          {items.map((e) => (
            <li key={e.id}>
              <Time iso={e.created_at} className="ov-activity-time" />
              <span className="ov-activity-what">
                <span className="mono ov-activity-actor">{e.actor}</span> {activityLabel(e.action).toLowerCase()}
              </span>
              {e.case_id ? (
                <Link to={`/cases/${e.case_id}`} className="case-link ov-activity-case">
                  {e.case_id}
                </Link>
              ) : (
                <span className="muted">—</span>
              )}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
