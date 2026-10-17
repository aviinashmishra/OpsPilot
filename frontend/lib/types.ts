/**
 * Types mirroring backend/app/api/schemas.py (and the ad-hoc dict responses of
 * the reports/usage/admin routes). Keep in sync with the backend contract.
 */

export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
export type JsonObject = Record<string, unknown>;

export interface ErrorBody {
  code: string;
  message: string;
  details: JsonObject;
  correlation_id: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// --- Auth -------------------------------------------------------------------
export interface LoginRequest {
  /** Workspace slug; optional when the email belongs to a single workspace. */
  tenant?: string;
  email: string;
  password: string;
}

export interface SignupRequest {
  company: string;
  full_name: string;
  email: string;
  password: string;
  sample_data: boolean;
}

export interface OnboardingStep {
  key: string;
  title: string;
  description: string;
  href: string;
  done: boolean;
}

export interface OnboardingOut {
  steps: OnboardingStep[];
  done: number;
  total: number;
  complete: boolean;
  ai: { available: boolean; configured: boolean; next_available_at: string | null };
  sandbox: boolean;
}

export interface UserOut {
  id: string;
  email: string;
  full_name: string;
  roles: string[];
  permissions: string[];
  is_active: boolean;
}

export interface TenantOut {
  id: string;
  slug: string;
  name: string;
  plan: string;
  status: string;
  emergency_disabled: boolean;
  retention_days: number;
  settings: JsonObject;
  quotas: JsonObject;
  feature_flags: JsonObject;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserOut;
  tenant: TenantOut;
}

export interface DemoAccount {
  email: string;
  role: string;
  name: string;
}

export interface DemoAccountsOut {
  tenant?: string;
  /** Only the public local-dev default is returned; null when a custom DEMO_PASSWORD is configured. */
  password?: string | null;
  accounts: DemoAccount[];
}

// --- Events -------------------------------------------------------------------
export interface EventIn {
  source: string;
  event_type: string;
  external_id?: string | null;
  payload: JsonObject;
  workflow_key?: string | null;
}

export interface EventOut {
  id: string;
  status: string;
  event_type: string;
  source: string;
  dedupe_key: string;
  workflow_run_id: string | null;
  duplicate: boolean;
  received_at: string;
}

// --- Workflows ------------------------------------------------------------------
export type GraphNodeType = "agent" | "condition" | "approval_gate" | "parallel" | "workflow" | "action" | "end";

export interface GraphNode {
  type: GraphNodeType | string;
  agent?: string;
  next?: string;
  then?: string;
  else?: string;
  branches?: string[];
  on_failure?: string;
  on_needs_input?: string;
  input?: unknown;
  when?: unknown;
  tool?: string;
  workflow_key?: string;
  action_type?: string;
  [key: string]: unknown;
}

export interface WorkflowGraph {
  start: string;
  nodes: Record<string, GraphNode>;
}

export interface NodeState {
  status?: string;
  summary?: string;
  error?: unknown;
  pending?: string[];
  result?: unknown;
  branches?: string[];
  agent_key?: string;
  agent_run_id?: string;
  data?: JsonObject;
  warnings?: string[];
  actions?: JsonObject[];
  pending_approvals?: string[];
  usage?: JsonObject;
  [key: string]: unknown;
}

export interface CheckpointOut {
  sequence: number;
  node_key: string;
  node_type: string;
  status: string;
  detail: JsonObject;
  duration_ms: number | null;
  created_at: string;
}

export interface AgentRunOut {
  id: string;
  agent_key: string;
  agent_version: string;
  node_key: string | null;
  status: string;
  input: JsonObject;
  output: JsonObject;
  evidence_refs: string[];
  missing_information: string[];
  proposed_actions: JsonObject[];
  warnings: string[];
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  latency_ms: number | null;
  error: JsonObject | null;
  started_at: string;
  finished_at: string | null;
}

export interface WorkflowRunOut {
  id: string;
  workflow_key: string;
  workflow_version: number;
  status: string;
  correlation_id: string;
  actor_id: string | null;
  current_node: string | null;
  step_count: number;
  attempt: number;
  input: JsonObject;
  output: JsonObject;
  state: { nodes?: Record<string, NodeState>; [key: string]: unknown };
  error: JsonObject | null;
  cost_usd: number;
  estimated_minutes_saved: number;
  cancel_requested: boolean;
  parent_run_id: string | null;
  depth: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  deadline_at: string | null;
  checkpoints: CheckpointOut[];
  agent_runs: AgentRunOut[];
  pending_approvals: string[];
  graph: WorkflowGraph | null;
}

export interface WorkflowDefinitionOut {
  id: string;
  key: string;
  name: string;
  description: string | null;
  version: number;
  graph: WorkflowGraph;
  trigger: JsonObject;
  is_active: boolean;
  timeout_seconds: number;
  scope: "platform" | "tenant";
}

export interface WorkflowStartIn {
  workflow_key: string;
  input: JsonObject;
}

// --- Agents ---------------------------------------------------------------------
export type RiskLevel = "low" | "medium" | "high" | "critical";

export interface AgentStats {
  runs: number;
  succeeded: number;
  failed: number;
  needs_approval: number;
  cost_usd: number;
  avg_latency_ms: number;
  success_rate: number | null;
}

export interface ApprovalRule {
  action_type: string;
  condition: string | null;
  required_permission: string;
  always: boolean;
}

export interface AgentCatalogOut {
  agent_key: string;
  name: string;
  department: string;
  department_label: string;
  description: string;
  use_cases: string[];
  current_version: string;
  allowed_tools: string[];
  permission_scopes: string[];
  policies: string[];
  approval_rules: ApprovalRule[];
  timeout_seconds: number;
  token_budget: number;
  risk_level: RiskLevel | string;
  baseline_minutes_saved: number;
  enabled: boolean;
  globally_enabled: boolean;
  tenant_config: JsonObject;
  model_override: string | null;
  disabled_reason: string | null;
  stats: AgentStats;
}

export interface ToolDescription {
  key: string;
  name: string;
  description: string;
  provider: string;
  side_effect: boolean;
  idempotent: boolean;
  required_permission: string;
  risk_level: string;
  input_schema: JsonObject;
}

export interface AgentEvaluationSummary {
  metrics: EvaluationMetrics;
  passed: boolean;
  created_at: string;
  model: string | null;
  cases: number;
}

export interface AgentDetailOut extends AgentCatalogOut {
  input_schema: JsonSchema;
  output_schema: JsonSchema;
  tools: ToolDescription[];
  recent_runs: AgentRunOut[];
  evaluation: AgentEvaluationSummary | null;
  /** A known-good input (first evaluation case), used to pre-fill the playground and bulk run. */
  example_input?: JsonObject | null;
}

export interface AgentSettingIn {
  enabled?: boolean | null;
  config?: JsonObject | null;
  model_override?: string | null;
  disabled_reason?: string | null;
}

export interface AgentRunIn {
  input: JsonObject;
  mode: "direct" | "workflow";
}

export interface AgentRunResult {
  data?: JsonObject;
  summary?: string | null;
  evidence_refs?: string[];
  missing_information?: string[];
  warnings?: string[];
  proposed_actions?: JsonObject[];
  confidence?: number | null;
  error?: JsonObject | null;
  [key: string]: unknown;
}

export interface AgentRunDirectOut {
  agent_run_id: string;
  status: string;
  result: AgentRunResult;
  actions: JsonObject[];
  latency_ms: number;
  usage: { prompt_tokens?: number; completion_tokens?: number; cost_usd?: number; model?: string | null; [k: string]: unknown };
  tool_modes: string[];
  workflow_run_id: string | null;
}

// JSON schema (subset used by the playground)
export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  enum?: unknown[];
  default?: unknown;
  examples?: unknown[];
  anyOf?: JsonSchema[];
  oneOf?: JsonSchema[];
  allOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  definitions?: Record<string, JsonSchema>;
  additionalProperties?: boolean | JsonSchema;
  minimum?: number;
  maximum?: number;
  format?: string;
  [key: string]: unknown;
}

