"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowUpRight, Bot, CheckCircle2, ChevronDown, Database, Hourglass, LayoutGrid, Loader2, type LucideIcon, Webhook, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge, type Tone } from "@/components/ui/badge";
import { JsonViewer } from "@/components/ui/json-viewer";
import { useTick } from "@/lib/hooks";
import type { CopilotStepOut } from "@/lib/types";
import { cn, fmtMs, parseDate } from "@/lib/utils";

export interface KindMeta {
  icon: LucideIcon;
  label: string;
  plural: string;
  chip: string;
}

export const KIND_META: Record<string, KindMeta> = {
  agent: { icon: Bot, label: "Agent", plural: "agents", chip: "bg-accent/12 text-accent border-accent/30" },
  tool: { icon: Database, label: "Tool", plural: "tools", chip: "bg-info/12 text-info border-info/30" },
  custom: { icon: Webhook, label: "Custom tool", plural: "custom tools", chip: "bg-accent-2/12 text-accent-2 border-accent-2/30" },
  platform: { icon: LayoutGrid, label: "Platform", plural: "platform helpers", chip: "bg-surface-3 text-fg-muted border-border-strong/60" },
};

export function kindMeta(kind: string): KindMeta {
  return KIND_META[kind] ?? KIND_META.platform;
}

const STATUS_META: Record<string, { icon: LucideIcon; tone: Tone; label: string; className: string }> = {
  running: { icon: Loader2, tone: "info", label: "Running", className: "text-info animate-spin" },
  ok: { icon: CheckCircle2, tone: "success", label: "Done", className: "text-success" },
  error: { icon: XCircle, tone: "danger", label: "Error", className: "text-danger" },
  needs_approval: { icon: Hourglass, tone: "warning", label: "Needs approval", className: "text-warning" },
};

/** Agent key from a Copilot tool name such as `agent__inventory_forecasting`. */
export function agentKeyFromTool(toolName: string): string | null {
  return toolName.startsWith("agent__") ? toolName.slice("agent__".length) : null;
}

function LiveDuration({ since }: { since: string }) {
  useTick(1000);
  const started = parseDate(since);
  if (!started) return null;
  const ms = Math.max(0, Date.now() - started.getTime());
  return <span className="tabular">{fmtMs(ms)}</span>;
}

