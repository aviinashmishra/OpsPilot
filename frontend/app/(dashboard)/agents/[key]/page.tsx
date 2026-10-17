"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, FlaskConical, Layers, Play, RotateCcw, Save, ShieldCheck, Wrench } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { AgentRunDetails, AgentRunSummaryLine } from "@/components/agents/agent-run-details";
import { AgentRunResultView } from "@/components/agents/agent-run-result";
import { BulkRunTab } from "@/components/agents/bulk-run-tab";
import { Badge, RiskBadge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardToolbar } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, Input, Textarea } from "@/components/ui/input";
import { JsonEditor } from "@/components/ui/json-editor";
import { JsonViewer } from "@/components/ui/json-viewer";
import { ChipList, KeyValueList } from "@/components/ui/key-value";
import { Collapsible } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { Skeleton, SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Switch } from "@/components/ui/switch";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, errorMessage, idempotencyKey } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import { useAgent, useAgentRuns } from "@/lib/queries";
import { schemaDefaults, schemaFields } from "@/lib/schema-defaults";
import type { AgentCatalogOut, AgentDetailOut, AgentRunDirectOut, AgentSettingIn, EvaluationResultOut } from "@/lib/types";
import { fmtCurrency, fmtDateTime, fmtInt, fmtMs, fmtPercent, fmtRelative, prettyJson, safeJsonParse } from "@/lib/utils";

const RUNS_PAGE = 10;
const AGENT_TABS = ["overview", "contract", "config", "runs", "evaluation", "playground", "bulk"] as const;
type AgentTab = (typeof AGENT_TABS)[number];