// --- Tasks ----------------------------------------------------------------------
export type TaskStatus = "open" | "in_progress" | "blocked" | "done" | "cancelled";
export type TaskPriority = "low" | "medium" | "high" | "critical";

export interface TaskIn {
  title: string;
  description?: string | null;
  priority: TaskPriority;
  owner_user_id?: string | null;
  owner_name?: string | null;
  due_at?: string | null;
  labels: string[];
}

export interface TaskUpdateIn {
  title?: string;
  description?: string | null;
  status?: TaskStatus;
  priority?: TaskPriority;
  owner_user_id?: string | null;
  owner_name?: string | null;
  due_at?: string | null;
  labels?: string[];
}

export interface TaskOut {
  id: string;
  title: string;
  description: string | null;
  status: TaskStatus | string;
  priority: TaskPriority | string;
  owner_user_id: string | null;
  owner_name: string | null;
  due_at: string | null;
  sla_hours: number | null;
  source: string;
  source_run_id: string | null;
  evidence_refs: string[];
  labels: string[];
  depends_on: string[];
  escalation_level: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  overdue: boolean;
}

// --- Approvals ------------------------------------------------------------------
export interface ApprovalOut {
  id: string;
  run_id: string | null;
  agent_run_id: string | null;
  agent_key: string | null;
  node_key: string | null;
  action_type: string;
  tool_key: string | null;
  action_payload: JsonObject;
  payload_hash: string;
  context: JsonObject;
  evidence: string[];
  reason: string | null;
  risk_level: string;
  policy_id: string | null;
  policy_version: string | null;
  status: string;
  requested_by: string | null;
  required_permission: string;
  reviewer_id: string | null;
  reviewer_name: string | null;
  decided_at: string | null;
  decision_note: string | null;
  expires_at: string;
  executed_at: string | null;
  execution_result: JsonObject | null;
  created_at: string;
}

