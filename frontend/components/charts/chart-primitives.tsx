"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** Chart roles resolved from CSS variables so light/dark pick the validated step. */
export const chartColors = {
  series1: "var(--chart-1)",
  series2: "var(--chart-2)",
  series3: "var(--chart-3)",
  neutral: "var(--chart-neutral)",
  cost: "var(--chart-cost)",
  grid: "var(--chart-grid)",
  axis: "var(--chart-axis)",
} as const;

export interface LegendEntry {
  label: string;
  color: string;
  value?: ReactNode;
}

export function ChartLegend({ entries, className }: { entries: LegendEntry[]; className?: string }) {
  return (
    <ul className={cn("flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted", className)} aria-label="Legend">
      {entries.map((entry) => (
        <li key={entry.label} className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: entry.color }} aria-hidden />
          <span>{entry.label}</span>
          {entry.value !== undefined ? <span className="text-fg tabular">{entry.value}</span> : null}
        </li>
      ))}
    </ul>
  );
}

export function ChartTooltipFrame({ title, rows }: { title: ReactNode; rows: Array<{ label: string; value: ReactNode; color?: string }> }) {
  return (
    <div className="min-w-[160px] rounded-md border border-border bg-surface px-3 py-2 text-xs shadow-pop">
      <p className="mb-1 font-medium text-fg">{title}</p>
      <ul className="space-y-0.5">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center justify-between gap-4">
            <span className="inline-flex items-center gap-1.5 text-fg-muted">
              {row.color ? <span className="h-2 w-2 rounded-sm" style={{ background: row.color }} aria-hidden /> : null}
              {row.label}
            </span>
            <span className="text-fg tabular">{row.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