export default function AgentDetailPage({ params }: { params: { key: string } }) {
  const agent = useAgent(params.key);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const canRun = usePermission("agents:run");
  // Playground and Bulk run only exist for people who can run agents (no dead-end tabs).
  const allowedTabs: readonly string[] = canRun ? AGENT_TABS : AGENT_TABS.filter((t) => t !== "playground" && t !== "bulk");
  const tab: AgentTab = allowedTabs.includes(requestedTab ?? "") ? (requestedTab as AgentTab) : "overview";
  const setTab = (next: string) => {
    const query = new URLSearchParams(searchParams.toString());
    if (next === "overview") query.delete("tab");
    else query.set("tab", next);
    const qs = query.toString();
    router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
  };
  const canAdmin = usePermission("agents:admin");
  const queryClient = useQueryClient();
  const [confirmToggle, setConfirmToggle] = useState<boolean | null>(null);
  const [reason, setReason] = useState("");

  const toggle = useMutation({
    mutationFn: (enabled: boolean) => {
      const body: AgentSettingIn = { enabled, disabled_reason: enabled ? null : reason.trim() || "Disabled from dashboard" };
      return api<AgentCatalogOut>(`/agents/${params.key}`, { method: "PATCH", body });
    },
    onSuccess: (updated) => {
      toast.success(`${updated.name} ${updated.enabled ? "enabled" : "disabled"}`);
      void queryClient.invalidateQueries({ queryKey: ["agent", params.key] });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      setConfirmToggle(null);
      setReason("");
    },
    onError: (error) => toast.error("Could not update agent", { description: errorMessage(error) }),
  });

  if (agent.isError) return <ErrorState error={agent.error} onRetry={() => agent.refetch()} />;
  if (agent.isLoading || !agent.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-16 w-2/3" />
        <SkeletonRows rows={8} />
      </div>
    );
  }
  const a = agent.data;

  return (
    <div className="space-y-5">
      <PageHeader
        crumbs={[{ label: "Agents", href: "/agents" }, { label: a.department_label, href: `/agents?department=${a.department}` }, { label: a.name }]}
        title={a.name}
        badge={
          <>
            <StatusPill status={a.enabled ? "active" : "disabled"} label={a.enabled ? "Enabled" : "Disabled"} />
            <RiskBadge level={a.risk_level} />
            <Badge>v{a.current_version}</Badge>
          </>
        }
        description={a.description}
        actions={
          <label className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5 text-sm">
            <span className="text-fg-muted">Enabled for tenant</span>
            <Switch checked={a.enabled} disabled={!canAdmin || !a.globally_enabled} onCheckedChange={(checked) => setConfirmToggle(checked)} aria-label="Enable agent for this tenant" />
          </label>
        }
      />
      {a.disabled_reason ? <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">{a.disabled_reason}</p> : null}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="w-full justify-start sm:w-auto">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="contract">Contract</TabsTrigger>
          <TabsTrigger value="config">Configuration</TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
          <TabsTrigger value="evaluation">Evaluation</TabsTrigger>
          {canRun ? (
            <>
              <TabsTrigger value="playground">
                <Play className="h-3.5 w-3.5" aria-hidden /> Playground
              </TabsTrigger>
              <TabsTrigger value="bulk">
                <Layers className="h-3.5 w-3.5" aria-hidden /> Bulk run
              </TabsTrigger>
            </>
          ) : null}
        </TabsList>
        <TabsContent value="overview">
          <OverviewTab agent={a} />
        </TabsContent>
        <TabsContent value="contract">
          <ContractTab agent={a} />
        </TabsContent>
        <TabsContent value="config">
          <ConfigTab agent={a} canAdmin={canAdmin} />
        </TabsContent>
        <TabsContent value="runs">
          <RunsTab agentKey={a.agent_key} />
        </TabsContent>
        <TabsContent value="evaluation">
          <EvaluationTab agent={a} canAdmin={canAdmin} />
        </TabsContent>
        {canRun ? (
          <>
            <TabsContent value="playground">
              <PlaygroundTab agent={a} canRun={canRun} />
            </TabsContent>
            <TabsContent value="bulk">
              <BulkRunTab agent={a} canRun={canRun} />
            </TabsContent>
          </>
        ) : null}
      </Tabs>

      <ConfirmDialog
        open={confirmToggle !== null}
        onOpenChange={(open) => {
          if (!open) {
            setConfirmToggle(null);
            setReason("");
          }
        }}
        title={confirmToggle ? `Enable ${a.name}?` : `Disable ${a.name}?`}
        description={confirmToggle ? "The agent becomes available to workflows and the playground for this tenant." : "Workflows that reach this agent will fail with agent_disabled until it is re-enabled."}
        confirmLabel={confirmToggle ? "Enable" : "Disable"}
        tone={confirmToggle ? "primary" : "danger"}
        loading={toggle.isPending}
        onConfirm={() => {
          if (confirmToggle !== null) toggle.mutate(confirmToggle);
        }}
      >
        {confirmToggle === false ? (
          <Field label="Reason (shown to operators)" htmlFor="disable-reason">
            <Textarea id="disable-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}

function OverviewTab({ agent }: { agent: AgentDetailOut }) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <Card>
          <CardToolbar title="Use cases" />
          <CardContent>
            <ul className="grid gap-2 sm:grid-cols-2">
              {agent.use_cases.map((u) => (
                <li key={u} className="rounded-md border border-border bg-surface-2/60 px-3 py-2 text-sm text-fg">
                  {u}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardToolbar title="Allowed tools" />
          <CardContent className="px-0 pb-0">
            {agent.tools.length === 0 ? (
              <div className="px-5 pb-5">
                <EmptyState compact icon={Wrench} title="No tools" description="This agent reads nothing from external systems." />
              </div>
            ) : (
              <TableWrap className="rounded-none border-x-0 border-b-0">
                <Table>
                  <THead>
                    <TR>
                      <TH>Tool</TH>
                      <TH>Provider</TH>
                      <TH>Side effect</TH>
                      <TH>Risk</TH>
                      <TH>Permission</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {agent.tools.map((tool) => (
                      <TR key={tool.key}>
                        <TD>
                          <span className="font-medium">{tool.name}</span>
                          <span className="block font-mono text-[11px] text-fg-subtle">{tool.key}</span>
                          <span className="block text-xs text-fg-muted">{tool.description}</span>
                        </TD>
                        <TD className="text-fg-muted">{tool.provider}</TD>
                        <TD>
                          {tool.side_effect ? (
                            <Badge tone="warning" size="sm">
                              side effect
                            </Badge>
                          ) : (
                            <Badge size="sm">read-only</Badge>
                          )}
                        </TD>
                        <TD>
                          <RiskBadge level={tool.risk_level} size="sm" />
                        </TD>
                        <TD>
                          <code className="font-mono text-[11px] text-fg-muted">{tool.required_permission}</code>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </TableWrap>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardToolbar title="Approval rules" />
          <CardContent>
            {agent.approval_rules.length === 0 ? (
              <p className="text-sm text-fg-subtle">No agent-level approval rules; tenant policies still apply.</p>
            ) : (
              <ul className="space-y-2">
                {agent.approval_rules.map((rule, i) => (
                  <li key={i} className="flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface-2/60 px-3 py-2 text-sm">
                    <ShieldCheck className="h-4 w-4 text-accent" aria-hidden />
                    <code className="font-mono text-xs">{rule.action_type}</code>
                    <span className="text-fg-muted">{rule.condition ?? (rule.always ? "always" : "")}</span>
                    <Badge size="sm" className="ml-auto">
                      requires {rule.required_permission}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
      <div className="space-y-4">
        <Card>
          <CardToolbar title="Budgets" />
          <CardContent>
            <KeyValueList
              columns={1}
              dense
              items={[
                { label: "Timeout", value: `${agent.timeout_seconds} s` },
                { label: "Token budget", value: fmtInt(agent.token_budget) },
                { label: "Baseline minutes saved / run", value: `${agent.baseline_minutes_saved} min` },
                { label: "Department", value: agent.department_label },
                { label: "Agent key", value: agent.agent_key, mono: true },
              ]}
            />
          </CardContent>
        </Card>
        <Card>
          <CardToolbar title="Permission scopes" />
          <CardContent>
            <ChipList items={agent.permission_scopes} tone="accent" />
          </CardContent>
        </Card>
        <Card>
          <CardToolbar title="Policies" />
          <CardContent>
            <ChipList items={agent.policies} />
          </CardContent>
        </Card>
        <Card>
          <CardToolbar title="Tenant stats" />
          <CardContent>
            <KeyValueList
              columns={2}
              dense
              items={[
                { label: "Runs", value: fmtInt(agent.stats.runs) },
                { label: "Success rate", value: fmtPercent(agent.stats.success_rate, 0) },
                { label: "Needs approval", value: fmtInt(agent.stats.needs_approval) },
                { label: "Failed", value: fmtInt(agent.stats.failed) },
                { label: "Avg latency", value: fmtMs(agent.stats.avg_latency_ms) },
                { label: "Cost", value: fmtCurrency(agent.stats.cost_usd) },
              ]}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function ContractTab({ agent }: { agent: AgentDetailOut }) {
  const inputFields = schemaFields(agent.input_schema);
  const outputFields = schemaFields(agent.output_schema);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {[
        { title: "Input schema", fields: inputFields, schema: agent.input_schema },
        { title: "Output schema", fields: outputFields, schema: agent.output_schema },
      ].map((section) => (
        <Card key={section.title}>
          <CardToolbar title={section.title} description={section.schema.title ? `${section.schema.title}` : undefined} />
          <CardContent className="space-y-3">
            {section.fields.length > 0 ? (
              <TableWrap>
                <Table className="min-w-[420px]">
                  <THead>
                    <TR>
                      <TH>Field</TH>
                      <TH>Type</TH>
                      <TH>Required</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {section.fields.map((f) => (
                      <TR key={f.name}>
                        <TD>
                          <code className="font-mono text-xs">{f.name}</code>
                          {f.description ? <span className="block text-xs text-fg-muted">{f.description}</span> : null}
                        </TD>
                        <TD>
                          <code className="font-mono text-[11px] text-fg-muted">{f.type}</code>
                        </TD>
                        <TD>{f.required ? <Badge size="sm" tone="accent">required</Badge> : <span className="text-xs text-fg-subtle">optional</span>}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </TableWrap>
            ) : null}
            <JsonViewer value={section.schema} collapsed title="JSON schema" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function ConfigTab({ agent, canAdmin }: { agent: AgentDetailOut; canAdmin: boolean }) {
  const queryClient = useQueryClient();
  const [config, setConfig] = useState(prettyJson(agent.tenant_config));
  const [valid, setValid] = useState(true);
  const [model, setModel] = useState(agent.model_override ?? "");

  useEffect(() => {
    setConfig(prettyJson(agent.tenant_config));
    setModel(agent.model_override ?? "");
  }, [agent.tenant_config, agent.model_override]);

  const save = useMutation({
    mutationFn: () => {
      const parsed = safeJsonParse(config || "{}");
      if (!parsed.ok) throw new Error(parsed.error);
      if (typeof parsed.value !== "object" || parsed.value === null || Array.isArray(parsed.value)) throw new Error("Config must be a JSON object");
      const body: AgentSettingIn = { config: parsed.value as Record<string, unknown>, model_override: model.trim() };
      return api<AgentCatalogOut>(`/agents/${agent.agent_key}`, { method: "PATCH", body });
    },
    onSuccess: () => {
      toast.success("Agent configuration saved");
      void queryClient.invalidateQueries({ queryKey: ["agent", agent.agent_key] });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
    },
    onError: (error) => toast.error("Could not save configuration", { description: errorMessage(error) }),
  });

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardToolbar title="Tenant configuration" description="Optional JSON settings for this agent." />
        <CardContent className="space-y-4">
          <JsonEditor label="agent_config" value={config} onChange={setConfig} onValidChange={setValid} rows={14} disabled={!canAdmin} />
          <Field label="Model override" htmlFor="model-override" hint="Leave empty to use the platform default model for this agent's tier.">
            <Input id="model-override" value={model} onChange={(e) => setModel(e.target.value)} placeholder="e.g. claude-sonnet-5-5" disabled={!canAdmin} />
          </Field>
          <div className="flex items-center gap-2">
            <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!canAdmin || !valid} leftIcon={<Save className="h-4 w-4" aria-hidden />}>
              Save changes
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setConfig(prettyJson(agent.tenant_config));
                setModel(agent.model_override ?? "");
              }}
              leftIcon={<RotateCcw className="h-4 w-4" aria-hidden />}
            >
              Reset
            </Button>
            {!canAdmin ? <span className="text-xs text-fg-subtle">Requires agents:admin</span> : null}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardToolbar title="Effective settings" />
        <CardContent>
          <KeyValueList
            columns={1}
            dense
            items={[
              { label: "Enabled (tenant)", value: agent.enabled ? "Yes" : "No" },
              { label: "Enabled (globally)", value: agent.globally_enabled ? "Yes" : "No" },
              { label: "Model override", value: agent.model_override ?? "platform default" },
              { label: "Disabled reason", value: agent.disabled_reason ?? "—" },
            ]}
          />
        </CardContent>
      </Card>
    </div>
  );
}

function RunsTab({ agentKey }: { agentKey: string }) {
  const [offset, setOffset] = useState(0);
  const runs = useAgentRuns(agentKey, { limit: RUNS_PAGE, offset });
  if (runs.isError) return <ErrorState error={runs.error} onRetry={() => runs.refetch()} />;
  if (runs.isLoading) return <SkeletonRows rows={6} />;
  const page = runs.data;
  if (!page || page.items.length === 0) return <EmptyState icon={Bot} title="No runs yet" description="Run this agent from the Playground tab or through a workflow." />;
  return (
    <div className="space-y-3">
      {page.items.map((run) => (
        <Collapsible
          key={run.id}
          title={<AgentRunSummaryLine run={run} />}
          summary={
            <span className="text-xs text-fg-muted tabular">
              {fmtMs(run.latency_ms)} · {fmtInt(run.prompt_tokens + run.completion_tokens)} tok · {fmtCurrency(run.cost_usd)}
            </span>
          }
        >
          <AgentRunDetails run={run} />
        </Collapsible>
      ))}
      <Pagination total={page.total} limit={page.limit} offset={page.offset} onChange={setOffset} label="runs" />
    </div>
  );
}

function EvaluationTab({ agent, canAdmin }: { agent: AgentDetailOut; canAdmin: boolean }) {
  const queryClient = useQueryClient();
  const run = useMutation({
    mutationFn: () => api<EvaluationResultOut>("/evaluations/run", { method: "POST", body: { agent_key: agent.agent_key } }),
    onSuccess: (result) => {
      toast[result.passed ? "success" : "warning"](`Evaluation ${result.passed ? "passed" : "has failing cases"}`, { description: `${result.metrics.passed ?? 0}/${result.metrics.cases ?? 0} cases passed` });
      void queryClient.invalidateQueries({ queryKey: ["agent", agent.agent_key] });
      void queryClient.invalidateQueries({ queryKey: ["evaluations"] });
    },
    onError: (error) => toast.error("Evaluation failed to run", { description: errorMessage(error) }),
  });
  const ev = agent.evaluation;
  return (
    <Card>
      <CardToolbar
        title="Latest evaluation"
        description={ev ? `Ran ${fmtRelative(ev.created_at)} · model ${ev.model ?? "—"}` : "No evaluation has been recorded for this agent yet."}
        actions={
          <Button variant="primary" size="sm" onClick={() => run.mutate()} loading={run.isPending} disabled={!canAdmin} leftIcon={<FlaskConical className="h-4 w-4" aria-hidden />}>
            Run evaluation
          </Button>
        }
      />
      <CardContent>
        {ev ? (
          <div className="space-y-4">
            <StatusPill status={ev.passed ? "passed" : "failed"} label={ev.passed ? "All cases passed" : "Some cases failed"} />
            <KeyValueList
              columns={3}
              dense
              items={[
                { label: "Cases", value: `${ev.metrics.passed ?? 0} / ${ev.metrics.cases ?? 0}` },
                { label: "Accuracy", value: fmtPercent(ev.metrics.accuracy ?? null, 0) },
                { label: "Unsupported claim rate", value: fmtPercent(ev.metrics.unsupported_claim_rate ?? null, 0) },
                { label: "Human intervention rate", value: fmtPercent(ev.metrics.human_intervention_rate ?? null, 0) },
                { label: "Extraction precision", value: fmtPercent(ev.metrics.extraction_precision ?? null, 0) },
                { label: "Extraction recall", value: fmtPercent(ev.metrics.extraction_recall ?? null, 0) },
                { label: "Cost per case", value: fmtCurrency(ev.metrics.cost_per_case_usd ?? null) },
                { label: "p50 latency", value: fmtMs(ev.metrics.p50_latency_ms ?? null) },
                { label: "p95 latency", value: fmtMs(ev.metrics.p95_latency_ms ?? null) },
              ]}
            />
            <p className="text-xs text-fg-subtle">Recorded {fmtDateTime(ev.created_at)}</p>
          </div>
        ) : (
          <EmptyState compact icon={FlaskConical} title="No evaluation yet" description={canAdmin ? "Run the test dataset to measure accuracy and speed." : "An administrator can run the evaluation."} />
        )}
      </CardContent>
    </Card>
  );
}

function PlaygroundTab({ agent, canRun }: { agent: AgentDetailOut; canRun: boolean }) {
  const queryClient = useQueryClient();
  const defaults = useMemo(() => prettyJson(agent.example_input ?? schemaDefaults(agent.input_schema)), [agent.example_input, agent.input_schema]);
  const [input, setInput] = useState(defaults);
  const [valid, setValid] = useState(true);
  const [result, setResult] = useState<AgentRunDirectOut | null>(null);

  const run = useMutation({
    mutationFn: () => {
      const parsed = safeJsonParse(input || "{}");
      if (!parsed.ok) throw new Error(parsed.error);
      return api<AgentRunDirectOut>(`/agents/${agent.agent_key}/run`, { method: "POST", body: { input: parsed.value, mode: "workflow" }, headers: { "Idempotency-Key": idempotencyKey() } });
    },
    onSuccess: (data) => {
      setResult(data);
      toast[data.status === "failed" ? "error" : "success"](`Run ${data.status.replace(/_/g, " ")}`, { description: data.workflow_run_id ? `Workflow run ${data.workflow_run_id.slice(0, 8)}` : undefined });
      void queryClient.invalidateQueries({ queryKey: ["agent", agent.agent_key] });
      void queryClient.invalidateQueries({ queryKey: ["agent-runs", agent.agent_key] });
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
    },
    onError: (error) => toast.error("Run failed", { description: errorMessage(error) }),
  });

  return (
    <div className="grid gap-4 xl:grid-cols-5">
      <Card className="xl:col-span-2">
        <CardToolbar title="Input" />
        <CardContent className="space-y-3">
          <JsonEditor label="Payload" value={input} onChange={setInput} onValidChange={setValid} rows={16} />
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" onClick={() => run.mutate()} loading={run.isPending} disabled={!canRun || !valid || !agent.enabled} leftIcon={<Play className="h-4 w-4" aria-hidden />}>
              Run agent
            </Button>
            <Button variant="ghost" onClick={() => setInput(defaults)} leftIcon={<RotateCcw className="h-4 w-4" aria-hidden />}>
              Reset
            </Button>
            {!canRun ? <span className="text-xs text-fg-subtle">Requires agents:run</span> : !agent.enabled ? <span className="text-xs text-danger">Agent is disabled</span> : null}
          </div>
        </CardContent>
      </Card>
      <Card className="xl:col-span-3">
        <CardToolbar title="Result" description={result ? `Agent run ${result.agent_run_id ? result.agent_run_id.slice(0, 8) : "—"}` : undefined} />
        <CardContent>
          {run.isPending ? <SkeletonRows rows={6} /> : result ? <AgentRunResultView result={result} /> : <EmptyState compact icon={Play} title="No run yet" description="Edit the payload and press Run agent." />}
        </CardContent>
      </Card>
    </div>
  );
}
