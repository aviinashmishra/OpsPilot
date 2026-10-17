"use client";

import { AlertTriangle, Bot, CheckCircle2, ClipboardCheck, Clock, Coins, Loader2, PiggyBank, Server, ShieldAlert, Workflow, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { DailyRunsChart } from "@/components/charts/daily-runs-chart";
import { DepartmentBars } from "@/components/charts/department-bars";
import { GettingStarted } from "@/components/overview/getting-started";
import { Badge, StatusPill } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Card, CardContent, CardToolbar } from "@/components/ui/card";
import { Segmented } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonCards, SkeletonRows } from "@/components/ui/skeleton";
import { StatTile } from "@/components/ui/stat-tile";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Tip } from "@/components/ui/tooltip";
import { RunListItem } from "@/components/workflows/run-row";
import { PERIOD_OPTIONS } from "@/lib/constants";
import { useOverview } from "@/lib/queries";
import { useSession } from "@/lib/session";
import { fmtCurrency, fmtDateTime, fmtHours, fmtInt, fmtRelative } from "@/lib/utils";

const MODE_LABELS: Record<string, { label: string; tone: "neutral" | "success" | "danger" }> = {
  sandbox: { label: "Sandbox", tone: "neutral" },
  live_connected: { label: "Live · connected", tone: "success" },
  live_error: { label: "Live · error / untested", tone: "danger" },
};

