"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertOctagon, CheckCircle2, Clock, Cpu, Layers, Loader2, Pause, Play, RotateCcw, Server, Timer } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardToolbar } from "@/components/ui/card";
import { CodeBlock } from "@/components/ui/json-viewer";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonCards, SkeletonRows } from "@/components/ui/skeleton";
import { StatTile } from "@/components/ui/stat-tile";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { Tip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { useTick } from "@/lib/hooks";
import { usePermission } from "@/lib/permissions";
import { qk, useSystemQueue } from "@/lib/queries";
import type { JobOut, JobStatus, SystemQueueOut } from "@/lib/types";
import { cn, fmtDateTime, fmtInt, fmtMs, fmtRelative, titleCase } from "@/lib/utils";

const JOB_STATUSES: JobStatus[] = ["queued", "running", "done", "failed", "dead"];
const STATUS_BAR: Record<JobStatus, string> = { queued: "bg-fg-subtle", running: "bg-info", done: "bg-success", failed: "bg-warning", dead: "bg-danger" };

function fmtLag(seconds: number): string {
  if (!seconds) return "0 s";
  return fmtMs(seconds * 1000);
}

function KindBreakdown({ data }: { data: SystemQueueOut }) {
  const rows = useMemo(() => {
    const map = new Map<string, Record<JobStatus, number>>();
    for (const r of data.by_kind) {
      const row = map.get(r.kind) ?? { queued: 0, running: 0, done: 0, failed: 0, dead: 0 };
      if ((JOB_STATUSES as string[]).includes(r.status)) row[r.status as JobStatus] += r.count;
      map.set(r.kind, row);
    }
    return Array.from(map.entries())
      .map(([kind, counts]) => ({ kind, counts, total: JOB_STATUSES.reduce((n, s) => n + counts[s], 0) }))
      .sort((a, b) => b.total - a.total);
  }, [data.by_kind]);

  if (rows.length === 0) return <EmptyState compact icon={Layers} title="No jobs yet" description="Jobs appear here as they are queued." />;
  const max = Math.max(...rows.map((r) => r.total), 1);
  return (
    <div className="space-y-3">
      <ul className="space-y-3">
        {rows.map((row) => (
          <li key={row.kind}>
            <div className="mb-1 flex items-baseline justify-between gap-2 text-xs">
              <code className="font-mono text-fg">{row.kind}</code>
              <span className="text-fg-muted tabular">{fmtInt(row.total)}</span>
            </div>
            <div className="flex h-2 overflow-hidden rounded-full bg-surface-3" style={{ width: `${Math.max(8, (row.total / max) * 100)}%` }} role="img" aria-label={`${row.kind}: ${JOB_STATUSES.map((s) => `${row.counts[s]} ${s}`).join(", ")}`}>
              {JOB_STATUSES.map((s) => (row.counts[s] > 0 ? <span key={s} className={cn("h-full", STATUS_BAR[s])} style={{ width: `${(row.counts[s] / row.total) * 100}%` }} /> : null))}
            </div>
            <p className="mt-1 text-[11px] text-fg-subtle tabular">
              {JOB_STATUSES.filter((s) => row.counts[s] > 0)
                .map((s) => `${fmtInt(row.counts[s])} ${s}`)
                .join(" · ")}
            </p>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-3 border-t border-border pt-3 text-[11px] text-fg-muted">
        {JOB_STATUSES.map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5">
            <span className={cn("h-2 w-2 rounded-full", STATUS_BAR[s])} aria-hidden /> {s}
          </span>
        ))}
      </div>
    </div>
  );
}

function RecentJobs({ jobs, canRetry }: { jobs: JobOut[]; canRetry: boolean }) {
  const queryClient = useQueryClient();
  const retry = useMutation({
    mutationFn: (job: JobOut) => api<{ id: string; status: string }>(`/system/jobs/${encodeURIComponent(job.id)}/retry`, { method: "POST" }),
    onSuccess: (_, job) => {
      toast.success("Job re-queued", { description: `${job.kind} · ${job.id.slice(0, 8)}` });
      void queryClient.invalidateQueries({ queryKey: qk.systemQueue });
    },
    onError: (error) => toast.error("Could not retry the job", { description: errorMessage(error) }),
  });
  if (jobs.length === 0) return <EmptyState compact icon={Activity} title="No recent jobs" />;
  return (
    <TableWrap>
      <Table className="min-w-[820px]">
        <THead>
          <TR>
            <TH>Job</TH>
            <TH>Status</TH>
            <TH align="right">Attempts</TH>
            <TH>Worker</TH>
            <TH>Created</TH>
            <TH>Finished</TH>
            <TH align="right">
              <span className="sr-only">Actions</span>
            </TH>
          </TR>
        </THead>
        <TBody>
          {jobs.map((job) => (
            <TR key={job.id}>
              <TD>
                <code className="font-mono text-xs text-fg">{job.kind}</code>
                <span className="block font-mono text-[11px] text-fg-subtle">{job.id.slice(0, 8)}</span>
                {job.last_error ? (
                  <Tip content={<pre className="max-h-60 max-w-sm overflow-auto whitespace-pre-wrap font-mono text-[11px]">{job.last_error}</pre>}>
                    <p className="mt-0.5 max-w-[340px] cursor-help truncate text-[11px] text-danger">{job.last_error}</p>
                  </Tip>
                ) : null}
              </TD>
              <TD>
                <StatusPill status={job.status} size="sm" />
              </TD>
              <TD align="right" className="text-xs">
                {job.attempts}/{job.max_attempts}
              </TD>
              <TD className="max-w-[200px] truncate font-mono text-[11px] text-fg-muted" title={job.locked_by ?? undefined}>
                {job.locked_by ?? "—"}
              </TD>
              <TD className="text-xs text-fg-muted" title={fmtDateTime(job.created_at)}>
                {fmtRelative(job.created_at)}
              </TD>
              <TD className="text-xs text-fg-muted" title={fmtDateTime(job.finished_at)}>
                {job.finished_at ? fmtRelative(job.finished_at) : "—"}
              </TD>
              <TD align="right">
                {job.status === "dead" ? (
                  <Tip content={canRetry ? "Re-queue with a fresh attempt budget" : "Requires tenant:admin"}>
                    <span>
                      <Button size="xs" variant="outline" disabled={!canRetry} loading={retry.isPending && retry.variables?.id === job.id} onClick={() => retry.mutate(job)} leftIcon={<RotateCcw className="h-3 w-3" aria-hidden />}>
                        Retry
                      </Button>
                    </span>
                  </Tip>
                ) : null}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </TableWrap>
  );
}

export default function SystemPage() {
  const [paused, setPaused] = useState(false);
  const queue = useSystemQueue(paused);
  const canRetry = usePermission("tenant:admin");
  useTick(5000);
  const d = queue.data;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Scale & workers"
        badge={d ? <Badge tone={d.alive_workers > 0 ? "success" : "danger"}>{d.alive_workers > 0 ? `${d.alive_workers} worker${d.alive_workers === 1 ? "" : "s"} alive` : "no live workers"}</Badge> : undefined}
        actions={
          <>
            <span className="inline-flex items-center gap-1.5 text-xs text-fg-subtle" aria-live="polite">
              {paused ? (
                "Auto-refresh paused"
              ) : (
                <>
                  {queue.isFetching ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden />} Live · every 3 s
                </>
              )}
            </span>
            <Button size="sm" variant="outline" onClick={() => setPaused((p) => !p)} aria-pressed={paused} leftIcon={paused ? <Play className="h-3.5 w-3.5" aria-hidden /> : <Pause className="h-3.5 w-3.5" aria-hidden />}>
              {paused ? "Resume" : "Pause"}
            </Button>
          </>
        }
      />

      {queue.isError && !d ? <ErrorState error={queue.error} onRetry={() => queue.refetch()} /> : null}
      {queue.isError && d ? <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">Refresh failed: {errorMessage(queue.error)} — showing the last known state.</p> : null}

      {!d && queue.isLoading ? (
        <SkeletonCards count={8} className="lg:grid-cols-4" />
      ) : d ? (
        <>
          <section aria-label="Queue metrics" className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="Queued" value={fmtInt(d.by_status.queued)} icon={Layers} tone={d.by_status.queued > 0 ? "info" : "neutral"} hint="ready or scheduled" />
            <StatTile label="Running" value={fmtInt(d.by_status.running)} icon={Loader2} tone={d.by_status.running > 0 ? "accent" : "neutral"} hint={`of ${fmtInt(d.total_concurrency)} slots`} />
            <StatTile label="Done · last hour" value={fmtInt(d.throughput_last_hour)} icon={CheckCircle2} tone="success" hint={`${fmtInt(d.by_status.done)} done in total`} />
            <StatTile label="Dead" value={fmtInt(d.by_status.dead)} icon={AlertOctagon} tone={d.by_status.dead > 0 ? "danger" : "neutral"} hint={d.by_status.failed > 0 ? `${fmtInt(d.by_status.failed)} failed, retrying` : "attempts exhausted"} />
            <StatTile label="Oldest ready lag" value={fmtLag(d.oldest_ready_lag_seconds)} icon={Timer} tone={d.oldest_ready_lag_seconds > 30 ? "warning" : "neutral"} />
            <StatTile label="Alive workers" value={fmtInt(d.alive_workers)} icon={Server} tone={d.alive_workers > 0 ? "success" : "danger"} hint={`${d.workers.length} registered`} />
            <StatTile label="Total concurrency" value={fmtInt(d.total_concurrency)} icon={Cpu} hint="parallel job slots" />
            <StatTile label="Worker mode" value={<span className="text-lg">{titleCase(d.worker_mode)}</span>} icon={Activity} hint={d.worker_mode === "db" ? "standalone workers" : "inside the API"} />
          </section>

          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardToolbar title="Workers" />
              <CardContent>
                {d.workers.length === 0 ? (
                  <EmptyState compact icon={Server} title="No workers registered" description="Start one with start.cmd -Workers 1 or python -m app.workers.runner." />
                ) : (
                  <TableWrap>
                    <Table className="min-w-[720px]">
                      <THead>
                        <TR>
                          <TH>Worker</TH>
                          <TH>Status</TH>
                          <TH align="right">Active</TH>
                          <TH align="right">Processed</TH>
                          <TH align="right">Failed</TH>
                          <TH>Last seen</TH>
                        </TR>
                      </THead>
                      <TBody>
                        {d.workers.map((w) => (
                          <TR key={w.name}>
                            <TD>
                              <span className="block max-w-[260px] truncate font-medium text-fg" title={w.name}>
                                {w.name}
                              </span>
                              <span className="block font-mono text-[11px] text-fg-subtle">
                                {w.hostname} · pid {w.pid} · {w.concurrency} slots
                              </span>
                            </TD>
                            <TD>
                              <StatusPill status={w.status} size="sm" />
                            </TD>
                            <TD align="right">
                              <span className={cn(w.active_jobs > 0 && "text-info")}>
                                {w.active_jobs}/{w.concurrency}
                              </span>
                            </TD>
                            <TD align="right">{fmtInt(w.processed)}</TD>
                            <TD align="right" className={cn(w.failed > 0 && "text-danger")}>
                              {fmtInt(w.failed)}
                            </TD>
                            <TD className="text-xs text-fg-muted" title={fmtDateTime(w.last_seen_at)}>
                              <span className="inline-flex items-center gap-1">
                                <Clock className="h-3 w-3 text-fg-subtle" aria-hidden /> {fmtRelative(w.last_seen_at)}
                              </span>
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
              <CardToolbar title="Jobs by kind" />
              <CardContent>
                <KindBreakdown data={d} />
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardToolbar title="Recent jobs" description={canRetry ? undefined : "Retrying dead jobs requires tenant:admin."} />
              <CardContent>{queue.isLoading ? <SkeletonRows rows={5} /> : <RecentJobs jobs={d.recent_jobs} canRetry={canRetry} />}</CardContent>
            </Card>
            <Card>
              <CardToolbar title="How to scale" />
              <CardContent className="space-y-3 text-xs text-fg-muted">
                <div className="space-y-1.5">
                  <p className="font-medium text-fg">More workers on this machine</p>
                  <CodeBlock code="start.cmd -Workers 4" />
                </div>
                <div className="space-y-1.5">
                  <p className="font-medium text-fg">Workers on more machines</p>
                  <CodeBlock code={"cd backend\npython -m app.workers.runner --concurrency 8"} />
                  <p>Point every worker at the same DATABASE_URL.</p>
                </div>
                <div className="space-y-1.5">
                  <p className="font-medium text-fg">Run the API without in-process workers</p>
                  <CodeBlock code="WORKER_MODE=db" />
                  <p>The API only enqueues; standalone workers do all the work. Current mode: <span className="font-mono text-fg">{d.worker_mode}</span>.</p>
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
}
