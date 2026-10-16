"use client";

import { chartColors } from "@/components/charts/chart-primitives";
import { EmptyState } from "@/components/ui/states";
import { Tip } from "@/components/ui/tooltip";
import { DEPARTMENTS } from "@/lib/constants";
import type { DepartmentBreakdown } from "@/lib/types";
import { fmtInt, fmtPercent } from "@/lib/utils";

/** Horizontal bar list: one hue for magnitude; outcome counts are stated as text. */
export function DepartmentBars({ data }: { data: DepartmentBreakdown[] }) {
  const byKey = new Map(data.map((d) => [d.department, d]));
  const rows = DEPARTMENTS.map((d) => byKey.get(d.key) ?? { department: d.key, label: d.label, runs: 0, succeeded: 0, failed: 0 });
  const max = Math.max(1, ...rows.map((r) => r.runs));
  if (data.length === 0) return <EmptyState compact title="No agent runs in this period" description="Department activity appears once agents have run." />;
  return (
    <ul className="space-y-3" aria-label="Agent runs by department">
      {rows.map((row) => {
        const rate = row.runs > 0 ? row.succeeded / row.runs : null;
        return (
          <li key={row.department}>
            <div className="mb-1 flex items-center justify-between gap-2 text-xs">
              <span className="truncate font-medium text-fg">{row.label}</span>
              <span className="shrink-0 text-fg-muted tabular">
                {fmtInt(row.runs)} runs · {fmtInt(row.succeeded)} ok · {fmtInt(row.failed)} failed
              </span>
            </div>
            <Tip content={`${row.label}: ${fmtInt(row.runs)} runs, success rate ${fmtPercent(rate)}`}>
              <div className="h-2 w-full overflow-hidden rounded-full bg-surface-3" role="img" aria-label={`${row.label}: ${row.runs} runs`}>
                <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${(row.runs / max) * 100}%`, background: chartColors.series1 }} />
              </div>
            </Tip>
          </li>
        );
      })}
    </ul>
  );
}
