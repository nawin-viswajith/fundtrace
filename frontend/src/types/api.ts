/* Types mirror the real backend responses in docs/api-samples/*.json. */

export type Provenance = "confirmed" | "derived" | "inferred" | "unknown" | "contradictory";
export type Severity = "high" | "medium" | "low";
export type RuleStatus = "triggered" | "not_triggered" | "not_evaluable";
export type Role = "investigator" | "supervisor" | "admin";
export type CaseStatus =
  | "new"
  | "triage"
  | "investigating"
  | "awaiting_evidence"
  | "ready_for_review"
  | "escalated"
  | "resolved";
export type Priority = "P1" | "P2" | "P3" | "P4";
export type TxnStatus = "posted" | "pending" | "failed" | "reversed";
export type AttributionMethod = "min" | "fifo" | "pro_rata" | "max";

export interface ApiErrorBody {
  error: { code: string; message: string; fields?: string[] };
}

// ------------------------------------------------------------------ auth
export interface User {
  id: number;
  username: string;
  full_name: string;
  role: Role;
}
export interface MeResponse {
  user: User;
}
export interface AuthConfig {
  demo: boolean;
  demo_users: { username: string; role: Role }[];
  demo_password: string | null;
  firebase_enabled: boolean;
  synthetic_data: boolean;
}

export interface Meta {
  statuses: CaseStatus[];
  status_labels: Record<CaseStatus, string>;
  categories: Record<string, string>;
  decisions: Record<string, string>;
  graph_relations: string[];
  assignees: { id: number; username: string; full_name: string; role: Role }[];
  limits: { max_depth: number; max_window_hours: number; max_nodes: number };
}

// ------------------------------------------------------------------ cases
export interface OwnerRef {
  id: number;
  username: string;
  full_name: string;
}

export interface CaseSummary {
  id: string;
  category: string;
  category_label: string;
  category_source: string;
  status: CaseStatus;
  priority: Priority;
  priority_reasons: string[];
  owner: OwnerRef | null;
  allegation: string;
  allegation_language: string;
  allegation_translation: string | null;
  reported_at: string;
  created_at: string;
  updated_at: string;
  due_at: string | null;
  sla_policy: string;
  decision: string | null;
  decision_rationale: string | null;
  decided_at: string | null;
  disputed_txn_id: string;
  customer_id: string;
  amount_minor: number;
  currency: string;
  txn_status: TxnStatus;
  txn_reference: string | null;
  is_synthetic: boolean;
  scenario?: string;
  sla_remaining_hours?: number | null;
  sla_next_label?: string;
  amount_label?: string;
}

export interface CaseListResponse {
  cases: CaseSummary[];
  counts: Record<CaseStatus, number>;
  status_labels: Record<CaseStatus, string>;
}

export interface TransactionData {
  amount_minor: number;
  currency: string;
  status: TxnStatus;
  channel: string;
  reference: string | null;
  reference_missing: boolean;
  occurred_at: string;
  posted_at: string | null;
  debit_account_id: string;
  credit_account_id: string;
  reversal_of_id: string | null;
  device_id: string | null;
  source_system: string;
  source_record_id: string;
  narrative: string;
  id?: string;
}

export interface AccountData {
  masked_number: string;
  institution: string;
  external: boolean;
  kind: string;
  opened_at: string | null;
  currency: string;
}

export interface EvidenceNodeData {
  kind: string;
  analysis_status: string;
  sha256: string;
  checks: ReconciliationCheck[] | null;
  summary: string | null;
}

export interface AttributionRange {
  min: number;
  fifo: number;
  pro_rata: number;
  max: number;
  amount_minor?: number;
  provenance?: Provenance;
  all_methods_full?: boolean;
}

interface GraphNodeBase {
  id: string;
  label: string;
  provenance: Provenance;
  source_ids: string[];
  depth: number;
  roles?: string[];
  endpoint?: string | null;
  endpoint_reason?: string | null;
  expandable?: boolean;
  provenance_note?: string;
  flags?: string[];
}