export default function OverviewPage() {
  const [days, setDays] = useState<number>(14);
  const overview = useOverview(days);
  const user = useSession((s) => s.user);
  const data = overview.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Good ${greeting()}, ${user?.full_name.split(" ")[0] ?? "there"}`}
        actions={<Segmented aria-label="Period" value={days} onChange={setDays} options={PERIOD_OPTIONS.map((d) => ({ value: d, label: `${d}d` }))} />}
      />

      <GettingStarted />

      {overview.isError ? <ErrorState error={overview.error} onRetry={() => overview.refetch()} /> : null}

      {overview.isLoading ? (
        <SkeletonCards count={8} />
      ) : data ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile label="Active agents" value={`${fmtInt(data.active_agents)} / ${fmtInt(data.total_agents)}`} hint={data.active_agents < data.total_agents ? `${data.total_agents - data.active_agents} disabled` : undefined} icon={Bot} tone="accent" />
          <StatTile label="Workflows executed" value={fmtInt(data.workflows_executed)} hint={`last ${days} days`} icon={Workflow} tone="info" />
          <StatTile label="Succeeded" value={fmtInt(data.workflows_succeeded)} hint={data.workflows_executed ? `${((data.workflows_succeeded / data.workflows_executed) * 100).toFixed(0)}% of runs` : "No runs yet"} icon={CheckCircle2} tone="success" />
          <StatTile label="Failed" value={fmtInt(data.workflows_failed)} hint="incl. timed out" icon={XCircle} tone={data.workflows_failed > 0 ? "danger" : "neutral"} />
          <StatTile label="Running / waiting" value={fmtInt(data.workflows_running)} icon={Loader2} tone="info" />
          <StatTile label="Estimated time saved" value={fmtHours(data.estimated_minutes_saved)} hint="not verified" icon={Clock} tone="accent" />
          <StatTile label="AI cost" value={fmtCurrency(data.ai_cost_usd)} hint={`+ ${fmtCurrency(data.infra_cost_usd)} infra (est.)`} icon={Coins} tone="warning" />
          <StatTile label="Realized savings" value={fmtCurrency(data.realized_savings_usd)} hint="finance-verified" icon={PiggyBank} tone={data.realized_savings_usd > 0 ? "success" : "neutral"} />
        </div>
      ) : null}

      {data ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <Link href="/approvals" className="surface-card flex items-center gap-3 p-4 transition-colors hover:border-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-warning/12 text-warning">
              <ClipboardCheck className="h-4 w-4" aria-hidden />
            </span>
            <span>
              <span className="block text-xl font-semibold tabular">{fmtInt(data.pending_approvals)}</span>
              <span className="block text-xs text-fg-muted">Pending approvals</span>
            </span>
          </Link>
          <Link href="/incidents" className="surface-card flex items-center gap-3 p-4 transition-colors hover:border-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-danger/12 text-danger">
              <ShieldAlert className="h-4 w-4" aria-hidden />
            </span>
            <span>
              <span className="block text-xl font-semibold tabular">{fmtInt(data.open_incidents)}</span>
              <span className="block text-xs text-fg-muted">Open incidents</span>
            </span>
          </Link>
          <div className="surface-card flex items-center gap-3 p-4">
            <span className="flex h-9 w-9 items-center justify-center rounded-md bg-surface-2 text-fg-muted">
              <Server className="h-4 w-4" aria-hidden />
            </span>
            <span className="min-w-0">
              <span className="block text-xs text-fg-muted">Integration modes</span>
              <span className="mt-1 flex flex-wrap gap-1">
                {Object.entries(data.integration_modes).length === 0 ? <span className="text-xs text-fg-subtle">None configured</span> : null}
                {Object.entries(data.integration_modes).map(([mode, count]) => {
                  const meta = MODE_LABELS[mode] ?? { label: mode, tone: "neutral" as const };
                  return (
                    <Badge key={mode} size="sm" tone={meta.tone}>
                      {count} {meta.label}
                    </Badge>
                  );
                })}
              </span>
            </span>
          </div>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardToolbar title="Runs and cost per day" />
          <CardContent>{overview.isLoading ? <SkeletonRows rows={5} /> : data ? data.daily_series.length > 0 ? <DailyRunsChart series={data.daily_series} /> : <EmptyState compact title="No activity yet" /> : null}</CardContent>
        </Card>
        <Card className="lg:col-span-2">
          <CardToolbar title="Department activity" actions={<ButtonLink href="/agents" size="xs" variant="ghost">View agents</ButtonLink>} />
          <CardContent>{overview.isLoading ? <SkeletonRows rows={6} /> : data ? <DepartmentBars data={data.department_breakdown} /> : null}</CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardToolbar title="Recent runs" actions={<ButtonLink href="/workflows" size="xs" variant="ghost">All runs</ButtonLink>} />
          <CardContent className="px-3">
            {overview.isLoading ? <SkeletonRows rows={5} /> : data && data.recent_runs.length > 0 ? <ul className="divide-y divide-border/60">{data.recent_runs.map((run) => <RunListItem key={run.id} run={run} />)}</ul> : <EmptyState compact icon={Workflow} title="No workflow runs yet" description="Start a workflow or run an agent from its playground." />}
          </CardContent>
        </Card>
        <Card>
          <CardToolbar title="Recent incidents" actions={<ButtonLink href="/incidents" size="xs" variant="ghost">All incidents</ButtonLink>} />
          <CardContent className="px-3">
            {overview.isLoading ? (
              <SkeletonRows rows={5} />
            ) : data && data.recent_incidents.length > 0 ? (
              <ul className="divide-y divide-border/60">
                {data.recent_incidents.map((incident) => (
                  <li key={incident.id} className="flex items-start gap-3 px-2 py-2.5">
                    <StatusPill status={incident.severity} size="sm" className="mt-0.5 w-[84px] shrink-0 justify-center" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-fg">{incident.title}</span>
                      <span className="block truncate text-xs text-fg-subtle">
                        {incident.source} · {incident.kind}
                        {incident.run_id ? (
                          <>
                            {" · "}
                            <Link href={`/workflows/${incident.run_id}`} className="text-accent hover:underline">
                              run
                            </Link>
                          </>
                        ) : null}
                      </span>
                    </span>
                    <span className="flex shrink-0 flex-col items-end gap-1">
                      <StatusPill status={incident.status} size="sm" />
                      <Tip content={fmtDateTime(incident.created_at)}>
                        <time dateTime={incident.created_at} className="text-[11px] text-fg-subtle">
                          {fmtRelative(incident.created_at)}
                        </time>
                      </Tip>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState compact icon={AlertTriangle} title="No incidents" description="Nothing has gone wrong recently." />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "morning";
  if (hour < 18) return "afternoon";
  return "evening";
}
