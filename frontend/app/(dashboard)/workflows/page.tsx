"use client";

import { FileCode2, Play, Search, Workflow } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { StatusPill } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { CopyableId } from "@/components/ui/copy-button";
import { Input, NativeSelect } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { Tip } from "@/components/ui/tooltip";
import { StartWorkflowDialog } from "@/components/workflows/start-workflow-dialog";
import { RUN_STATUSES } from "@/lib/constants";
import { useDebounced } from "@/lib/hooks";
import { usePermission } from "@/lib/permissions";
import { useWorkflowDefinitions, useWorkflows } from "@/lib/queries";
import { fmtCurrency, fmtDateTime, fmtMinutes, fmtRelative, titleCase } from "@/lib/utils";

const PAGE = 25;

export default function WorkflowsPage() {
  return (
    <Suspense fallback={<SkeletonRows rows={8} />}>
      <WorkflowsPageInner />
    </Suspense>
  );
}

function WorkflowsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState(searchParams.get("status") ?? "");
  const [workflowKey, setWorkflowKey] = useState(searchParams.get("workflow_key") ?? "");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [startOpen, setStartOpen] = useState(false);
  const q = useDebounced(search.trim(), 350);
  const canWrite = usePermission("workflows:write");
  const definitions = useWorkflowDefinitions();
  const runs = useWorkflows({ status: status || undefined, workflow_key: workflowKey || undefined, q: q || undefined, limit: PAGE, offset });

  const resetAnd = <T,>(setter: (v: T) => void) => (value: T) => {
    setter(value);
    setOffset(0);
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Workflow runs"
        actions={
          <>
            <ButtonLink href="/workflows/definitions" variant="outline" leftIcon={<FileCode2 className="h-4 w-4" aria-hidden />}>
              Definitions
            </ButtonLink>
            <Button variant="primary" onClick={() => setStartOpen(true)} disabled={!canWrite} leftIcon={<Play className="h-4 w-4" aria-hidden />}>
              Start workflow
            </Button>
          </>
        }
      />

      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
          <Input value={search} onChange={(e) => resetAnd(setSearch)(e.target.value)} placeholder="Run id, correlation id or workflow…" className="pl-8" aria-label="Search runs" />
        </div>
        <NativeSelect value={status} onChange={(e) => resetAnd(setStatus)(e.target.value)} aria-label="Filter by status" className="w-full sm:w-48">
          <option value="">All statuses</option>
          {RUN_STATUSES.map((s) => (
            <option key={s} value={s}>
              {titleCase(s)}
            </option>
          ))}
        </NativeSelect>
        <NativeSelect value={workflowKey} onChange={(e) => resetAnd(setWorkflowKey)(e.target.value)} aria-label="Filter by workflow" className="w-full sm:w-64">
          <option value="">All workflows</option>
          {(definitions.data ?? []).map((d) => (
            <option key={d.key} value={d.key}>
              {d.name}
            </option>
          ))}
        </NativeSelect>
      </div>

      {runs.isError ? <ErrorState error={runs.error} onRetry={() => runs.refetch()} /> : null}
      {runs.isLoading ? (
        <SkeletonRows rows={8} />
      ) : runs.data && runs.data.items.length === 0 ? (
        <EmptyState icon={Workflow} title="No runs match" description={q || status || workflowKey ? "Adjust the filters to see more runs." : "Start a workflow to see it here."} action={canWrite ? <Button variant="primary" onClick={() => setStartOpen(true)}>Start workflow</Button> : undefined} />
      ) : runs.data ? (
        <>
          <TableWrap>
            <Table className="min-w-[860px]">
              <THead>
                <TR>
                  <TH>Status</TH>
                  <TH>Workflow</TH>
                  <TH>Run</TH>
                  <TH>Node</TH>
                  <TH align="right">Steps</TH>
                  <TH align="right">Cost</TH>
                  <TH align="right">Time saved</TH>
                  <TH>Created</TH>
                </TR>
              </THead>
              <TBody>
                {runs.data.items.map((run) => (
                  <TR key={run.id} interactive onClick={() => router.push(`/workflows/${run.id}`)}>
                    <TD>
                      <StatusPill status={run.status} size="sm" />
                    </TD>
                    <TD>
                      <Link href={`/workflows/${run.id}`} className="font-medium text-fg hover:underline" onClick={(e) => e.stopPropagation()}>
                        {titleCase(run.workflow_key.replace(/^single_agent__/, "agent: "))}
                      </Link>
                      <span className="block text-xs text-fg-subtle">v{run.workflow_version}</span>
                    </TD>
                    <TD onClick={(e) => e.stopPropagation()}>
                      <CopyableId value={run.id} />
                    </TD>
                    <TD className="font-mono text-xs text-fg-muted">{run.current_node ?? "—"}</TD>
                    <TD align="right">{run.step_count}</TD>
                    <TD align="right">{fmtCurrency(run.cost_usd)}</TD>
                    <TD align="right">{fmtMinutes(run.estimated_minutes_saved)}</TD>
                    <TD>
                      <Tip content={fmtDateTime(run.created_at)}>
                        <time dateTime={run.created_at} className="text-fg-muted">
                          {fmtRelative(run.created_at)}
                        </time>
                      </Tip>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </TableWrap>
          <Pagination total={runs.data.total} limit={runs.data.limit} offset={runs.data.offset} onChange={setOffset} label="runs" />
        </>
      ) : null}
      <StartWorkflowDialog open={startOpen} onOpenChange={setStartOpen} />
    </div>
  );
}