export interface ApprovalDecisionIn {
  decision: "approve" | "reject";
  note?: string | null;
  payload_hash?: string | null;
}

export interface ApprovalDecisionOut {
  approval_id: string;
  status: string;
  execution?: JsonObject;
  approval: ApprovalOut;
}

// --- Integrations ---------------------------------------------------------------
export interface IntegrationIn {
  provider: string;
  name: string;
  mode: "mock" | "live";
  live_provider?: string | null;
  config: JsonObject;
  credentials?: JsonObject | null;
  webhook_secret?: string | null;
  scopes: string[];
}

export interface IntegrationOut {
  id: string;
  provider: string;
  provider_label: string;
  name: string;
  mode: string;
  status: string;
  live_provider: string | null;
  config: JsonObject;
  scopes: string[];
  has_credentials: boolean;
  has_webhook_secret: boolean;
  last_sync_at: string | null;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_error: string | null;
  health: JsonObject;
  capabilities: string[];
  tools: string[];
  created_at: string;
}

export interface ConnectionTestOut {
  ok: boolean;
  mode: string;
  provider: string;
  message: string;
  details: JsonObject;
}

export interface IntegrationFamily {
  key: string;
  label: string;
  live_providers: string[];
  icon: string;
  live_supported: string[];
  required_credentials: Record<string, string[]>;
  sandbox_capabilities: string[];
}

export interface IntegrationCatalogOut {
  families: IntegrationFamily[];
}

// --- Reports / usage / audit ------------------------------------------------------
export interface AuditEventOut {
  id: string;
  created_at: string;
  actor_id: string | null;
  actor_type: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  correlation_id: string | null;
  details: JsonObject;
  severity: string;
  hash: string;
  prev_hash: string | null;
}

export interface AuditVerifyOut {
  ok: boolean;
  checked: number;
  broken_at?: string;
  reason?: string;
}