export interface AccountNode extends GraphNodeBase {
  type: "account";
  data: AccountData;
}
export interface TransactionNode extends GraphNodeBase {
  type: "transaction";
  direction: "root" | "forward" | "backward";
  time: string;
  data: TransactionData;
  attribution?: AttributionRange;
}
export interface EvidenceNode extends GraphNodeBase {
  type: "evidence";
  data: EvidenceNodeData;
}
export type GraphNode = AccountNode | TransactionNode | EvidenceNode;

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  provenance: Provenance;
  source_ids: string[];
  time: string | null;
  label: string | null;
  data: Partial<AttributionRange> & Record<string, unknown>;
}

export interface TracePath {
  endpoint_account_id: string;
  endpoint: string;
  txn_ids: string[];
  provenance: Provenance;
  note: string;
}

export interface TraceGraph {
  root_txn_id: string;
  params: { direction: string; depth: number; window_hours: number; max_nodes: number; hub_threshold: number };
  window: { start: string; end: string };
  nodes: GraphNode[];
  edges: GraphEdge[];
  paths: TracePath[];
  cycles: string[][];
  truncated: boolean;
  warnings: string[];
  stats: { nodes: number; edges: number; transactions: number; accounts: number; endpoints: number };
}

export type BucketKey =
  | "residual_in_visible_accounts"
  | "left_visibility"
  | "reached_merchant_or_hub"
  | "returned_to_payer"
  | "beyond_trace_limits"
  | "unaccounted";
export type Buckets = Record<BucketKey, number>;

export interface HoldableAccount {
  account_id: string;
  label: string;
  max_minor: number;
  min_minor: number;
  balance_minor: number;
  by_method: Record<AttributionMethod, number>;
}

export interface Attribution {
  disputed_txn_id: string;
  disputed_amount_minor: number;
  currency: string;
  methods: Record<AttributionMethod, string>;
  per_transaction: Record<string, AttributionRange>;
  per_account: Record<
    string,
    { residual: Record<AttributionMethod, number>; balance_at_window_end: number; label: string }
  >;
  buckets: Record<AttributionMethod, Buckets>;
  coverage: Record<AttributionMethod, number>;
  warnings: string[];
  caveat: string;
  evaluable: boolean;
  exits: Record<string, Record<AttributionMethod, number>>;
  holdable: HoldableAccount[];
}

export interface GraphResponse {
  graph: TraceGraph;
  attribution: Attribution;
}

export interface RuleFact {
  text: string;
  source_ids: string[];
}
export interface RuleResult {
  rule_id: string;
  name: string;
  version: number;
  severity: Severity;
  status: RuleStatus;
  facts: RuleFact[];
  source_ids: string[];
  params: Record<string, number | boolean>;
  limitations: string[];
  missing_fields: string[];
  suggested_step: string;
  evaluated_at: string;
}
export interface RulesSummary {
  triggered: number;
  not_triggered: number;
  not_evaluable: number;
  highest_severity: Severity | null;
  by_severity: Record<Severity, number>;
}

export interface ChecklistItem {
  key: string;
  label: string;
  why_it_matters: string;
  required: boolean;
  status: "present" | "missing" | "requested" | "received_not_analysed" | string;
  source_ids: string[];
}
export interface Completeness {
  present: number;
  required: number;
  ratio: number;
  items: ChecklistItem[];
  note: string;
}

export interface ConsistencyCheck {
  check: string;
  result: "consistent" | "contradictory" | "unverifiable" | string;
  detail: string;
  source_ids: string[];
}
export interface Consistency {
  consistent: number;
  contradictory: number;
  unverifiable: number;
  checks: ConsistencyCheck[];
}

export interface Traceability {
  coverage: Record<AttributionMethod, number>;
  coverage_range: [number, number];
  buckets: Record<AttributionMethod, Buckets>;
  endpoints: Record<string, number>;
  paths: number;
  truncated: boolean;
  note: string;
}

export interface PolicyClause {
  clause_id: string;
  policy_id: string;
  text: string;
  status: string;
  reasons: string[];
  needs: string[];
}
export interface Policy {
  category: string;
  report_lag_working_days: number;
  overall: string;
  clauses: PolicyClause[];
  note: string;
}

export interface SlaMilestone {
  key: string;
  label: string;
  due_at: string;
  remaining_hours: number;
  breached: boolean;
  clause_id?: string;
}
export interface Sla {
  policy: string;
  milestones: SlaMilestone[];
  due_at: string | null;
  note: string;
}

