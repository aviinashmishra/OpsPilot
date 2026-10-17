"use client";

import { keepPreviousData, useQuery, type UseQueryOptions } from "@tanstack/react-query";

import { api, type QueryParams } from "@/lib/api";
import type {
  OnboardingOut,
  AgentCatalogOut,
  AgentDetailOut,
  AgentRunOut,
  ApiKeyOut,
  ApprovalOut,
  AuditEventOut,
  BatchDetailOut,
  BatchOut,
  CopilotSessionOut,
  CopilotStatusOut,
  CustomToolOut,
  SystemQueueOut,
  ToolCatalogOut,
  DemoAccountsOut,
  DocumentOut,
  DocumentSearchOut,
  EvaluationResultOut,
  EventOut,
  IncidentOut,
  IntegrationCatalogOut,
  IntegrationOut,
  OverviewOut,
  Page,
  PermissionCatalogOut,
  ReportOut,
  RoleOut,
  TaskOut,
  TenantOut,
  UsageOut,
  UserOut,
  WorkflowDefinitionOut,
  WorkflowRunOut,
} from "@/lib/types";

export const qk = {
  overview: (days: number) => ["overview", days] as const,
  reports: (days: number) => ["reports", days] as const,
  usage: ["usage"] as const,
  agents: (params: QueryParams) => ["agents", params] as const,
  agent: (key: string) => ["agent", key] as const,
  agentRuns: (key: string, params: QueryParams) => ["agent-runs", key, params] as const,
  workflows: (params: QueryParams) => ["workflows", params] as const,
  workflow: (id: string) => ["workflow", id] as const,
  definitions: ["workflow-definitions"] as const,
  approvals: (params: QueryParams) => ["approvals", params] as const,
  approval: (id: string) => ["approval", id] as const,
  tasks: (params: QueryParams) => ["tasks", params] as const,
  integrations: ["integrations"] as const,
  integrationCatalog: ["integration-catalog"] as const,
  audit: (params: QueryParams) => ["audit", params] as const,
  incidents: (params: QueryParams) => ["incidents", params] as const,
  documents: (collection?: string) => ["documents", collection ?? ""] as const,
  documentSearch: (q: string) => ["document-search", q] as const,
  evaluations: ["evaluations"] as const,
  tenant: ["tenant"] as const,
  users: ["users"] as const,
  roles: ["roles"] as const,
  permissions: ["permissions"] as const,
  apiKeys: ["api-keys"] as const,
  tenants: ["tenants"] as const,
  demoAccounts: ["demo-accounts"] as const,
  events: (params: QueryParams) => ["events", params] as const,
  copilotStatus: ["copilot-status"] as const,
  copilotSessions: ["copilot-sessions"] as const,
  copilotSession: (id: string) => ["copilot-session", id] as const,
  toolCatalog: ["tool-catalog"] as const,
  customTools: ["custom-tools"] as const,
  batches: (params: QueryParams) => ["batches", params] as const,
  batch: (id: string, params: QueryParams) => ["batch", id, params] as const,
  systemQueue: ["system-queue"] as const,
};

type Opts<T> = Omit<UseQueryOptions<T, Error>, "queryKey" | "queryFn">;

export function useOverview(days: number, opts?: Opts<OverviewOut>) {
  return useQuery<OverviewOut, Error>({ queryKey: qk.overview(days), queryFn: () => api<OverviewOut>("/reports/overview", { query: { days } }), placeholderData: keepPreviousData, ...opts });
}

export function useReports(days: number, opts?: Opts<ReportOut>) {
  return useQuery<ReportOut, Error>({ queryKey: qk.reports(days), queryFn: () => api<ReportOut>("/reports", { query: { days } }), placeholderData: keepPreviousData, ...opts });
}

export function useUsage(opts?: Opts<UsageOut>) {
  return useQuery<UsageOut, Error>({ queryKey: qk.usage, queryFn: () => api<UsageOut>("/usage"), ...opts });
}

