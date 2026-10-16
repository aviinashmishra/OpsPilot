"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Ban, ClipboardCheck, RefreshCw, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { AgentRunDetails, AgentRunSummaryLine } from "@/components/agents/agent-run-details";
import { Badge, StatusPill } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { Card, CardContent, CardToolbar } from "@/components/ui/card";
import { CopyButton } from "@/components/ui/copy-button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { JsonViewer } from "@/components/ui/json-viewer";
import { KeyValueList } from "@/components/ui/key-value";
import { Collapsible } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton, SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Timeline, type TimelineItem } from "@/components/ui/timeline";
import { GraphLegend, WorkflowGraphView } from "@/components/workflows/workflow-graph";
import { api, errorMessage } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import { useWorkflow } from "@/lib/queries";
import type { WorkflowRunOut } from "@/lib/types";
import { fmtCurrency, fmtDateTime, fmtMinutes, fmtMs, fmtRelative, titleCase } from "@/lib/utils";

const CANCELLABLE = new Set(["pending", "running", "waiting_approval", "waiting_input"]);
const RETRYABLE = new Set(["failed", "timed_out"]);

export default function WorkflowRunPage({ params }: { params: { id: string } }) {
  const run = useWorkflow(params.id);
  const canWrite = usePermission("workflows:write");
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState<"cancel" | "retry" | null>(null);

  const act = useMutation({
    mutationFn: (action: "cancel" | "retry") => api<WorkflowRunOut>(`/workflows/${params.id}/${action}`, { method: "POST" }),
    onSuccess: (updated, action) => {
      toast.success(action === "cancel" ? "Cancellation requested" : "Run re-queued", { description: `Status: ${titleCase(updated.status)}` });
      queryClient.setQueryData(["workflow", params.id], updated);
      void queryClient.invalidateQueries({ queryKey: ["workflow", params.id] });
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      setConfirm(null);
    },
    onError: (error) => toast.error("Action failed", { description: errorMessage(error) }),
  });

  if (run.isError) return <ErrorState error={run.error} onRetry={() => run.refetch()} />;
  if (run.isLoading || !run.data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-16 w-1/2" />
        <Skeleton className="h-[420px] w-full" />
        <SkeletonRows rows={5} />
      </div>
    );
  }
  const r = run.data;
  const nodeStates = r.state.nodes ?? {};
  const checkpoints: TimelineItem[] = [...r.checkpoints]
    .sort((a, b) => b.sequence - a.sequence)
    .map((c) => ({
      id: `${c.sequence}-${c.node_key}`,
      title: (
        <span>
          <span className="font-mono text-xs text-fg-subtle">#{c.sequence}</span> {c.node_key} <span className="text-xs text-fg-subtle">({c.node_type})</span>
        </span>
      ),
      status: c.status,
      time: c.created_at,
      meta: (
        <span className="inline-flex flex-wrap items-center gap-2">
          <StatusPill status={c.status} size="sm" />
          {c.duration_ms !== null ? <span className="tabular">{fmtMs(c.duration_ms)}</span> : null}
          {typeof c.detail.next === "string" ? <span>→ {c.detail.next}</span> : null}
          {c.detail.wait ? <span className="text-warning">waiting</span> : null}
        </span>
      ),
      detail: Object.keys(c.detail).length > 0 && (c.detail.error || c.detail.result !== undefined) ? <JsonViewer value={c.detail} collapsed maxHeight="12rem" title="Detail" /> : undefined,
    }));

  return (
    <div className="space-y-5">
      <PageHeader
        crumbs={[{ label: "Workflows", href: "/workflows" }, { label: r.id.slice(0, 8) }]}
        title={titleCase(r.workflow_key.replace(/^single_agent__/, "agent: "))}
        badge={
          <>
            <StatusPill status={r.status} />
            {r.cancel_requested ? (
              <Badge tone="warning" size="sm">
                cancel requested
              </Badge>
            ) : null}
            <Badge size="sm">v{r.workflow_version}</Badge>
            {r.attempt > 0 ? <Badge size="sm">attempt {r.attempt}</Badge> : null}
          </>
        }
        description={
          <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="inline-flex items-center gap-1">
              run <code className="font-mono text-xs">{r.id}</code>
              <CopyButton value={r.id} label="Copy run id" />
            </span>
            <span className="inline-flex items-center gap-1">
              correlation <code className="font-mono text-xs">{r.correlation_id}</code>
              <CopyButton value={r.correlation_id} label="Copy correlation id" />
            </span>
          </span>
        }
        actions={
          <>
            <Button variant="ghost" size="sm" onClick={() => run.refetch()} leftIcon={<RefreshCw className="h-4 w-4" aria-hidden />}>
              Refresh
            </Button>
            {RETRYABLE.has(r.status) ? (
              <Button variant="primary" size="sm" onClick={() => setConfirm("retry")} disabled={!canWrite} leftIcon={<RotateCcw className="h-4 w-4" aria-hidden />}>
                Retry
              </Button>
            ) : null}
            {CANCELLABLE.has(r.status) ? (
              <Button variant="danger" size="sm" onClick={() => setConfirm("cancel")} disabled={!canWrite || r.cancel_requested} leftIcon={<Ban className="h-4 w-4" aria-hidden />}>
                Cancel run
              </Button>
            ) : null}
          </>
        }
      />

      {r.error ? (
        <div role="alert" className="rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
          <span className="font-semibold">{String(r.error.code ?? "error")}</span>: {String(r.error.message ?? "")}
        </div>
      ) : null}

      {r.pending_approvals.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-warning/40 bg-warning/10 px-4 py-3 text-sm">
          <ClipboardCheck className="h-4 w-4 text-warning" aria-hidden />
          <span className="text-fg">
            {r.pending_approvals.length} pending approval{r.pending_approvals.length > 1 ? "s" : ""} block this run.
          </span>
          {r.pending_approvals.map((id) => (
            <ButtonLink key={id} href={`/approvals?id=${id}`} size="xs" variant="outline">
              Review {id.slice(0, 8)}
            </ButtonLink>
          ))}
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KeyValueList
          className="surface-card p-4 sm:col-span-2 lg:col-span-4"
          columns={3}
          dense
          items={[
            { label: "Created", value: <span title={fmtDateTime(r.created_at)}>{fmtRelative(r.created_at)}</span> },
            { label: "Started", value: r.started_at ? <span title={fmtDateTime(r.started_at)}>{fmtRelative(r.started_at)}</span> : "—" },
            { label: "Finished", value: r.finished_at ? <span title={fmtDateTime(r.finished_at)}>{fmtRelative(r.finished_at)}</span> : "—" },
            { label: "Deadline", value: r.deadline_at ? fmtDateTime(r.deadline_at) : "—" },
            { label: "Current node", value: r.current_node ?? "—", mono: true },
            { label: "Steps", value: String(r.step_count) },
            { label: "AI cost", value: fmtCurrency(r.cost_usd) },
            { label: "Estimated time saved", value: fmtMinutes(r.estimated_minutes_saved) },
            { label: "Actor", value: r.actor_id ?? "—", mono: true },
            ...(r.parent_run_id ? [{ label: "Parent run", value: <Link href={`/workflows/${r.parent_run_id}`} className="text-accent hover:underline">{r.parent_run_id.slice(0, 8)}</Link> }] : []),
          ]}
        />
      </div>

      <Card>
        <CardToolbar title="Execution graph" />
        <CardContent className="space-y-3">
          {r.graph ? <WorkflowGraphView graph={r.graph} nodeStates={nodeStates} currentNode={r.current_node} runStatus={r.status} /> : <EmptyState compact title="Graph unavailable" description="The workflow definition for this run could not be loaded." />}
          <GraphLegend />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <CardToolbar title="Checkpoints" />
          <CardContent>{checkpoints.length === 0 ? <EmptyState compact title="No checkpoints yet" /> : <Timeline items={checkpoints} />}</CardContent>
        </Card>
        <Card className="lg:col-span-3">
          <CardToolbar title={`Agent runs (${r.agent_runs.length})`} />
          <CardContent className="space-y-2">
            {r.agent_runs.length === 0 ? (
              <EmptyState compact title="No agent runs yet" />
            ) : (
              r.agent_runs.map((ar) => (
                <Collapsible key={ar.id} title={<AgentRunSummaryLine run={ar} />} summary={<span className="text-xs text-fg-muted tabular">{fmtMs(ar.latency_ms)} · {fmtCurrency(ar.cost_usd)}</span>}>
                  <AgentRunDetails run={ar} />
                </Collapsible>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <JsonViewer value={r.input} title="Input" collapsed />
        <JsonViewer value={r.output} title="Output" />
      </div>
      <Collapsible title={<span className="text-sm font-medium">Raw state</span>}>
        <JsonViewer value={r.state} collapsed />
      </Collapsible>

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={confirm === "cancel" ? "Cancel this run?" : "Retry this run?"}
        description={confirm === "cancel" ? "The orchestrator stops at the next checkpoint. Actions already executed are not rolled back." : "The run resumes from its last checkpoint with a fresh deadline."}
        confirmLabel={confirm === "cancel" ? "Cancel run" : "Retry run"}
        tone={confirm === "cancel" ? "danger" : "primary"}
        loading={act.isPending}
        onConfirm={() => confirm && act.mutate(confirm)}
      />
    </div>
  );
}
