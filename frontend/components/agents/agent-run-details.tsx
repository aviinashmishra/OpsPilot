"use client";

import { ActionOutcomeList, ProposedActionList } from "@/components/agents/agent-run-result";
import { Badge, StatusPill } from "@/components/ui/badge";
import { JsonViewer } from "@/components/ui/json-viewer";
import { ChipList, KeyValueList } from "@/components/ui/key-value";
import { Collapsible } from "@/components/ui/misc";
import type { AgentRunOut, JsonObject } from "@/lib/types";
import { fmtCurrency, fmtDateTime, fmtInt, fmtMs, fmtRelative, titleCase } from "@/lib/utils";

export function splitAgentOutput(output: JsonObject): { data: JsonObject; summary: string | null; actions: JsonObject[]; toolModes: string[]; confidence: number | null } {
  const data: JsonObject = {};
  for (const [key, value] of Object.entries(output)) {
    if (!key.startsWith("_")) data[key] = value;
  }
  const actions = Array.isArray(output._actions) ? (output._actions as JsonObject[]) : [];
  const toolModes = Array.isArray(output._tool_modes) ? (output._tool_modes as string[]) : [];
  return { data, summary: typeof output._summary === "string" ? output._summary : null, actions, toolModes, confidence: typeof output._confidence === "number" ? output._confidence : null };
}

export function AgentRunSummaryLine({ run }: { run: AgentRunOut }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <StatusPill status={run.status} size="sm" />
      <span className="truncate text-sm font-medium text-fg">{titleCase(run.agent_key)}</span>
      {run.node_key ? <code className="font-mono text-[11px] text-fg-subtle">node: {run.node_key}</code> : null}
      <span className="text-xs text-fg-subtle" title={fmtDateTime(run.started_at)}>
        {fmtRelative(run.started_at)}
      </span>
    </div>
  );
}

export function AgentRunDetails({ run }: { run: AgentRunOut }) {
  const { data, summary, actions, toolModes, confidence } = splitAgentOutput(run.output);
  return (
    <div className="space-y-4">
      <KeyValueList
        dense
        columns={3}
        items={[
          { label: "Run id", value: run.id, mono: true },
          { label: "Version", value: `v${run.agent_version}` },
          { label: "Model", value: run.model ?? "—" },
          { label: "Latency", value: fmtMs(run.latency_ms) },
          { label: "Tokens", value: `${fmtInt(run.prompt_tokens)} in · ${fmtInt(run.completion_tokens)} out` },
          { label: "Cost", value: fmtCurrency(run.cost_usd) },
          { label: "Started", value: fmtDateTime(run.started_at) },
          { label: "Finished", value: fmtDateTime(run.finished_at) },
          { label: "Confidence", value: confidence !== null ? `${(confidence * 100).toFixed(0)}%` : "—" },
        ]}
      />
      {toolModes.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {toolModes.map((mode) => (
            <Badge key={mode} size="sm" tone={mode === "live" ? "success" : "neutral"}>
              tools: {mode === "mock" ? "sandbox" : mode}
            </Badge>
          ))}
        </div>
      ) : null}
      {summary ? <p className="rounded-md border border-accent/30 bg-accent/5 px-3 py-2 text-sm text-fg">{summary}</p> : null}
      {run.error ? (
        <div role="alert" className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          <span className="font-medium">{String(run.error.code ?? "error")}</span>: {String(run.error.message ?? "")}
        </div>
      ) : null}
      {run.missing_information.length > 0 ? (
        <div className="rounded-md border border-info/40 bg-info/10 px-3 py-2 text-sm">
          <p className="mb-1 text-xs font-medium text-info">Missing information</p>
          <ul className="list-disc pl-5">
            {run.missing_information.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {run.warnings.length > 0 ? (
        <div className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm">
          <p className="mb-1 text-xs font-medium text-warning">Warnings</p>
          <ul className="list-disc pl-5">
            {run.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-2">
        <JsonViewer value={run.input} title="Input" collapsed maxHeight="18rem" />
        <JsonViewer value={data} title="Output data" collapsed maxHeight="18rem" />
      </div>
      <div>
        <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">Evidence</p>
        <ChipList items={run.evidence_refs} empty="No evidence references" />
      </div>
      <Collapsible title={<span className="text-sm font-medium">Proposed actions ({run.proposed_actions.length})</span>} className="bg-transparent">
        <ProposedActionList actions={run.proposed_actions} />
      </Collapsible>
      <Collapsible title={<span className="text-sm font-medium">Action outcomes ({actions.length})</span>} className="bg-transparent" defaultOpen={actions.length > 0}>
        <ActionOutcomeList actions={actions} />
      </Collapsible>
    </div>
  );
}
