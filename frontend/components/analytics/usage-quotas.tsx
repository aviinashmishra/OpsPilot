"use client";

import { Card, CardContent, CardToolbar } from "@/components/ui/card";
import { KeyValueList } from "@/components/ui/key-value";
import { Meter } from "@/components/ui/misc";
import { SkeletonRows } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { useUsage } from "@/lib/queries";
import { fmtCompact, fmtCurrency, fmtInt, fmtPercent, titleCase } from "@/lib/utils";

function meterTone(ratio: number | null): "accent" | "warning" | "danger" {
  if (ratio === null) return "accent";
  if (ratio >= 0.95) return "danger";
  if (ratio >= 0.8) return "warning";
  return "accent";
}

export function UsageQuotas() {
  const usage = useUsage();
  if (usage.isError) return <ErrorState error={usage.error} onRetry={() => usage.refetch()} compact />;
  if (usage.isLoading || !usage.data) return <SkeletonRows rows={4} />;
  const u = usage.data;
  const runs = u.totals.workflow_run?.quantity ?? 0;
  const tokens = u.totals.llm_tokens?.quantity ?? 0;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardToolbar title="Quota utilisation" description={`Billing period ${u.period} · ${u.plan} plan`} />
        <CardContent className="space-y-4">
          <Meter label="Workflow runs" value={runs} max={u.quotas.monthly_workflow_runs} tone={meterTone(u.utilization.workflow_runs)} format={(v, m) => `${fmtInt(v)} / ${fmtInt(m)} (${fmtPercent(u.utilization.workflow_runs, 1)})`} />
          <Meter label="LLM tokens" value={tokens} max={u.quotas.monthly_llm_tokens} tone={meterTone(u.utilization.llm_tokens)} format={(v, m) => `${fmtCompact(v)} / ${fmtCompact(m)} (${fmtPercent(u.utilization.llm_tokens, 1)})`} />
          <p className="text-xs text-fg-subtle">Max concurrent runs: {fmtInt(u.quotas.max_concurrent_runs)}</p>
        </CardContent>
      </Card>
      <Card>
        <CardToolbar title="Metered usage" description={`Total metered cost ${fmtCurrency(u.total_cost_usd)}`} />
        <CardContent>
          <KeyValueList columns={2} dense items={Object.entries(u.totals).map(([kind, total]) => ({ label: titleCase(kind), value: `${fmtInt(total.quantity)} · ${fmtCurrency(total.cost_usd)}` }))} />
        </CardContent>
      </Card>
    </div>
  );
}
