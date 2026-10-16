"use client";

import Link from "next/link";

import { StatusPill } from "@/components/ui/badge";
import type { WorkflowRunOut } from "@/lib/types";
import { fmtCurrency, fmtDateTime, fmtRelative, shortId, titleCase } from "@/lib/utils";

/** Compact run row used in overview lists. */
export function RunListItem({ run }: { run: WorkflowRunOut }) {
  return (
    <li>
      <Link href={`/workflows/${run.id}`} className="flex items-center gap-3 rounded-md px-2 py-2 transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
        <StatusPill status={run.status} size="sm" className="w-[132px] shrink-0 justify-center" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-fg">{titleCase(run.workflow_key.replace(/^single_agent__/, "agent: "))}</span>
          <span className="block truncate text-xs text-fg-subtle">
            <code className="font-mono">{shortId(run.id)}</code>
            {run.current_node ? ` · at ${run.current_node}` : ""}
          </span>
        </span>
        <span className="hidden text-right text-xs text-fg-muted sm:block">
          <span className="block tabular">{fmtCurrency(run.cost_usd)}</span>
          <time dateTime={run.created_at} title={fmtDateTime(run.created_at)} className="block text-fg-subtle">
            {fmtRelative(run.created_at)}
          </time>
        </span>
      </Link>
    </li>
  );
}