export interface ReconciliationCheck {
  field: string;
  result: "matches" | "contradicts" | "unverifiable" | string;
  document_value: string | null;
  ledger_value: string | null;
  ledger_id: string;
}
export interface Reconciliation {
  checks: ReconciliationCheck[];
  matched_txn_id: string;
  summary: string;
  contradictions: number;
  matches: number;
  embedded_instructions_detected: boolean;
  tamper_indicators: string[];
  compared_by: string;
}
export interface EvidenceExtracted {
  document_type?: string;
  is_payment_record?: boolean;
  amount?: string | null;
  currency?: string | null;
  reference?: string | null;
  date_text?: string | null;
  time_text?: string | null;
  payee?: string | null;
  payer?: string | null;
  app_or_bank?: string | null;
  tamper_indicators?: string[];
  embedded_instructions_detected?: boolean;
  legibility?: string;
  summary?: string;
  model?: string;
  prompt_version?: string;
}
export interface EvidenceItem {
  id: string;
  case_id: string;
  kind: string;
  checklist_key: string | null;
  filename: string;
  mime: string;
  sha256: string;
  size: number;
  uploaded_by: string;
  uploaded_at: string;
  analysis_status: "not_analysed" | "analysed" | "failed" | string;
  analysis_note: string | null;
  extracted: EvidenceExtracted | null;
  reconciliation: Reconciliation | null;
  is_synthetic: boolean;
  retention_status?: "active" | "deletion_requested" | "deleted";
  retention_note?: string | null;
  deleted_at?: string | null;
}
export interface EvidenceRequest {
  id: number;
  checklist_key: string;
  requested_from: string;
  status: string;
  note: string;
  created_at: string;
}
export interface Hold {
  id: number;
  account_id: string;
  amount_minor: number;
  currency: string;
  basis: { range?: string; min_minor?: number; max_minor?: number; citations?: string[]; method?: string } | string | null;
  status: "recommended" | "requested" | "declined" | string;
  recommended_by: string;
  decision_note: string | null;
  created_at: string;
  decided_at: string | null;
}
export interface Note {
  id: number;
  author: string;
  body: string;
  created_at: string;
}

export interface ReportBrief {
  id: string;
  case_id: string;
  version: number;
  status: ReportStatus;
  generator: string;
  claims_total: number;
  claims_supported: number;
  claims_flagged: number;
  hallucination_rate: number | null;
  confidence: number | null;
  review_status: "pending" | "accepted" | "rejected" | "partial" | string;
  created_at: string;
  cost_usd: number | null;
  trace_id: string | null;
}

export interface CaseContext {
  case: CaseSummary;
  disputed_transaction: TransactionData & { id: string };
  payer: AccountNode;
  beneficiary: AccountNode;
  graph: TraceGraph;
  attribution: Attribution;
  rules: RuleResult[];
  rules_summary: RulesSummary;
  ruleset_version: string;
  completeness: Completeness;
  consistency: Consistency;
  traceability: Traceability;
  policy: Policy;
  sla: Sla;
  computed_priority: { priority: Priority; reasons: string[] };
  evidence: EvidenceItem[];
  evidence_requests: EvidenceRequest[];
  holds: Hold[];
  generated_at: string;
  notes: Note[];
  latest_report: ReportBrief | null;
  allowed_transitions: CaseStatus[];
  can_edit: boolean;
}

export interface TimelineItem {
  time: string;
  kind: "transaction" | "auth_event" | "case" | "evidence" | string;
  id: string;
  title: string;
  status?: string;
  reference?: string | null;
  provenance: Provenance;
  source_ids: string[];
  role?: string;
  attribution?: AttributionRange | null;
  note?: string | null;
  device?: string | null;
}
export interface TimelineResponse {
  items: TimelineItem[];
  disputed_txn_id: string;
  empty: boolean;
}

export interface RiskResponse {
  rules: RuleResult[];
  summary: RulesSummary;
  ruleset_version: string;
}

export interface EvidenceResponse {
  evidence: EvidenceItem[];
  checklist: Completeness;
  requests: EvidenceRequest[];
  consistency: Consistency;
}

