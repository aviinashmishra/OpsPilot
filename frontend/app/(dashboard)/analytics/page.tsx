"use client";

import { Info } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { UsageQuotas } from "@/components/analytics/usage-quotas";
import { Card, CardContent, CardToolbar } from "@/components/ui/card";
import { KeyValueList } from "@/components/ui/key-value";
import { Segmented } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonCards, SkeletonRows } from "@/components/ui/skeleton";
import { StatTile } from "@/components/ui/stat-tile";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { SortableTH, TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { DEPARTMENT_LABELS, PERIOD_OPTIONS } from "@/lib/constants";
import { useReports } from "@/lib/queries";
import type { ReportAgentRow, ReportWorkflowRow } from "@/lib/types";
import { fmtCurrency, fmtInt, fmtMinutes, fmtMs, fmtPercent, titleCase } from "@/lib/utils";

type SortDir = "asc" | "desc";

function useSort<T>(rows: T[], initialKey: keyof T, initialDir: SortDir = "desc") {
  const [key, setKey] = useState<keyof T>(initialKey);
  const [dir, setDir] = useState<SortDir>(initialDir);
  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a[key];
      const bv = b[key];
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      if (typeof av === "number" && typeof bv === "number") return dir === "asc" ? av - bv : bv - av;
      return dir === "asc" ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    });
    return copy;
  }, [rows, key, dir]);
  const toggle = (next: keyof T) => {
    if (next === key) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setKey(next);
      setDir("desc");
    }
  };
  return { sorted, key, dir, toggle };
}