export function useAgents(params: QueryParams = {}, opts?: Opts<AgentCatalogOut[]>) {
  return useQuery<AgentCatalogOut[], Error>({ queryKey: qk.agents(params), queryFn: () => api<AgentCatalogOut[]>("/agents", { query: params }), placeholderData: keepPreviousData, ...opts });
}

export function useAgent(key: string, opts?: Opts<AgentDetailOut>) {
  return useQuery<AgentDetailOut, Error>({ queryKey: qk.agent(key), queryFn: () => api<AgentDetailOut>(`/agents/${encodeURIComponent(key)}`), enabled: Boolean(key), ...opts });
}

export function useAgentRuns(key: string, params: QueryParams, opts?: Opts<Page<AgentRunOut>>) {
  return useQuery<Page<AgentRunOut>, Error>({ queryKey: qk.agentRuns(key, params), queryFn: () => api<Page<AgentRunOut>>(`/agents/${encodeURIComponent(key)}/runs`, { query: params }), enabled: Boolean(key), placeholderData: keepPreviousData, ...opts });
}

export function useWorkflows(params: QueryParams, opts?: Opts<Page<WorkflowRunOut>>) {
  return useQuery<Page<WorkflowRunOut>, Error>({ queryKey: qk.workflows(params), queryFn: () => api<Page<WorkflowRunOut>>("/workflows", { query: params }), placeholderData: keepPreviousData, ...opts });
}

const LIVE_RUN_STATUSES = new Set(["pending", "running", "waiting_approval", "waiting_input"]);

export function useWorkflow(id: string, opts?: Opts<WorkflowRunOut>) {
  return useQuery<WorkflowRunOut, Error>({
    queryKey: qk.workflow(id),
    queryFn: () => api<WorkflowRunOut>(`/workflows/${encodeURIComponent(id)}`),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data && LIVE_RUN_STATUSES.has(query.state.data.status) ? 4000 : false),
    ...opts,
  });
}

export function useWorkflowDefinitions(opts?: Opts<WorkflowDefinitionOut[]>) {
  return useQuery<WorkflowDefinitionOut[], Error>({ queryKey: qk.definitions, queryFn: () => api<WorkflowDefinitionOut[]>("/workflows/definitions"), staleTime: 5 * 60_000, ...opts });
}

export function useApprovals(params: QueryParams, opts?: Opts<Page<ApprovalOut>>) {
  return useQuery<Page<ApprovalOut>, Error>({ queryKey: qk.approvals(params), queryFn: () => api<Page<ApprovalOut>>("/approvals", { query: params }), placeholderData: keepPreviousData, ...opts });
}

export function useApproval(id: string | null, opts?: Opts<ApprovalOut>) {
  return useQuery<ApprovalOut, Error>({ queryKey: qk.approval(id ?? ""), queryFn: () => api<ApprovalOut>(`/approvals/${encodeURIComponent(id ?? "")}`), enabled: Boolean(id), ...opts });
}

export function useTasks(params: QueryParams, opts?: Opts<Page<TaskOut>>) {
  return useQuery<Page<TaskOut>, Error>({ queryKey: qk.tasks(params), queryFn: () => api<Page<TaskOut>>("/tasks", { query: params }), placeholderData: keepPreviousData, ...opts });
}

export function useIntegrations(opts?: Opts<IntegrationOut[]>) {
  return useQuery<IntegrationOut[], Error>({ queryKey: qk.integrations, queryFn: () => api<IntegrationOut[]>("/integrations"), ...opts });
}

export function useIntegrationCatalog(opts?: Opts<IntegrationCatalogOut>) {
  return useQuery<IntegrationCatalogOut, Error>({ queryKey: qk.integrationCatalog, queryFn: () => api<IntegrationCatalogOut>("/integrations/catalog"), staleTime: 10 * 60_000, ...opts });
}

