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
  OutcomesResponse,
  OverviewResponse,
  Report,
  ReportsList,
  RingsResponse,
  RiskResponse,
  RuleCatalogueEntry,
  RuleVersion,
  SearchResponse,
  TimelineResponse,
  AdminUser,
  ChatState,
  ChatTurn,
  NewDispute,
  PortalDispute,
  PortalDisputeBrief,
  PortalPayment,
  PortalProfile,
  AssistantReply,
  DraftOpResult,
  ReportDraft,
  IngestEvent,
  HelpIndex,
  HelpAnswer,
  SafetyCheck,
  IngestEventsResponse,
  LoginResult,
  MfaSetup,
  SecurityStatus,
  User,
  InvestigationRun,
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

export interface GenerateDataRequest {
  count: number;
  categories: string[];
  amount_min: number;
  amount_max: number;
  status_mode: string;
  assign: string;
  days_back: number;
  with_trail: boolean;
  with_evidence: boolean;
  statements: "template" | "ai";
  ai_budget_usd: number;
}
export interface GenerateDataResult {
  created: { case_id: string; category: string; status: string; priority: string; amount: string }[];
  statements: { ai: number; ai_rejected: number; template: number; ai_cost_usd: number; ai_available: boolean };
}

export const api = {
  authConfig: () => request<AuthConfig>("/api/auth/config", { quiet401: true }),
  me: () => request<MeResponse>("/api/auth/me", { quiet401: true }),
  login: (username: string, password: string) =>
    request<LoginResult>("/api/auth/login", { method: "POST", body: { username, password }, quiet401: true }),
  firebaseLogin: (idToken: string) => request<LoginResult>("/api/auth/firebase", { method: "POST", body: { id_token: idToken }, quiet401: true }),
  mfaVerify: (mfaToken: string, code: string) =>
    request<{ user: User; recovery_codes_left: number | null }>("/api/auth/mfa/verify", {
      method: "POST",
      body: { mfa_token: mfaToken, code },
      quiet401: true,
    }),
  mfaSetup: (mfaToken?: string) => request<MfaSetup>("/api/auth/mfa/setup", { method: "POST", body: { mfa_token: mfaToken ?? null } }),
  mfaEnable: (code: string, mfaToken?: string) =>
    request<{ user: User; recovery_codes: string[] }>("/api/auth/mfa/enable", { method: "POST", body: { code, mfa_token: mfaToken ?? null } }),
  mfaDisable: (password: string, code: string) => request<{ user: User }>("/api/auth/mfa/disable", { method: "POST", body: { password, code } }),
  mfaNewRecoveryCodes: (code: string) => request<{ recovery_codes: string[] }>("/api/auth/mfa/recovery-codes", { method: "POST", body: { code } }),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST", quiet401: true }),
  meta: () => request<Meta>("/api/meta"),

  overview: () => request<OverviewResponse>("/api/overview"),
  outcomes: () => request<OutcomesResponse>("/api/outcomes"),
  search: (q: string, signal?: AbortSignal) => request<SearchResponse>("/api/search" + qs({ q }), { signal }),

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
  investigateStart: (id: string) => request<InvestigationRun>(`/api/cases/${enc(id)}/investigate?background=true`, { method: "POST" }),
  investigationRun: (id: string, runId: string) => request<InvestigationRun>(`/api/cases/${enc(id)}/runs/${enc(runId)}`),
  investigationActive: (id: string) => request<{ run: InvestigationRun | null }>(`/api/cases/${enc(id)}/runs/active`),
  reports: (id: string) => request<ReportsList>(`/api/cases/${enc(id)}/reports`),
  report: (rid: string) => request<Report>(`/api/reports/${enc(rid)}`),
  exportReport: (rid: string) => request<Report>(`/api/reports/${enc(rid)}/export`),
  reviewReport: (rid: string, body: { status: string; claims: Record<string, "accept" | "reject">; note: string }) =>
    request<{ ok: boolean }>(`/api/reports/${enc(rid)}/review`, { method: "POST", body }),
  ask: (id: string, question: string) =>
    request<AskResponse>(`/api/cases/${enc(id)}/ask`, { method: "POST", body: { question } }),
  assistant: (id: string, message: string, history: { role: string; text: string }[]) =>
    request<AssistantReply>(`/api/cases/${enc(id)}/assistant`, { method: "POST", body: { message, history } }),
  reportDraft: (rid: string) => request<{ draft: ReportDraft | null }>(`/api/reports/${enc(rid)}/draft`),
  draftOp: (rid: string, op: string, sectionKey?: string | null, claimIds?: string[]) =>
    request<DraftOpResult>(`/api/reports/${enc(rid)}/draft/ops`, {
      method: "POST",
      body: { op, section_key: sectionKey ?? null, claim_ids: claimIds ?? [] },
    }),
  saveDraft: (rid: string) => request<Report>(`/api/reports/${enc(rid)}/draft/save`, { method: "POST" }),
  discardDraft: (rid: string) => request<{ ok: boolean }>(`/api/reports/${enc(rid)}/draft/discard`, { method: "POST" }),
  rejudge: (rid: string) =>
    request<{ result: { ok: boolean; message: string; judged: number }; report: Report }>(`/api/reports/${enc(rid)}/judge`, { method: "POST" }),
  classify: (id: string) => request<ClassifyResponse>(`/api/cases/${enc(id)}/classify`, { method: "POST" }),

  rules: () => request<{ rules: RuleCatalogueEntry[] }>("/api/rules"),
  updateRule: (rid: string, body: { params: Record<string, number>; enabled: boolean; change_note: string }) =>
    request<{ rule_id: string; version: number }>(`/api/rules/${enc(rid)}`, { method: "PUT", body }),
  ruleHistory: (rid: string) => request<{ versions: RuleVersion[] }>(`/api/rules/${enc(rid)}/history`),
  rings: () => request<RingsResponse>("/api/network/rings"),

  opsMetrics: () => request<OpsMetrics>("/api/ops/metrics"),
  portalMe: () => request<PortalProfile>("/api/portal/me"),
  portalPayments: (q?: string) => request<{ transactions: PortalPayment[] }>(`/api/portal/transactions${qs({ q })}`),
  portalDisputes: () => request<{ disputes: PortalDisputeBrief[] }>("/api/portal/disputes"),
  portalDispute: (id: string) => request<PortalDispute>(`/api/portal/disputes/${enc(id)}`),
  portalRaise: (body: NewDispute) => request<PortalDispute>("/api/portal/disputes", { method: "POST", body }),
  portalUpload: (id: string, file: File, checklistKey?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (checklistKey) form.append("checklist_key", checklistKey);
    return request<PortalDispute>(`/api/portal/disputes/${enc(id)}/evidence`, { method: "POST", form });
  },
  portalChat: (state: ChatState | null, choice?: string, text?: string) =>
    request<ChatTurn>("/api/portal/chat", { method: "POST", body: { state, choice: choice ?? null, text: text ?? null } }),
  portalChatStory: (story: string) => request<ChatTurn>("/api/portal/chat/story", { method: "POST", body: { story } }),
  portalHelpIndex: () => request<HelpIndex>("/api/portal/help"),
  portalHelpAsk: (message: string, history?: { role: string; text: string }[]) =>
    request<HelpAnswer>("/api/portal/help/ask", { method: "POST", body: { message, history: history ?? null } }),
  portalSafetyCheck: () => request<SafetyCheck>("/api/portal/safety-check"),
  generateData: (body: GenerateDataRequest) => request<GenerateDataResult>("/api/admin/generate-data", { method: "POST", body }),
  adminUsers: () => request<{ users: AdminUser[] }>("/api/admin/users"),
  adminResetMfa: (userId: number, reason: string) =>
    request<{ ok: boolean }>(`/api/admin/users/${userId}/mfa/reset`, { method: "POST", body: { reason } }),
  securityStatus: () => request<SecurityStatus>("/api/admin/security"),
  ingestEvents: () => request<IngestEventsResponse>("/api/ingest/events"),
  ingestFile: (file: File, format: string, sourceSystem: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("format", format);
    form.append("source_system", sourceSystem);
    return request<{ event: IngestEvent; already_processed: boolean }>("/api/ingest/file", { method: "POST", form });
  },
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