function AgentTable({ rows }: { rows: ReportAgentRow[] }) {
  const sort = useSort<ReportAgentRow>(rows, "runs");
  if (rows.length === 0) return <EmptyState compact title="No agent runs in this period" />;
  const col = (label: string, k: keyof ReportAgentRow, align: "left" | "right" = "right") => <SortableTH label={label} active={sort.key === k} direction={sort.dir} onClick={() => sort.toggle(k)} align={align} />;
  return (
    <TableWrap>
      <Table className="min-w-[980px]">
        <THead>
          <TR>
            {col("Agent", "name", "left")}
            <TH>Department</TH>
            {col("Runs", "runs")}
            {col("Success", "success_rate")}
            {col("Intervention", "human_intervention_rate")}
            {col("p50", "p50_latency_ms")}
            {col("p95", "p95_latency_ms")}
            {col("Cost / success", "cost_per_success_usd")}
            {col("Cost", "cost_usd")}
            {col("Tokens", "tokens")}
            {col("Warnings", "warnings")}
          </TR>
        </THead>
        <TBody>
          {sort.sorted.map((row) => (
            <TR key={row.agent_key}>
              <TD>
                <Link href={`/agents/${row.agent_key}`} className="font-medium text-fg hover:underline">
                  {row.name}
                </Link>
                <span className="block text-xs text-fg-subtle">
                  {row.succeeded} ok · {row.failed} failed · {row.needs_approval} approvals · {row.needs_input} needs input
                </span>
              </TD>
              <TD className="text-fg-muted">{DEPARTMENT_LABELS[row.department] ?? row.department}</TD>
              <TD align="right">{fmtInt(row.runs)}</TD>
              <TD align="right">{fmtPercent(row.success_rate, 0)}</TD>
              <TD align="right">{fmtPercent(row.human_intervention_rate, 0)}</TD>
              <TD align="right">{fmtMs(row.p50_latency_ms)}</TD>
              <TD align="right">{fmtMs(row.p95_latency_ms)}</TD>
              <TD align="right">{fmtCurrency(row.cost_per_success_usd)}</TD>
              <TD align="right">{fmtCurrency(row.cost_usd)}</TD>
              <TD align="right">{fmtInt(row.tokens)}</TD>
              <TD align="right">{fmtInt(row.warnings)}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </TableWrap>
  );
}

function WorkflowTable({ rows }: { rows: ReportWorkflowRow[] }) {
  const sort = useSort<ReportWorkflowRow>(rows, "runs");
  if (rows.length === 0) return <EmptyState compact title="No workflow runs in this period" />;
  const col = (label: string, k: keyof ReportWorkflowRow, align: "left" | "right" = "right") => <SortableTH label={label} active={sort.key === k} direction={sort.dir} onClick={() => sort.toggle(k)} align={align} />;
  return (
    <TableWrap>
      <Table className="min-w-[720px]">
        <THead>
          <TR>
            {col("Workflow", "workflow_key", "left")}
            {col("Runs", "runs")}
            {col("Completed", "completed")}
            {col("Failed", "failed")}
            {col("Waiting", "waiting")}
            {col("Cost", "cost_usd")}
            {col("Time saved", "minutes_saved")}
          </TR>
        </THead>
        <TBody>
          {sort.sorted.map((row) => (
            <TR key={row.workflow_key}>
              <TD>
                <Link href={`/workflows?workflow_key=${row.workflow_key}`} className="font-medium text-fg hover:underline">
                  {titleCase(row.workflow_key.replace(/^single_agent__/, "agent: "))}
                </Link>
              </TD>
              <TD align="right">{fmtInt(row.runs)}</TD>
              <TD align="right">{fmtInt(row.completed)}</TD>
              <TD align="right">{fmtInt(row.failed)}</TD>
              <TD align="right">{fmtInt(row.waiting)}</TD>
              <TD align="right">{fmtCurrency(row.cost_usd)}</TD>
              <TD align="right">{fmtMinutes(row.minutes_saved)}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </TableWrap>
  );
}

export default function AnalyticsPage() {
  const [days, setDays] = useState<number>(30);
  const report = useReports(days);
  const data = report.data;
  return (
    <div className="space-y-6">
      <PageHeader title="Analytics" actions={<Segmented aria-label="Period" value={days} onChange={setDays} options={PERIOD_OPTIONS.map((d) => ({ value: d, label: `${d}d` }))} />} />
      {report.isError ? <ErrorState error={report.error} onRetry={() => report.refetch()} /> : null}
      {report.isLoading ? (
        <SkeletonCards count={8} />
      ) : data ? (
        <>
          <section aria-label="Key performance indicators" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Workflow runs" value={fmtInt(data.kpis.workflow_runs)} hint={`last ${days} days`} />
            <StatTile label="Completion rate" value={fmtPercent(data.kpis.workflow_completion_rate, 1)} hint="of terminal runs" tone="success" />
            <StatTile label="Failure rate" value={fmtPercent(data.kpis.workflow_failure_rate, 1)} hint="failed or timed out" tone={data.kpis.workflow_failure_rate && data.kpis.workflow_failure_rate > 0.1 ? "danger" : "neutral"} />
            <StatTile label="Cost per successful workflow" value={fmtCurrency(data.kpis.cost_per_successful_workflow_usd)} hint="AI spend ÷ completed runs" />
            <StatTile label="Median latency" value={fmtMs(data.kpis.median_latency_ms)} hint={`p95 ${fmtMs(data.kpis.p95_latency_ms)}`} />
            <StatTile label="Tokens consumed" value={fmtInt(data.kpis.token_consumption)} hint="prompt + completion" />
            <StatTile label="Tool failure rate" value={fmtPercent(data.kpis.tool_failure_rate, 2)} hint={`${fmtInt(data.kpis.tool_executions)} executions · ${fmtInt(data.kpis.side_effect_actions)} side effects`} />
            <StatTile label="Duplicate actions suppressed" value={fmtInt(data.kpis.duplicate_actions_suppressed)} hint={`duplicate external action rate ${fmtPercent(data.kpis.duplicate_external_action_rate, 2)}`} tone="info" />
            <StatTile label="Approval rate" value={fmtPercent(data.kpis.approval_rate, 1)} hint={`${fmtInt(data.kpis.approvals_requested)} requested`} />
            <StatTile label="Approval latency" value={data.kpis.approval_latency_minutes_avg === null ? "—" : fmtMinutes(data.kpis.approval_latency_minutes_avg)} hint="average time to decision" />
            <StatTile label="Human intervention rate" value={fmtPercent(data.kpis.human_intervention_rate, 1)} hint="agent runs needing approval or input" tone="warning" />
            <StatTile label="Validation failures" value={fmtInt(data.kpis.validation_failures)} hint="invalid agent/LLM output" tone={data.kpis.validation_failures > 0 ? "danger" : "neutral"} />
          </section>

          <Card>
            <CardToolbar title="ROI" description="Estimates, except realized savings (finance-verified)." />
            <CardContent className="grid gap-4 lg:grid-cols-3">
              <div className="grid gap-3 sm:grid-cols-2 lg:col-span-2">
                <StatTile label="Estimated time saved" value={fmtMinutes(data.roi.estimated_minutes_saved)} tone="accent" />
                <StatTile label="Estimated labor value" value={fmtCurrency(data.roi.estimated_labor_value_usd)} hint="time saved × hourly cost" tone="accent" />
                <StatTile label="Realized savings" value={fmtCurrency(data.roi.realized_savings_usd)} hint={`realization rate ${fmtPercent(data.roi.assumptions.realization_rate, 0)}`} tone={data.roi.realized_savings_usd > 0 ? "success" : "neutral"} />
                <StatTile label="Net estimated value" value={fmtCurrency(data.roi.net_estimated_value_usd)} hint={`labor value − AI ${fmtCurrency(data.roi.ai_cost_usd)} − infra ${fmtCurrency(data.roi.infra_cost_usd)}`} />
              </div>
              <div className="space-y-3 rounded-md border border-border bg-surface-2/60 p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Assumptions</p>
                <KeyValueList
                  columns={1}
                  dense
                  items={[
                    { label: "Loaded hourly cost", value: fmtCurrency(data.roi.assumptions.loaded_hourly_cost_usd) },
                    { label: "Infra cost per run", value: fmtCurrency(data.roi.assumptions.infra_cost_per_run_usd, { precise: true }) },
                    { label: "Realization rate", value: fmtPercent(data.roi.assumptions.realization_rate, 0) },
                    { label: "Monthly platform fee", value: fmtCurrency(data.roi.assumptions.monthly_platform_fee_usd) },
                  ]}
                />
                <p className="flex items-start gap-1.5 text-[11px] text-fg-subtle">
                  <Info className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                  <span>Change these in Admin → Tenant.</span>
                </p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardToolbar title="Agent performance" />
            <CardContent>
              <AgentTable rows={data.agents} />
            </CardContent>
          </Card>

          <Card>
            <CardToolbar title="Workflow performance" />
            <CardContent>
              <WorkflowTable rows={data.workflows} />
            </CardContent>
          </Card>
        </>
      ) : null}

      <section aria-label="Usage and quotas" className="space-y-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-muted">Usage &amp; quotas</h2>
        {report.isLoading ? <SkeletonRows rows={3} /> : <UsageQuotas />}
      </section>
    </div>
  );
}
