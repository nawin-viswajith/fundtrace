import { request } from "./client";
import type {
  AskResponse,
  AuditResponse,
  AuthConfig,
  CaseAction,
  CaseContext,
  CaseListResponse,
  ClassifyResponse,
  EvalRun,
  EvidenceItem,
  EvidenceResponse,
  GraphQueryParams,
  GraphResponse,
  MeResponse,
  Meta,
  OpsCall,
  OpsMetrics,
  Report,
  ReportsList,
  RingsResponse,
  RiskResponse,
  RuleCatalogueEntry,
  RuleVersion,
  TimelineResponse,
} from "../types/api";

const enc = encodeURIComponent;

export interface CaseFilters {
  status?: string;
  priority?: string;
  owner?: "all" | "me" | "unassigned";
  q?: string;
}

export function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export function graphQuery(p: GraphQueryParams): string {
  return qs({
    direction: p.direction,
    depth: p.depth,
    window_hours: p.window_hours,
    status: p.status.length ? p.status.join(",") : undefined,
    rel: p.rel.length ? p.rel.join(",") : undefined,
    expand: p.expand.length ? p.expand.join(",") : undefined,
  });
}

export const api = {
  authConfig: () => request<AuthConfig>("/api/auth/config", { quiet401: true }),
  me: () => request<MeResponse>("/api/auth/me", { quiet401: true }),
  login: (username: string, password: string) =>
    request<MeResponse>("/api/auth/login", { method: "POST", body: { username, password }, quiet401: true }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST", quiet401: true }),
  meta: () => request<Meta>("/api/meta"),

  cases: (f: CaseFilters) => request<CaseListResponse>("/api/cases" + qs({ ...f })),
  case: (id: string) => request<CaseContext>(`/api/cases/${enc(id)}`),
  graph: (id: string, p: GraphQueryParams) => request<GraphResponse>(`/api/cases/${enc(id)}/graph${graphQuery(p)}`),
  timeline: (id: string) => request<TimelineResponse>(`/api/cases/${enc(id)}/timeline`),
  risk: (id: string) => request<RiskResponse>(`/api/cases/${enc(id)}/risk`),
  evaluateRisk: (id: string) => request<RiskResponse>(`/api/cases/${enc(id)}/risk/evaluate`, { method: "POST" }),
  evidence: (id: string) => request<EvidenceResponse>(`/api/cases/${enc(id)}/evidence`),
  uploadEvidence: (id: string, file: File, checklistKey: string | null, kind: string) => {
    const form = new FormData();
    form.append("file", file);
    if (checklistKey) form.append("checklist_key", checklistKey);
    form.append("kind", kind);
    return request<{ id: string; analysis_status: string }>(`/api/cases/${enc(id)}/evidence`, { method: "POST", form });
  },
  analyseEvidence: (id: string, ev: string) =>
    request<{ status: string; note?: string; evidence?: EvidenceItem }>(
      `/api/cases/${enc(id)}/evidence/${enc(ev)}/analyse`,
      { method: "POST" },
    ),
  evidenceFileUrl: (id: string, ev: string) => `/api/cases/${enc(id)}/evidence/${enc(ev)}/file`,
  action: (id: string, body: CaseAction) =>
    request<{ ok: boolean; status?: string }>(`/api/cases/${enc(id)}/actions`, { method: "POST", body }),
  audit: (id: string) => request<AuditResponse>(`/api/cases/${enc(id)}/audit`),

  investigate: (id: string) => request<Report>(`/api/cases/${enc(id)}/investigate`, { method: "POST" }),
  reports: (id: string) => request<ReportsList>(`/api/cases/${enc(id)}/reports`),
  report: (rid: string) => request<Report>(`/api/reports/${enc(rid)}`),
  exportReport: (rid: string) => request<Report>(`/api/reports/${enc(rid)}/export`),
  reviewReport: (rid: string, body: { status: string; claims: Record<string, "accept" | "reject">; note: string }) =>
    request<{ ok: boolean }>(`/api/reports/${enc(rid)}/review`, { method: "POST", body }),
  ask: (id: string, question: string) =>
    request<AskResponse>(`/api/cases/${enc(id)}/ask`, { method: "POST", body: { question } }),
  classify: (id: string) => request<ClassifyResponse>(`/api/cases/${enc(id)}/classify`, { method: "POST" }),

  rules: () => request<{ rules: RuleCatalogueEntry[] }>("/api/rules"),
  updateRule: (rid: string, body: { params: Record<string, number>; enabled: boolean; change_note: string }) =>
    request<{ rule_id: string; version: number }>(`/api/rules/${enc(rid)}`, { method: "PUT", body }),
  ruleHistory: (rid: string) => request<{ versions: RuleVersion[] }>(`/api/rules/${enc(rid)}/history`),
  rings: () => request<RingsResponse>("/api/network/rings"),

  opsMetrics: () => request<OpsMetrics>("/api/ops/metrics"),
  opsCalls: () => request<{ calls: OpsCall[] }>("/api/ops/calls?limit=50"),
  opsEvals: () => request<{ runs: EvalRun[] }>("/api/ops/evals"),
  runEval: () => request<EvalRun>("/api/ops/evals/run", { method: "POST" }),
  resetDemo: () => request<Record<string, unknown>>("/api/admin/reset-demo", { method: "POST" }),
  runRetention: (dryRun: boolean) =>
    request<RetentionResult>(`/api/admin/retention/run?dry_run=${dryRun}`, { method: "POST" }),
};

export interface RetentionResult {
  dry_run: boolean;
  retention_days: number;
  cutoff: string;
  eligible: { evidence_id: string; case_id: string; filename: string }[];
  deleted: number;
}