export function useAuditEvents(params: QueryParams, opts?: Opts<Page<AuditEventOut>>) {
  return useQuery<Page<AuditEventOut>, Error>({ queryKey: qk.audit(params), queryFn: () => api<Page<AuditEventOut>>("/audit-events", { query: params }), placeholderData: keepPreviousData, ...opts });
}

export function useIncidents(params: QueryParams, opts?: Opts<Page<IncidentOut>>) {
  return useQuery<Page<IncidentOut>, Error>({ queryKey: qk.incidents(params), queryFn: () => api<Page<IncidentOut>>("/incidents", { query: params }), placeholderData: keepPreviousData, ...opts });
}

export function useDocuments(collection?: string, opts?: Opts<DocumentOut[]>) {
  return useQuery<DocumentOut[], Error>({ queryKey: qk.documents(collection), queryFn: () => api<DocumentOut[]>("/documents", { query: { collection } }), ...opts });
}

export function useDocumentSearch(q: string, opts?: Opts<DocumentSearchOut>) {
  return useQuery<DocumentSearchOut, Error>({ queryKey: qk.documentSearch(q), queryFn: () => api<DocumentSearchOut>("/documents/search", { query: { q, limit: 10 } }), enabled: q.trim().length >= 2, placeholderData: keepPreviousData, ...opts });
}

export function useEvaluations(opts?: Opts<EvaluationResultOut[]>) {
  return useQuery<EvaluationResultOut[], Error>({ queryKey: qk.evaluations, queryFn: () => api<EvaluationResultOut[]>("/evaluations"), ...opts });
}

export function useTenant(opts?: Opts<TenantOut>) {
  return useQuery<TenantOut, Error>({ queryKey: qk.tenant, queryFn: () => api<TenantOut>("/admin/tenant"), ...opts });
}

export function useUsers(opts?: Opts<UserOut[]>) {
  return useQuery<UserOut[], Error>({ queryKey: qk.users, queryFn: () => api<UserOut[]>("/admin/users"), ...opts });
}

export function useRoles(opts?: Opts<RoleOut[]>) {
  return useQuery<RoleOut[], Error>({ queryKey: qk.roles, queryFn: () => api<RoleOut[]>("/admin/roles"), ...opts });
}

export function usePermissionCatalog(opts?: Opts<PermissionCatalogOut>) {
  return useQuery<PermissionCatalogOut, Error>({ queryKey: qk.permissions, queryFn: () => api<PermissionCatalogOut>("/admin/permissions"), staleTime: 10 * 60_000, ...opts });
}

export function useApiKeys(opts?: Opts<ApiKeyOut[]>) {
  return useQuery<ApiKeyOut[], Error>({ queryKey: qk.apiKeys, queryFn: () => api<ApiKeyOut[]>("/admin/api-keys"), ...opts });
}

export function useTenants(opts?: Opts<TenantOut[]>) {
  return useQuery<TenantOut[], Error>({ queryKey: qk.tenants, queryFn: () => api<TenantOut[]>("/admin/tenants"), ...opts });
}

export function useDemoAccounts(opts?: Opts<DemoAccountsOut>) {
  return useQuery<DemoAccountsOut, Error>({ queryKey: qk.demoAccounts, queryFn: () => api<DemoAccountsOut>("/auth/demo-accounts", { auth: false }), staleTime: Infinity, retry: 1, ...opts });
}

export interface ApiHealthOut {
  status: "ok" | "degraded";
  version: string;
  database: string;
  llm_provider: string;
  ai_available?: boolean;
  ai_next_available_at?: string | null;
  signup_enabled?: boolean;
  worker_mode: string;
  environment: string;
}

export function useOnboarding(opts?: Opts<OnboardingOut>) {
  return useQuery<OnboardingOut, Error>({ queryKey: ["onboarding"], queryFn: () => api<OnboardingOut>("/onboarding"), staleTime: 30_000, ...opts });
}