export interface IncidentOut {
  id: string;
  severity: string;
  title: string;
  source: string;
  kind: string;
  status: string;
  details: JsonObject;
  run_id: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface DailySeriesPoint {
  date: string;
  completed: number;
  failed: number;
  other: number;
  cost_usd: number;
  minutes_saved: number;
}

export interface DepartmentBreakdown {
  department: string;
  label: string;
  runs: number;
  succeeded: number;
  failed: number;
}

export interface OverviewOut {
  active_agents: number;
  total_agents: number;
  workflows_executed: number;
  workflows_succeeded: number;
  workflows_failed: number;
  workflows_running: number;
  estimated_minutes_saved: number;
  realized_savings_usd: number;
  ai_cost_usd: number;
  infra_cost_usd: number;
  pending_approvals: number;
  open_incidents: number;
  recent_incidents: IncidentOut[];
  recent_runs: WorkflowRunOut[];
  daily_series: DailySeriesPoint[];
  department_breakdown: DepartmentBreakdown[];
  integration_modes: Record<string, number>;
  period: { days: number; since: string };
}

export interface ReportKpis {
  workflow_runs: number;
  workflow_completion_rate: number | null;
  workflow_failure_rate: number | null;
  cost_per_successful_workflow_usd: number | null;
  median_latency_ms: number | null;
  p95_latency_ms: number | null;
  token_consumption: number;
  tool_executions: number;
  tool_failure_rate: number | null;
  side_effect_actions: number;
  duplicate_actions_suppressed: number;
  duplicate_external_action_rate: number | null;
  validation_failures: number;
  approvals_requested: number;
  approval_rate: number | null;
  approval_latency_minutes_avg: number | null;
  human_intervention_rate: number | null;
}

export interface RoiAssumptions {
  loaded_hourly_cost_usd: number;
  infra_cost_per_run_usd: number;
  realization_rate: number;
  monthly_platform_fee_usd: number;
}

export interface ReportRoi {
  assumptions: RoiAssumptions;
  estimated_minutes_saved: number;
  estimated_labor_value_usd: number;
  realized_savings_usd: number;
  ai_cost_usd: number;
  infra_cost_usd: number;
  net_estimated_value_usd: number;
  note: string;
}

export interface ReportAgentRow {
  agent_key: string;
  name: string;
  department: string;
  runs: number;
  succeeded: number;
  failed: number;
  needs_approval: number;
  needs_input: number;
  cost_usd: number;
  tokens: number;
  warnings: number;
  missing_info: number;
  success_rate: number | null;
  human_intervention_rate: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  cost_per_success_usd: number | null;
}

export interface ReportWorkflowRow {
  workflow_key: string;
  runs: number;
  completed: number;
  failed: number;
  waiting: number;
  cost_usd: number;
  minutes_saved: number;
}

export interface ReportOut {
  period_days: number;
  kpis: ReportKpis;
  roi: ReportRoi;
  agents: ReportAgentRow[];
  workflows: ReportWorkflowRow[];
}

export interface UsageTotal {
  quantity: number;
  cost_usd: number;
}

export interface UsageOut {
  period: string;
  totals: Record<string, UsageTotal>;
  total_cost_usd: number;
  plan: string;
  quotas: { monthly_workflow_runs: number; monthly_llm_tokens: number; max_concurrent_runs: number };
  utilization: { workflow_runs: number | null; llm_tokens: number | null };
}

// --- Admin -----------------------------------------------------------------------------
export interface TenantIn {
  slug: string;
  name: string;
  plan: string;
  admin_email: string;
  admin_name: string;
  admin_password?: string | null;
}

export interface TenantUpdateIn {
  name?: string;
  plan?: string;
  status?: "active" | "suspended" | "disabled";
  settings?: JsonObject;
  quotas?: JsonObject;
  feature_flags?: JsonObject;
  retention_days?: number;
  emergency_disabled?: boolean;
}

export interface UserIn {
  email: string;
  full_name: string;
  password?: string | null;
  roles: string[];
  external_subject?: string | null;
}

export interface UserUpdateIn {
  full_name?: string;
  roles?: string[];
  is_active?: boolean;
  password?: string;
}

export interface RoleIn {
  name: string;
  description?: string | null;
  permissions: string[];
}

export interface RoleOut {
  id: string;
  name: string;
  description: string | null;
  permissions: string[];
  is_system: boolean;
  user_count: number;
}

export interface PermissionCatalogOut {
  permissions: string[];
  system_roles: Record<string, { description: string; permissions: string[] }>;
}

export interface ApiKeyIn {
  name: string;
  scopes: string[];
  expires_in_days?: number | null;
}

export interface ApiKeyOut {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  plaintext: string | null;
}

// --- Documents -------------------------------------------------------------------------
export interface DocumentOut {
  id: string;
  name: string;
  collection: string;
  content_type: string;
  size_bytes: number;
  sha256: string | null;
  classification: string;
  scan_status: string;
  scan_findings: JsonObject[];
  chunk_count: number;
  meta: JsonObject;
  created_at: string;
}

export interface DocumentTextIn {
  name: string;
  collection: string;
  text: string;
  classification: "public" | "internal" | "confidential" | "restricted";
  meta: JsonObject;
}

export interface DocumentSearchHit {
  ref: string;
  document_id: string;
  document_name: string;
  collection: string;
  section: string | null;
  text: string;
  score: number;
}

export interface DocumentSearchOut {
  items: DocumentSearchHit[];
}

// --- Ops Copilot ---------------------------------------------------------------------------
export type CopilotMode = "claude" | "gemini" | "openai" | "offline_planner";

export interface AiRouteStatus {
  provider: string;
  model: string;
  fast_model: string;
  tools: boolean;
  state: "ready" | "cooling";
  until: string | null;
  reason: string | null;
}

/** Availability of the AI routes (primary model, fallback models, other providers). */
export interface AiStatus {
  available: boolean;
  active: { provider: string; model: string } | null;
  next_available_at: string | null;
  routes: AiRouteStatus[];
}
export type CopilotToolKind = "agent" | "tool" | "custom" | "platform";
export type CopilotMessageStatus = "pending" | "running" | "done" | "failed";
export type CopilotStepStatus = "running" | "ok" | "error" | "needs_approval";

export interface CopilotToolInfo {
  name: string;
  kind: CopilotToolKind | string;
  label: string;
  description: string;
}

export interface CopilotStatusOut {
  mode: CopilotMode | string;
  model: string | null;
  provider: string;
  tool_counts: Partial<Record<CopilotToolKind, number>> & Record<string, number | undefined>;
  tools: CopilotToolInfo[];
  suggestions: string[];
  ai?: AiStatus;
}

export interface CopilotStepOut {
  id: string;
  sequence: number;
  iteration: number;
  tool_name: string;
  kind: CopilotToolKind | string;
  label: string;
  input: JsonObject;
  output: JsonObject;
  summary: string | null;
  status: CopilotStepStatus | string;
  duration_ms: number | null;
  approval_ids: string[];
  agent_run_id: string | null;
  workflow_run_id: string | null;
  created_at: string;
}

export interface CopilotUsage {
  tool_calls?: number;
  iterations?: number;
  latency_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  cost_usd?: number;
  calls?: number;
  stop_reason?: string;
  [key: string]: unknown;
}

export interface CopilotMessageOut {
  id: string;
  sequence: number;
  role: "user" | "assistant" | string;
  text: string;
  status: CopilotMessageStatus | string;
  mode: CopilotMode | string | null;
  model: string | null;
  usage: CopilotUsage;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  steps: CopilotStepOut[];
}

export interface CopilotSessionOut {
  id: string;
  title: string;
  correlation_id: string;
  cost_usd: number;
  tokens: number;
  created_at: string;
  updated_at: string;
  busy: boolean;
  messages: CopilotMessageOut[];
}

export interface CopilotMessageIn {
  message: string;
}

// --- Tools / custom tools ----------------------------------------------------------------------
export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface BuiltinToolOut extends ToolDescription {
  used_by: string[];
  calls_30d: number;
  source: "builtin";
}

export interface CustomToolOut {
  id: string;
  key: string;
  name: string;
  description: string;
  method: HttpMethod | string;
  url_template: string;
  headers: Record<string, string>;
  auth_header_name: string | null;
  has_secret: boolean;
  input_schema: JsonSchema;
  side_effect: boolean;
  risk_level: RiskLevel | string;
  timeout_seconds: number;
  enabled: boolean;
  call_count: number;
  last_called_at: string | null;
  created_at: string;
}

export interface CatalogCustomToolOut extends CustomToolOut {
  source: "custom";
  calls_30d: number;
}

export interface ToolCatalogOut {
  builtin: BuiltinToolOut[];
  custom: CatalogCustomToolOut[];
  providers: string[];
}

export interface CustomToolIn {
  name: string;
  description: string;
  method: HttpMethod;
  url_template: string;
  headers: Record<string, string>;
  auth_header_name?: string | null;
  auth_secret?: string | null;
  input_schema: JsonObject;
  side_effect: boolean;
  risk_level: RiskLevel;
  timeout_seconds: number;
  enabled: boolean;
}

export type CustomToolPatch = Partial<Omit<CustomToolIn, "name">>;

export interface CustomToolTestIn {
  input: JsonObject;
  confirm_side_effect: boolean;
}

export interface CustomToolTestOut {
  ok: boolean;
  latency_ms: number;
  result: unknown;
  error: string | null;
}

// --- Bulk runs -------------------------------------------------------------------------------
export type BatchStatus = "running" | "completed" | "cancelled";
export type BatchItemStatus = "queued" | "running" | "completed" | "needs_review" | "failed" | "cancelled";

export interface BatchIn {
  items: JsonObject[];
  name?: string | null;
  execute_actions?: boolean;
}

export interface BatchOut {
  id: string;
  agent_key: string;
  name: string;
  status: BatchStatus | string;
  total: number;
  succeeded: number;
  failed: number;
  needs_review: number;
  processed: number;
  progress: number;
  execute_actions: boolean;
  created_by: string | null;
  correlation_id: string;
  cost_usd: number;
  created_at: string;
  finished_at: string | null;
  elapsed_seconds: number | null;
}

export interface BatchItemOut {
  index: number;
  status: BatchItemStatus | string;
  summary: string | null;
  error: string | null;
  approval_ids: string[];
  agent_run_id: string | null;
  latency_ms: number | null;
  input: JsonObject;
}

export interface BatchDetailOut extends BatchOut {
  items: BatchItemOut[];
  items_limit: number;
  items_offset: number;
}

// --- System / job queue ----------------------------------------------------------------------
export type JobStatus = "queued" | "running" | "done" | "failed" | "dead";

export interface WorkerOut {
  name: string;
  hostname: string;
  pid: number;
  concurrency: number;
  active_jobs: number;
  processed: number;
  failed: number;
  status: "alive" | "stopped" | "lost" | string;
  last_seen_at: string;
}

export interface JobOut {
  id: string;
  kind: string;
  status: JobStatus | string;
  attempts: number;
  max_attempts: number;
  locked_by: string | null;
  last_error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface SystemQueueOut {
  worker_mode: string;
  by_status: Record<JobStatus, number>;
  by_kind: Array<{ kind: string; status: JobStatus | string; count: number }>;
  oldest_ready_lag_seconds: number;
  throughput_last_hour: number;
  workers: WorkerOut[];
  alive_workers: number;
  total_concurrency: number;
  recent_jobs: JobOut[];
}

// --- Evaluations ---------------------------------------------------------------------------
export interface EvaluationMetrics {
  cases?: number;
  passed?: number;
  accuracy?: number;
  extraction_precision?: number | null;
  extraction_recall?: number | null;
  unsupported_claim_rate?: number;
  human_intervention_rate?: number;
  cost_per_case_usd?: number;
  p50_latency_ms?: number | null;
  p95_latency_ms?: number | null;
  [key: string]: unknown;
}

export interface EvaluationCaseResult {
  name: string;
  passed: boolean;
  checks: Array<{ check: string; expected: unknown; actual: unknown; passed: boolean }>;
}

export interface EvaluationResultOut {
  id: string;
  agent_key: string;
  agent_version: string;
  model: string | null;
  metrics: EvaluationMetrics;
  case_results: EvaluationCaseResult[];
  passed: boolean;
  created_at: string;
}