function StepRow({ step }: { step: CopilotStepOut }) {
  const [open, setOpen] = useState(false);
  const reduce = useReducedMotion();
  const kind = kindMeta(step.kind);
  const KindIcon = kind.icon;
  const status = STATUS_META[step.status] ?? STATUS_META.ok;
  const StatusIcon = status.icon;
  const agentKey = agentKeyFromTool(step.tool_name);
  const detailsId = `step-${step.id}-details`;

  return (
    <motion.li
      layout={reduce ? false : "position"}
      initial={reduce ? false : { opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className={cn(
        "rounded-lg border bg-surface/80 transition-colors",
        step.status === "needs_approval" ? "border-warning/40" : step.status === "error" ? "border-danger/40" : step.status === "running" ? "border-info/40" : "border-border",
      )}
      data-testid="copilot-step"
      data-status={step.status}
    >
      <div className="flex items-start gap-2.5 px-3 py-2.5">
        <span className={cn("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border", kind.chip)} aria-hidden>
          <KindIcon className="h-3.5 w-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate text-sm font-medium text-fg">{step.label}</span>
            <span className="hidden font-mono text-[11px] text-fg-subtle sm:inline">{step.tool_name}</span>
            <span className="ml-auto flex shrink-0 items-center gap-1.5 text-xs text-fg-muted">
              {step.status === "needs_approval" ? (
                <Badge tone="warning" size="sm" icon={<Hourglass className="h-3 w-3" aria-hidden />}>
                  Needs approval
                </Badge>
              ) : (
                <span className="inline-flex items-center gap-1">
                  <StatusIcon className={cn("h-3.5 w-3.5", status.className)} aria-hidden />
                  <span className="sr-only sm:not-sr-only">{status.label}</span>
                </span>
              )}
              <span className="text-fg-subtle" aria-label="Duration">
                {step.status === "running" ? <LiveDuration since={step.created_at} /> : <span className="tabular">{fmtMs(step.duration_ms)}</span>}
              </span>
            </span>
          </div>
          {step.summary && step.summary !== step.label ? <p className={cn("mt-0.5 text-xs leading-relaxed", step.status === "error" ? "text-danger" : "text-fg-muted")}>{step.summary}</p> : step.status === "running" ? <p className="mt-0.5 text-xs text-fg-subtle">Working…</p> : null}
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {step.approval_ids.map((id) => (
              <Link key={id} href={`/approvals?id=${encodeURIComponent(id)}`} className="inline-flex items-center gap-1 font-medium text-warning hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
                Review approval <span className="font-mono text-[11px] opacity-80">{id.slice(0, 8)}</span>
                <ArrowUpRight className="h-3 w-3" aria-hidden />
              </Link>
            ))}
            {step.agent_run_id ? (
              <Link href={agentKey ? `/agents/${encodeURIComponent(agentKey)}?tab=runs` : "/agents"} className="inline-flex items-center gap-1 text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
                Agent run <span className="font-mono text-[11px] opacity-80">{step.agent_run_id.slice(0, 8)}</span>
                <ArrowUpRight className="h-3 w-3" aria-hidden />
              </Link>
            ) : null}
            {step.workflow_run_id ? (
              <Link href={`/workflows/${encodeURIComponent(step.workflow_run_id)}`} className="inline-flex items-center gap-1 text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
                Workflow run <span className="font-mono text-[11px] opacity-80">{step.workflow_run_id.slice(0, 8)}</span>
                <ArrowUpRight className="h-3 w-3" aria-hidden />
              </Link>
            ) : null}
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              aria-expanded={open}
              aria-controls={detailsId}
              className="ml-auto inline-flex items-center gap-1 rounded px-1 text-fg-subtle hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              {open ? "Hide" : "Input & output"}
              <ChevronDown className={cn("h-3 w-3 transition-transform", open && "rotate-180")} aria-hidden />
            </button>
          </div>
        </div>
      </div>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            id={detailsId}
            initial={reduce ? false : { height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={reduce ? { opacity: 0 } : { height: 0, opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden"
          >
            <div className="grid gap-2 border-t border-border p-3 lg:grid-cols-2">
              <JsonViewer value={step.input} title="Input" maxHeight="16rem" collapsed />
              <JsonViewer value={step.output} title="Output" maxHeight="16rem" collapsed />
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </motion.li>
  );
}

export interface StepGroup {
  iteration: number;
  steps: CopilotStepOut[];
}

export function groupSteps(steps: CopilotStepOut[]): StepGroup[] {
  const groups = new Map<number, CopilotStepOut[]>();
  for (const step of [...steps].sort((a, b) => a.sequence - b.sequence)) {
    const list = groups.get(step.iteration) ?? [];
    list.push(step);
    groups.set(step.iteration, list);
  }
  return Array.from(groups.entries())
    .sort(([a], [b]) => a - b)
    .map(([iteration, list]) => ({ iteration, steps: list }));
}

/** Live tool-call trace, grouped by planning iteration. */
export function StepTrace({ steps, className }: { steps: CopilotStepOut[]; className?: string }) {
  const groups = groupSteps(steps);
  return (
    <ol className={cn("space-y-3", className)} aria-label="Tool calls">
      {groups.map((group, gi) => {
        const running = group.steps.some((s) => s.status === "running");
        return (
          <li key={group.iteration} className="relative pl-6">
            <span className={cn("absolute left-[7px] top-6 bottom-0 w-px", gi === groups.length - 1 ? "bg-gradient-to-b from-border to-transparent" : "bg-border")} aria-hidden />
            <span className={cn("absolute left-0 top-1 flex h-[15px] w-[15px] items-center justify-center rounded-full border text-[9px] font-semibold tabular", running ? "border-info/60 bg-info/15 text-info" : "border-border-strong bg-surface-2 text-fg-muted")} aria-hidden>
              {gi + 1}
            </span>
            <p className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-fg-subtle">
              Step {gi + 1} · {group.steps.length === 1 ? "1 call" : `${group.steps.length} parallel calls`}
            </p>
            <ul className="space-y-1.5">
              {group.steps.map((step) => (
                <StepRow key={step.id} step={step} />
              ))}
            </ul>
          </li>
        );
      })}
    </ol>
  );
}

/** One-line digest used when a finished trace is collapsed. */
export function traceDigest(steps: CopilotStepOut[]): string {
  const groups = groupSteps(steps).length;
  const approvals = steps.reduce((n, s) => n + s.approval_ids.length, 0);
  const errors = steps.filter((s) => s.status === "error").length;
  const parts = [`${steps.length} tool call${steps.length === 1 ? "" : "s"}`, `${groups} step${groups === 1 ? "" : "s"}`];
  if (approvals) parts.push(`${approvals} awaiting approval`);
  if (errors) parts.push(`${errors} failed`);
  return parts.join(" · ");
}
