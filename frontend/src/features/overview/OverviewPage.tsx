import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useOverview } from "../../api/hooks";
import type { CaseBrief, Measurement, MeasurementKey, OverviewResponse, RecentActivity } from "../../types/api";
import { Card, EmptyState, ErrorState, Skeleton, Time } from "../../components/Primitives";
import { PriorityChip, SectionTitle, SlaRemaining, StatusBadge } from "../../components/Domain";
import { Chip } from "../../components/Chip";
import { activityLabel } from "../../lib/labels";
import {
  caseActionHref,
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
      <p className="page-lede">What needs your attention today. Start with the cases at the top of “Needs attention”.</p>
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
      <OutcomesSection outcomes={data.outcomes} collapsible />
      <RecentActivityCard items={data.recent_activity} />
    </div>
  );
}

/* ------------------------------------------------------------------ KPIs */
interface TileProps {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  to?: string;
  tone?: "default" | "warn" | "bad";
  children?: ReactNode;
}

function KpiTile({ label, value, sub, to, tone = "default", children }: TileProps) {
  const body = (
    <>
      <span className="ov-kpi-label">{label}</span>
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
      <KpiTile label="Open cases" value={c.open} to="/cases" sub="P1 is the most urgent">
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
        label="Money may be recoverable"
        value={c.golden_hour}
        sub="Cases with a suggested hold waiting for approval"
        to="#golden-hour"
        tone={c.golden_hour > 0 ? "warn" : "default"}
      />
      <KpiTile
        label="Deadline in the next 3 days"
        value={c.sla_at_risk_72h}
        sub="Must be resolved within 72 hours (SLA)"
        tone={c.sla_at_risk_72h > 0 ? "warn" : "default"}
      />
      <KpiTile
        label="Past the deadline"
        value={c.sla_breached}
        sub="Open cases that missed their deadline (SLA)"
        tone={c.sla_breached > 0 ? "bad" : "default"}
      />
      <KpiTile label="Nobody assigned" value={c.unassigned} sub="Open cases with no owner yet" to="/cases?owner=unassigned" />
      <KpiTile label="Money in dispute" value={c.disputed_open_amount_label} sub="Total of all open cases" />
    </section>
  );
}

/* ------------------------------------------------------------------ case lists */
function NextActionLink({ c }: { c: CaseBrief }) {
  if (!c.next_action) return <span className="muted">—</span>;
  return (
    <Link to={caseActionHref(c)} className="next-action-link ov-next">
      {c.next_action.label}
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
          {c.sla_remaining_hours !== null && c.sla_remaining_hours !== undefined && (
            <span className="ov-deadline">
              <span className="ov-deadline-label">Deadline:</span>
              <SlaRemaining hours={c.sla_remaining_hours} label="Time left to resolve the case (SLA)" />
            </span>
          )}
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
    <Card
      title="Needs attention"
      subtitle="Most urgent first, then the nearest deadline. The blue link on each case is the next thing to do."
      actions={<Link to="/cases" className="link small">All cases</Link>}>
      {focus.length === 0 ? (
        <EmptyState title="Nothing needs attention">There are no open cases for you right now.</EmptyState>
      ) : (
        <ul className="ov-case-list">
          {focus.map((c) => (
            <CaseRow key={c.id} c={c} />
          ))}
        </ul>
      )}
      {extraRisk.length > 0 && (
        <>
          <h4 className="h-sub">Also due in the next 3 days</h4>
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

const goldenReason = (c: CaseBrief) =>
  c.priority_reasons
    .find((r) => r.toLowerCase().startsWith("golden hour"))
    ?.replace(/^golden hour:\s*/i, "")
    .replace(/in visible accounts/i, "in accounts at this bank");

export function GoldenHourPanel({ cases }: { cases: CaseBrief[] }) {
  return (
    <Card
      id="golden-hour"
      className="ov-golden"
      title="Money may still be recoverable"
      subtitle="Some of the customer's money may still be in accounts at this bank. Act quickly: each suggested hold needs an investigator to approve it."
    >
      {cases.length === 0 ? (
        <EmptyState title="No holds waiting for approval">
          When some of a customer's money may still be in an account at this bank, FundTrace suggests a hold. The case appears here until an
          investigator approves or declines it.
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

/** Team measurements. On the home page they sit behind a disclosure: useful for supervisors, not needed for daily case work. */
export function OutcomesSection({ outcomes, collapsible = false }: { outcomes: OverviewResponse["outcomes"]; collapsible?: boolean }) {
  const basis = (
    <>
      Measured from what was recorded in FundTrace · <span className="num">{outcomes.cases.decided}</span> of{" "}
      <span className="num">{outcomes.cases.total}</span> cases decided so far
    </>
  );
  if (collapsible)
    return (
      <details className="disclosure ov-team card">
        <summary>
          <h2 id="ov-outcomes-title" className="ov-section-title">
            How the team is doing
          </h2>
          <span className="ov-team-hint">Speed, quality and safety checks for the whole team (for supervisors)</span>
        </summary>
        <p className="muted small">{basis}.</p>
        <OutcomesBody outcomes={outcomes} explain />
      </details>
    );
  return (
    <section className="ov-outcomes" aria-labelledby="ov-outcomes-title">
      <div className="ov-section-head">
        <h3 id="ov-outcomes-title" className="ov-section-title">
          How the team is doing
        </h3>
        <p className="muted small">{basis}</p>
      </div>
      <OutcomesBody outcomes={outcomes} />
    </section>
  );
}

function OutcomesBody({ outcomes, explain = false }: { outcomes: OverviewResponse["outcomes"]; explain?: boolean }) {
  return (
    <div className="ov-outcomes" aria-label="Team measurements">
      {explain && (
        <p className="muted small">
          “Median” is the middle value: half of the cases were quicker and half slower. “SLA” is the deadline the bank must meet for each case.
        </p>
      )}
      {MEASUREMENT_GROUPS.map((g) => (
        <div key={g.title} className="ov-measure-group">
          <h3 className="h-sub">{g.title}</h3>
          {g.hint && <p className="muted small ov-group-hint">{g.hint}</p>}
          <div className="ov-measure-grid">
            {g.keys.map((k) => (
              <MeasurementCard key={k} mkey={k} m={outcomes.measurements[k]} />
            ))}
          </div>
        </div>
      ))}
      <p className="ov-footnote">
        {outcomes.note} Updated <Time iso={outcomes.generated_at} />.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ activity */
export function RecentActivityCard({ items }: { items: RecentActivity[] }) {
  return (
    <Card title="Recent activity" subtitle="What people did on the cases you can see, newest first">
      {items.length === 0 ? (
        <EmptyState title="No activity recorded yet">
          Notes, assignments, reviews and decisions will be listed here as they happen.
        </EmptyState>
      ) : (
        <ol className="ov-activity">
          {items.map((e) => (
            <li key={e.id}>
              <Time iso={e.created_at} className="ov-activity-time" />
              <span className="ov-activity-what">
                <span className="mono ov-activity-actor">{e.actor}</span> {activityLabel(e.action)}
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
