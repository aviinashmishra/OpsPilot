"use client";

import { useMemo } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { ChartLegend, ChartTooltipFrame, chartColors } from "@/components/charts/chart-primitives";
import type { DailySeriesPoint } from "@/lib/types";
import { fmtCurrency, fmtInt, fmtShortDate } from "@/lib/utils";

interface TooltipPayloadItem {
  dataKey?: string | number;
  value?: number | string;
  payload?: DailySeriesPoint;
}

function RunsTooltip({ active, payload }: { active?: boolean; payload?: TooltipPayloadItem[] }) {
  if (!active || !payload || payload.length === 0 || !payload[0].payload) return null;
  const point = payload[0].payload;
  return (
    <ChartTooltipFrame
      title={fmtShortDate(point.date)}
      rows={[
        { label: "Completed", value: fmtInt(point.completed), color: chartColors.series1 },
        { label: "Failed", value: fmtInt(point.failed), color: chartColors.series2 },
        { label: "Other", value: fmtInt(point.other), color: chartColors.neutral },
        { label: "Total", value: fmtInt(point.completed + point.failed + point.other) },
      ]}
    />
  );
}

function CostTooltip({ active, payload }: { active?: boolean; payload?: TooltipPayloadItem[] }) {
  if (!active || !payload || payload.length === 0 || !payload[0].payload) return null;
  const point = payload[0].payload;
  return <ChartTooltipFrame title={fmtShortDate(point.date)} rows={[{ label: "AI cost", value: fmtCurrency(point.cost_usd), color: chartColors.cost }]} />;
}

/**
 * Daily workflow runs as a stacked column chart (status = identity, legend +
 * tooltip carry labels) plus a separate single-series area for cost. Two
 * charts rather than one dual-axis chart.
 */
export function DailyRunsChart({ series }: { series: DailySeriesPoint[] }) {
  const totals = useMemo(() => series.reduce((acc, p) => ({ completed: acc.completed + p.completed, failed: acc.failed + p.failed, other: acc.other + p.other, cost: acc.cost + p.cost_usd }), { completed: 0, failed: 0, other: 0, cost: 0 }), [series]);
  const tickInterval = Math.max(0, Math.ceil(series.length / 8) - 1);

  return (
    <div className="space-y-5">
      <div>
        <ChartLegend
          className="mb-2"
          entries={[
            { label: "Completed", color: chartColors.series1, value: fmtInt(totals.completed) },
            { label: "Failed / timed out", color: chartColors.series2, value: fmtInt(totals.failed) },
            { label: "Running / waiting / other", color: chartColors.neutral, value: fmtInt(totals.other) },
          ]}
        />
        <div className="h-56 w-full" role="img" aria-label="Workflow runs per day by outcome">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={series} margin={{ top: 4, right: 4, left: -18, bottom: 0 }} barCategoryGap="28%">
              <CartesianGrid vertical={false} stroke={chartColors.grid} />
              <XAxis dataKey="date" tickFormatter={fmtShortDate} interval={tickInterval} tickLine={false} axisLine={{ stroke: chartColors.grid }} tick={{ fill: chartColors.axis, fontSize: 11 }} />
              <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: chartColors.axis, fontSize: 11 }} width={40} />
              <Tooltip content={<RunsTooltip />} cursor={{ fill: "hsl(var(--fg) / 0.05)" }} />
              <Bar dataKey="completed" stackId="runs" fill={chartColors.series1} stroke="hsl(var(--surface))" strokeWidth={1} name="Completed" />
              <Bar dataKey="failed" stackId="runs" fill={chartColors.series2} stroke="hsl(var(--surface))" strokeWidth={1} name="Failed" />
              <Bar dataKey="other" stackId="runs" fill={chartColors.neutral} stroke="hsl(var(--surface))" strokeWidth={1} name="Other" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div>
        <div className="mb-2 flex items-center justify-between text-xs text-fg-muted">
          <span>AI cost per day</span>
          <span className="text-fg tabular">{fmtCurrency(totals.cost)} total</span>
        </div>
        <div className="h-28 w-full" role="img" aria-label="AI cost per day">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={series} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
              <defs>
                <linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={chartColors.cost} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={chartColors.cost} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid vertical={false} stroke={chartColors.grid} />
              <XAxis dataKey="date" tickFormatter={fmtShortDate} interval={tickInterval} tickLine={false} axisLine={{ stroke: chartColors.grid }} tick={{ fill: chartColors.axis, fontSize: 11 }} />
              <YAxis tickLine={false} axisLine={false} tick={{ fill: chartColors.axis, fontSize: 11 }} width={48} tickFormatter={(v: number) => `$${v.toFixed(v < 1 ? 2 : 0)}`} />
              <Tooltip content={<CostTooltip />} cursor={{ stroke: chartColors.axis, strokeDasharray: "3 3" }} />
              <Area type="monotone" dataKey="cost_usd" stroke={chartColors.cost} strokeWidth={2} fill="url(#costFill)" dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "hsl(var(--surface))" }} name="AI cost" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
