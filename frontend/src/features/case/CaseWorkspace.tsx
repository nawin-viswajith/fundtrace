import { lazy, Suspense, useCallback, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useCase } from "../../api/hooks";
import { ApiError } from "../../api/client";
import { Tabs, TabPanel, type TabDef } from "../../components/Tabs";
import { EmptyState, ErrorState, LoadingBlock, Skeleton } from "../../components/Primitives";
import { CaseHeader } from "./CaseHeader";
import { OverviewTab } from "./OverviewTab";
import { TAB_IDS, WorkspaceCtx, type TabId, type WorkspaceApi } from "./workspace";
import { TimelineTab } from "../timeline/TimelineTab";
import { RiskTab } from "../risk/RiskTab";
import { EvidenceTab } from "../evidence/EvidenceTab";
import { ReportTab } from "../report/ReportTab";
import { ActionsAuditTab } from "../audit/ActionsAuditTab";

const TrailGraphTab = lazy(() => import("../graph/TrailGraphTab"));

export default function CaseWorkspace() {
  const { caseId = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const tabParam = sp.get("tab") as TabId | null;
  const tab: TabId = tabParam && TAB_IDS.includes(tabParam) ? tabParam : "overview";
  const [highlight, setHighlight] = useState<string[]>([]);
  const q = useCase(caseId);

  const setTab = useCallback(
    (t: TabId) => {
      const next = new URLSearchParams(sp);
      if (t === "overview") next.delete("tab");
      else next.set("tab", t);
      setSp(next, { replace: true });
    },
    [sp, setSp],
  );

  const api: WorkspaceApi | null = useMemo(
    () =>
      q.data
        ? {
            caseId,
            ctx: q.data,
            setTab,
            showOnGraph: (ids: string[]) => {
              setHighlight(ids);
              setTab("graph");
            },
            highlight,
            clearHighlight: () => setHighlight([]),
          }
        : null,
    [q.data, caseId, setTab, highlight],
  );

  if (q.isLoading)
    return (
      <div className="page">
        <Skeleton height={120} />
        <div style={{ height: 16 }} />
        <LoadingBlock label="Loading case" lines={8} />
      </div>
    );
  if (q.error || !api) {
    const notFound = q.error instanceof ApiError && (q.error.status === 404 || q.error.status === 403);
    return (
      <div className="page">
        <Link to="/cases" className="back-link">
          <ArrowLeft size={14} aria-hidden="true" /> Case queue
        </Link>
        {notFound ? (
          <EmptyState title="Case not found">This case does not exist or is not assigned to you.</EmptyState>
        ) : (
          <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load this case" />
        )}
      </div>
    );
  }

  const ctx = api.ctx;
  const tabs: TabDef[] = [
    { id: "overview", label: "Overview" },
    { id: "graph", label: "Trail graph", badge: ctx.graph.stats.transactions },
    { id: "timeline", label: "Timeline" },
    { id: "risk", label: "Risk signals", badge: ctx.rules_summary.triggered },
    { id: "evidence", label: "Evidence", badge: `${ctx.completeness.present}/${ctx.completeness.required}` },
    { id: "report", label: "AI report" },
    { id: "audit", label: "Actions & audit" },
  ];

  return (
    <WorkspaceCtx.Provider value={api}>
      <div className="page page-wide">
        <Link to="/cases" className="back-link">
          <ArrowLeft size={14} aria-hidden="true" /> Case queue
        </Link>
        <CaseHeader compact={tab !== "overview"} />
        <div className="tabs-sticky">
          <Tabs tabs={tabs} active={tab} onChange={(t) => setTab(t as TabId)} label="Case sections" idPrefix="case" />
        </div>
        <TabPanel id="overview" active={tab} idPrefix="case">
          <OverviewTab />
        </TabPanel>
        <TabPanel id="graph" active={tab} idPrefix="case">
          <Suspense fallback={<LoadingBlock label="Loading graph" lines={6} />}>
            <TrailGraphTab />
          </Suspense>
        </TabPanel>
        <TabPanel id="timeline" active={tab} idPrefix="case">
          <TimelineTab />
        </TabPanel>
        <TabPanel id="risk" active={tab} idPrefix="case">
          <RiskTab />
        </TabPanel>
        <TabPanel id="evidence" active={tab} idPrefix="case">
          <EvidenceTab />
        </TabPanel>
        <TabPanel id="report" active={tab} idPrefix="case">
          <ReportTab />
        </TabPanel>
        <TabPanel id="audit" active={tab} idPrefix="case">
          <ActionsAuditTab />
        </TabPanel>
      </div>
    </WorkspaceCtx.Provider>
  );
}