// ------------------------------------------------------------------ reports
export type ReportStatus = "verified" | "partially_verified" | "unverified" | "facts_only" | string;
export type ClaimBasis = "verified" | "derived" | "inferred" | "unknown";
export type ClaimVerdict =
  | "supported"
  | "partial"
  | "unsupported"
  | "contradicted"
  | "unjudged"
  | "system_generated"
  | string;

export interface ClaimIssue {
  code: string;
  detail: string;
  severity?: "error" | "warning" | string;
}
export interface Claim {
  id: string;
  text: string;
  citations: string[];
  basis: ClaimBasis | string;
  section?: string;
  issues: ClaimIssue[];
  valid: boolean;
  verdict: ClaimVerdict;
  verdict_reason?: string;
  hallucination: boolean;
  flagged: boolean;
}
export interface ReportSection {
  key: string;
  title: string;
  claims: Claim[];
}
export interface RecommendedAction {
  action_type: string;
  target_id: string;
  description: string;
  citations: string[];
}
export interface ReportMetrics {
  claims_total: number;
  claims_supported: number;
  claims_partial: number;
  claims_flagged: number;
  claims_unjudged: number;
  hallucinated_claims: number;
  verdicts: Record<string, number>;
  hallucination_rate: number | null;
  confidence: number | null;
  confidence_note: string;
  by_basis: Record<string, number>;
  validation_passed: boolean;
  missing_sections: string[];
  action_issues: { action: string; code: string; detail: string }[];
  draft_attempts: number;
  judge_status: string;
  ai_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  ai_latency_ms: number;
  tool_calls: number;
  notes: string[];
}
export interface RunStep {
  node: string;
  status: string;
  ms: number;
  [k: string]: unknown;
}
export interface ToolLogEntry {
  tool: string;
  target_id: string;
  reason: string;
  status: string;
  new_records: number;
  record_ids?: string[];
  ms?: number;
  round?: number;
  detail?: string;
}
export interface ReportRun {
  id: string;
  status: string;
  steps: RunStep[];
  tool_log: ToolLogEntry[];
  models: string[];
  prompt_versions: Record<string, string>;
  ruleset_version: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_ms: number;
  started_at: string;
}
export type SnapshotRecord = Record<string, unknown>;
export interface Report extends ReportBrief {
  sections: ReportSection[];
  recommended_actions: RecommendedAction[];
  metrics: ReportMetrics;
  snapshot_hash: string;
  review: { claims: Record<string, "accept" | "reject">; note: string } | null;
  trace_url: string | null;
  records: Record<string, SnapshotRecord>;
  run: ReportRun | null;
}
export interface ReportsList {
  reports: ReportBrief[];
}

export interface AskResponse {
  status: "ok" | "not_analysed" | "invalid" | string;
  message?: string;
  claims: Claim[];
  insufficient_data?: boolean;
  follow_up_questions?: string[];
  model?: string;
  cost_usd?: number;
  flagged?: number;
  snapshot_hash?: string;
}
export interface ClassifyResponse {
  status: "ok" | "not_analysed" | string;
  message?: string;
  suggested_category?: string;
  label?: string;
  rationale?: string;
  current_category?: string;
  agrees?: boolean;
  detected_language?: string;
  translation?: string | null;
  token_confidence?: number | null;
  model?: string;
  note?: string;
}

// ------------------------------------------------------------------ audit
export interface AuditEvent {
  id: number;
  case_id: string | null;
  actor: string;
  actor_role: string;
  action: string;
  details: Record<string, unknown>;
  trace_id: string | null;
  created_at: string;
  hash: string;
  prev_hash: string;
}
export interface AuditVerification {
  valid: boolean;
  events: number;
  head?: string;
  broken_at?: number;
}
export interface AuditResponse {
  events: AuditEvent[];
  verification: AuditVerification;
}

// ------------------------------------------------------------------ rules / network / ops
export interface RuleCatalogueEntry {
  rule_id: string;
  name: string;
  description: string;
  severity: Severity;
  version: number;
  params: Record<string, number>;
  default_params: Record<string, number>;
  enabled: boolean;
  needs: string[];
}
export interface RuleVersion {
  version: number;
  params: Record<string, number>;
  enabled: boolean;
  note: string;
  by: string;
  at: string;
}