/** Polls the public API status so the UI can explain outages instead of failing silently. */
export function useApiHealth(opts?: Opts<ApiHealthOut>) {
  return useQuery<ApiHealthOut, Error>({ queryKey: ["api-health"], queryFn: () => api<ApiHealthOut>("/health", { auth: false }), refetchInterval: (q) => (q.state.status === "error" ? 3000 : 30000), retry: false, ...opts });
}

export function useEvents(params: QueryParams, opts?: Opts<Page<EventOut>>) {
  return useQuery<Page<EventOut>, Error>({ queryKey: qk.events(params), queryFn: () => api<Page<EventOut>>("/events", { query: params }), placeholderData: keepPreviousData, ...opts });
}

// --- Ops Copilot --------------------------------------------------------------------------

export function useCopilotStatus(opts?: Opts<CopilotStatusOut>) {
  return useQuery<CopilotStatusOut, Error>({ queryKey: qk.copilotStatus, queryFn: () => api<CopilotStatusOut>("/copilot/status"), staleTime: 60_000, ...opts });
}

/** Session list; polls while any session is still working so busy spinners clear on their own. */
export function useCopilotSessions(opts?: Opts<CopilotSessionOut[]>) {
  return useQuery<CopilotSessionOut[], Error>({
    queryKey: qk.copilotSessions,
    queryFn: () => api<CopilotSessionOut[]>("/copilot/sessions", { query: { limit: 50 } }),
    refetchInterval: (query) => (query.state.data?.some((s) => s.busy) ? 3000 : false),
    ...opts,
  });
}

/** One conversation; polls every second while the assistant is still answering. */
export function useCopilotSession(id: string | null, opts?: Opts<CopilotSessionOut>) {
  return useQuery<CopilotSessionOut, Error>({
    queryKey: qk.copilotSession(id ?? ""),
    queryFn: () => api<CopilotSessionOut>(`/copilot/sessions/${encodeURIComponent(id ?? "")}`),
    enabled: Boolean(id),
    refetchInterval: (query) => (query.state.data?.busy ? 1000 : false),
    ...opts,
  });
}

// --- Tools ---------------------------------------------------------------------------------

export function useToolCatalog(opts?: Opts<ToolCatalogOut>) {
  return useQuery<ToolCatalogOut, Error>({ queryKey: qk.toolCatalog, queryFn: () => api<ToolCatalogOut>("/tools"), staleTime: 60_000, ...opts });
}

export function useCustomTools(opts?: Opts<CustomToolOut[]>) {
  return useQuery<CustomToolOut[], Error>({ queryKey: qk.customTools, queryFn: () => api<CustomToolOut[]>("/custom-tools"), ...opts });
}

// --- Bulk runs -----------------------------------------------------------------------------

export function useBatches(params: QueryParams, opts?: Opts<Page<BatchOut>>) {
  return useQuery<Page<BatchOut>, Error>({
    queryKey: qk.batches(params),
    queryFn: () => api<Page<BatchOut>>("/batches", { query: params }),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => (query.state.data?.items.some((b) => b.status === "running") ? 4000 : false),
    ...opts,
  });
}

/** Batch progress + one page of items; polls every 1.5 s while the batch is running. */
export function useBatch(id: string | null, params: QueryParams, opts?: Opts<BatchDetailOut>) {
  return useQuery<BatchDetailOut, Error>({
    queryKey: qk.batch(id ?? "", params),
    queryFn: () => api<BatchDetailOut>(`/batches/${encodeURIComponent(id ?? "")}`, { query: params }),
    enabled: Boolean(id),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1500 : false),
    ...opts,
  });
}

// --- System --------------------------------------------------------------------------------

export function useSystemQueue(paused: boolean, opts?: Opts<SystemQueueOut>) {
  return useQuery<SystemQueueOut, Error>({ queryKey: qk.systemQueue, queryFn: () => api<SystemQueueOut>("/system/queue"), refetchInterval: paused ? false : 3000, placeholderData: keepPreviousData, ...opts });
}
