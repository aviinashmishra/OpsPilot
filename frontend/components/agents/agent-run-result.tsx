"use client";

import { AlertTriangle, ArrowUpRight, FileSearch, HelpCircle, Zap } from "lucide-react";
import Link from "next/link";

import { Badge, RiskBadge, StatusPill } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { JsonViewer } from "@/components/ui/json-viewer";
import { ChipList, KeyValueList } from "@/components/ui/key-value";
import { Collapsible } from "@/components/ui/misc";
import type { AgentRunDirectOut, JsonObject } from "@/lib/types";
import { fmtCurrency, fmtInt, fmtMs, titleCase } from "@/lib/utils";

interface ActionOutcomeLike {
  action_type?: string;
  tool_key?: string;
  outcome?: string;
  approval_id?: string | null;
  tool_execution_id?: string | null;
  error?: JsonObject | null;
  mode?: string | null;
  external_ref?: string | null;
  reason?: string;
  response?: JsonObject | null;
  details?: JsonObject;
}

interface ProposedActionLike {
  action_type?: string;
  tool_key?: string;
  payload?: JsonObject;
  reason?: string;
  risk_level?: string;
  evidence_refs?: string[];
  requires_approval?: boolean | null;
  estimated_minutes_saved?: number;
}

const OUTCOME_STATUS: Record<string, string> = {
  executed: "executed",
  approval_pending: "needs_approval",
  denied: "rejected",
  failed: "failed",
  duplicate: "skipped",
  unknown: "pending",
};

export function ActionOutcomeList({ actions }: { actions: JsonObject[] }) {
  if (actions.length === 0) return <p className="text-sm text-fg-subtle">No actions were executed or queued.</p>;
  return (
    <ul className="space-y-2">
      {actions.map((raw, i) => {
        const action = raw as ActionOutcomeLike;
        return (
          <li key={i} className="rounded-md border border-border bg-surface-2/50 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill status={OUTCOME_STATUS[action.outcome ?? ""] ?? action.outcome} size="sm" label={titleCase(action.outcome ?? "unknown")} />
              <span className="text-sm font-medium text-fg">{action.action_type ?? action.tool_key}</span>
              <code className="font-mono text-[11px] text-fg-subtle">{action.tool_key}</code>
              {action.mode ? (
                <Badge size="sm" tone={action.mode === "live" ? "success" : "neutral"}>
                  {action.mode === "mock" ? "sandbox" : action.mode}
                </Badge>
              ) : null}
            </div>
            {action.reason ? <p className="mt-1 text-xs text-fg-muted">{action.reason}</p> : null}
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-muted">
              {action.approval_id ? (
                <Link href={`/approvals?id=${action.approval_id}`} className="inline-flex items-center gap-1 text-accent hover:underline">
                  Approval {action.approval_id.slice(0, 8)} <ArrowUpRight className="h-3 w-3" aria-hidden />
                </Link>
              ) : null}
              {action.external_ref ? <span>ref: {action.external_ref}</span> : null}
              {action.tool_execution_id ? <span>execution: {action.tool_execution_id.slice(0, 8)}</span> : null}
            </div>
            {action.error ? <p className="mt-1 text-xs text-danger">{String(action.error.message ?? action.error.code ?? "error")}</p> : null}
            {action.response && Object.keys(action.response).length > 0 ? (
              <Collapsible title={<span className="text-xs text-fg-muted">Response</span>} className="mt-2 bg-transparent">
                <JsonViewer value={action.response} collapsed maxHeight="14rem" />
              </Collapsible>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export function ProposedActionList({ actions }: { actions: JsonObject[] }) {
  if (actions.length === 0) return <p className="text-sm text-fg-subtle">The agent proposed no actions.</p>;
  return (
    <ul className="space-y-2">
      {actions.map((raw, i) => {
        const action = raw as ProposedActionLike;
        return (
          <li key={i} className="rounded-md border border-border bg-surface-2/50 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Zap className="h-3.5 w-3.5 text-accent" aria-hidden />
              <span className="text-sm font-medium text-fg">{action.action_type}</span>
              <code className="font-mono text-[11px] text-fg-subtle">{action.tool_key}</code>
              {action.risk_level ? <RiskBadge level={action.risk_level} size="sm" /> : null}
              {action.requires_approval ? (
                <Badge size="sm" tone="warning">
                  requires approval
                </Badge>
              ) : null}
            </div>
            {action.reason ? <p className="mt-1 text-xs text-fg-muted">{action.reason}</p> : null}
            {action.payload ? <JsonViewer value={action.payload} collapsed className="mt-2" maxHeight="14rem" title="Payload" /> : null}
          </li>
        );
      })}
    </ul>
  );
}

export function AgentRunResultView({ result }: { result: AgentRunDirectOut }) {
  const r = result.result;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={result.status} />
        <span className="text-xs text-fg-muted">
          latency {fmtMs(result.latency_ms)} · {fmtInt((result.usage.prompt_tokens ?? 0) + (result.usage.completion_tokens ?? 0))} tokens · {fmtCurrency(result.usage.cost_usd ?? 0)}
        </span>
        {result.usage.model ? <Badge size="sm">{String(result.usage.model)}</Badge> : null}
        {result.tool_modes.map((mode) => (
          <Badge key={mode} size="sm" tone={mode === "live" ? "success" : "neutral"}>
            tools: {mode === "mock" ? "sandbox" : mode}
          </Badge>
        ))}
        {result.workflow_run_id ? (
          <ButtonLink href={`/workflows/${result.workflow_run_id}`} size="xs" variant="outline" leftIcon={<ArrowUpRight className="h-3 w-3" aria-hidden />}>
            Open workflow run
          </ButtonLink>
        ) : null}
      </div>

      {r.summary ? <p className="rounded-md border border-accent/30 bg-accent/5 px-3 py-2 text-sm text-fg">{r.summary}</p> : null}

      {r.error ? (
        <div role="alert" className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {String(r.error.message ?? r.error.code ?? "The run failed")}
        </div>
      ) : null}

      {r.missing_information && r.missing_information.length > 0 ? (
        <div className="rounded-md border border-info/40 bg-info/10 px-3 py-2">
          <p className="mb-1 inline-flex items-center gap-1 text-xs font-medium text-info">
            <HelpCircle className="h-3.5 w-3.5" aria-hidden /> Missing information
          </p>
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-fg">
            {r.missing_information.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {r.warnings && r.warnings.length > 0 ? (
        <div className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2">
          <p className="mb-1 inline-flex items-center gap-1 text-xs font-medium text-warning">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden /> Warnings
          </p>
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-fg">
            {r.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Data</h4>
          <JsonViewer value={r.data ?? {}} />
        </div>
        <div className="space-y-4">
          <div>
            <h4 className="mb-2 inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-fg-muted">
              <FileSearch className="h-3.5 w-3.5" aria-hidden /> Evidence references
            </h4>
            <ChipList items={r.evidence_refs} empty="No evidence references" />
          </div>
          <KeyValueList
            dense
            items={[
              { label: "Confidence", value: typeof r.confidence === "number" ? `${(r.confidence * 100).toFixed(0)}%` : "—" },
              { label: "Agent run id", value: result.agent_run_id || "—", mono: true },
            ]}
          />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Proposed actions</h4>
          <ProposedActionList actions={r.proposed_actions ?? []} />
        </div>
        <div className="space-y-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Action outcomes</h4>
          <ActionOutcomeList actions={result.actions} />
        </div>
      </div>
    </div>
  );
}