export interface RingEdge {
  source: string;
  target: string;
  kind: "transfer" | "shared_device" | string;
  ref: string;
}
export interface Ring {
  accounts: string[];
  cases: string[];
  hub_account: string | null;
  shared_devices: string[];
  transfers: unknown[];
  disputed_amount_minor: number;
  currency: string;
  edges: RingEdge[];
  signal: string;
}
export interface RingsResponse {
  rings: Ring[];
  cases_scanned: number;
  accounts_in_trails: number;
  note: string;
}

export interface OpsNode {
  node: string;
  calls: number;
  ok: number;
  errors: Record<string, number>;
  p50_ms: number | null;
  p95_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  models: string[];
}
export interface EvalMetrics {
  deterministic?: { checks: number; passed: number; pass_rate: number; rule_precision: number | null; rule_recall: number | null };
  ai?: {
    reports: number;
    claims_total: number;
    claims_supported: number;
    claims_flagged: number;
    mean_hallucination_rate: number | null;
    mean_confidence: number | null;
    calls: number;
    call_error_rate: number | null;
    p50_latency_ms: number | null;
    total_cost_usd: number;
  };
}
export interface EvalScenario {
  scenario: string;
  case_id: string;
  checks: { check: string; passed: boolean; detail: string }[];
  passed: number;
  total: number;
}
export interface OpsMetrics {
  window_days: number;
  llm: {
    enabled: boolean;
    configured: boolean;
    fast_models: string[];
    pro_models: string[];
    location: string;
    daily_budget_usd: number;
    case_budget_usd: number;
  };
  totals: {
    calls: number;
    ok: number;
    error_rate: number | null;
    cost_usd: number;
    input_tokens: number;
    output_tokens: number;
    reports: number;
    ai_reports: number;
    facts_only_reports: number;
    mean_cost_per_case_usd: number | null;
  };
  nodes: OpsNode[];
  per_day: { day: string; cost_usd: number; calls: number; errors: number }[];
  per_case: { case_id: string; cost_usd: number }[];
  quality: {
    hallucination_trend: {
      report_id: string;
      case_id: string;
      created_at: string;
      generator: string;
      hallucination_rate: number | null;
      confidence: number | null;
      claims: number;
      flagged: number;
      status: string;
    }[];
    mean_hallucination_rate: number | null;
    mean_confidence: number | null;
    verdicts: Record<string, number>;
    report_status: Record<string, number>;
  };
  pricing: { version: string; source: string; table: Record<string, { input: number; output: number }> };
  latest_eval: { id: number; started_at: string; metrics: EvalMetrics } | null;
}
export interface OpsCall {
  id: number;
  run_id: string | null;
  case_id: string | null;
  node: string;
  model: string;
  prompt_version: string;
  status: string;
  input_tokens: number;
  output_tokens: number;
  thinking_tokens: number;
  cost_usd: number;
  latency_ms: number;
  avg_logprob: number | null;
  trace_id: string | null;
  trace_url: string | null;
  error: string | null;
  created_at: string;
}
export interface EvalRun {
  id: number;
  kind?: string;
  started_at?: string;
  metrics: EvalMetrics;
  details: EvalScenario[];
}

// ------------------------------------------------------------------ actions
export type CaseAction =
  | { type: "note"; body: string }
  | { type: "assign"; user_id: number | null }
  | { type: "status"; to: CaseStatus; reason?: string }
  | { type: "request_evidence"; checklist_key: string; requested_from: string; note?: string }
  | { type: "hold"; hold_id: number; decision: "request" | "decline"; note: string; amount_minor?: number }
  | { type: "recategorise"; category: string; reason: string; from_ai?: boolean }
  | { type: "decision"; decision: string; rationale: string; override_reason?: string }
  | { type: "evidence_deletion"; evidence_id: string; decision: "request" | "approve" | "cancel"; note: string };

export interface GraphQueryParams {
  direction: "forward" | "backward" | "both";
  depth: number;
  window_hours: number;
  status: TxnStatus[];
  rel: string[];
  expand: string[];
}
