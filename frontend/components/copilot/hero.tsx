"use client";

import { motion, useReducedMotion } from "framer-motion";
import { ArrowUpRight, Cpu, Search, ShieldCheck, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";

import { KIND_META, kindMeta } from "@/components/copilot/step-trace";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { InlineError } from "@/components/ui/states";
import { Tip } from "@/components/ui/tooltip";
import type { CopilotStatusOut } from "@/lib/types";
import { cn, copilotModelLabel, fmtInt } from "@/lib/utils";

export function CopilotModeBadge({ status }: { status: CopilotStatusOut | undefined; compact?: boolean }) {
  if (!status) return null;
  const live = copilotModelLabel(status.mode);
  if (live) {
    return (
      <Badge tone="accent" icon={<Sparkles className="h-3 w-3" aria-hidden />} data-testid="copilot-mode">
        {live}{status.model ? ` · ${status.model}` : ""}
      </Badge>
    );
  }
  const paused = Boolean(status.ai && status.ai.routes.length > 0 && !status.ai.available);
  const back = status.ai?.next_available_at ? new Date(status.ai.next_available_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : null;
  return (
    <Tip content={paused ? `Every AI model is at its limit or busy${back ? `; back around ${back}` : ""}. Answers use the built-in planner until then.` : "No AI key is configured, so a built-in planner routes requests to tools."}>
      <span className="inline-flex flex-wrap items-center justify-center gap-1.5" data-testid="copilot-mode">
        <Badge tone={paused ? "warning" : "neutral"} icon={<Cpu className="h-3 w-3" aria-hidden />}>
          {paused ? `AI paused${back ? ` · back ${back}` : ""}` : "Built-in planner"}
        </Badge>
      </span>
    </Tip>
  );
}

export function toolCountsText(status: CopilotStatusOut): string {
  const c = status.tool_counts;
  const agents = c.agent ?? 0;
  const tools = c.tool ?? 0;
  const custom = c.custom ?? 0;
  return `${fmtInt(agents)} agent${agents === 1 ? "" : "s"} · ${fmtInt(tools)} tool${tools === 1 ? "" : "s"} · ${fmtInt(custom)} custom tool${custom === 1 ? "" : "s"}`;
}

function ToolsDialog({ status, open, onOpenChange }: { status: CopilotStatusOut; open: boolean; onOpenChange: (open: boolean) => void }) {
  const [query, setQuery] = useState("");
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = status.tools.filter((t) => !q || t.name.toLowerCase().includes(q) || t.label.toLowerCase().includes(q) || t.description.toLowerCase().includes(q));
    return Object.keys(KIND_META)
      .map((kind) => ({ kind, tools: filtered.filter((t) => (KIND_META[t.kind] ? t.kind : "platform") === kind) }))
      .filter((g) => g.tools.length > 0);
  }, [status.tools, query]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>What the Copilot can use</DialogTitle>
          <DialogDescription>Every tool runs with your permissions.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter tools…" className="pl-8" aria-label="Filter tools" />
          </div>
          {groups.length === 0 ? <p className="text-sm text-fg-subtle">No tools match “{query}”.</p> : null}
          {groups.map((group) => {
            const meta = kindMeta(group.kind);
            const Icon = meta.icon;
            return (
              <section key={group.kind} className="space-y-1.5">
                <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">
                  <Icon className="h-3.5 w-3.5" aria-hidden /> {meta.plural} <span className="font-normal text-fg-subtle tabular">({group.tools.length})</span>
                </h3>
                <ul className="divide-y divide-border rounded-lg border border-border">
                  {group.tools.map((tool) => (
                    <li key={tool.name} className="px-3 py-2">
                      <p className="flex flex-wrap items-baseline gap-x-2 text-sm font-medium text-fg">
                        {tool.label} <code className="font-mono text-[11px] font-normal text-fg-subtle">{tool.name}</code>
                      </p>
                      <p className="mt-0.5 line-clamp-2 text-xs text-fg-muted">{tool.description}</p>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}

export function CopilotHero({ status, statusError, statusLoading, onSuggestion, disabled }: { status: CopilotStatusOut | undefined; statusError: Error | null; statusLoading: boolean; onSuggestion: (text: string) => void; disabled?: boolean }) {
  const reduce = useReducedMotion();
  const [toolsOpen, setToolsOpen] = useState(false);
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col items-center px-2 py-8 text-center sm:py-12">
      <motion.div initial={reduce ? false : { opacity: 0, scale: 0.94 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.3, ease: [0.2, 0.8, 0.2, 1] }} className="relative mb-5">
        <span className="absolute inset-0 -z-10 rounded-full bg-gradient-to-br from-accent/40 to-accent-2/30 blur-2xl" aria-hidden />
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-accent to-accent-2 text-white shadow-glow">
          <Sparkles className="h-7 w-7" aria-hidden />
        </span>
      </motion.div>
      <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
        Ask your <span className="gradient-text">operations</span> anything
      </h2>
      <p className="mt-2 max-w-xl text-sm text-fg-muted">It calls the right agents and tools for you and shows every step.</p>
      {statusError ? (
        <div className="mt-4">
          <InlineError error={statusError} />
        </div>
      ) : null}

      <div className="mt-8 grid w-full gap-2 sm:grid-cols-2" role="list" aria-label="Suggested questions">
        {statusLoading
          ? Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-14 w-full" />)
          : (status?.suggestions ?? []).map((suggestion, i) => (
              <motion.div key={suggestion} role="listitem" initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2, delay: reduce ? 0 : 0.04 * i }}>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onSuggestion(suggestion)}
                  className={cn(
                    "group flex h-full w-full items-center justify-between gap-3 rounded-xl border border-border bg-surface/70 px-4 py-3 text-left text-sm text-fg transition-[border-color,background-color,box-shadow] hover:border-accent/50 hover:bg-surface-2 hover:shadow-glow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50",
                  )}
                >
                  <span>{suggestion}</span>
                  <ArrowUpRight className="h-4 w-4 shrink-0 text-fg-subtle transition-colors group-hover:text-accent" aria-hidden />
                </button>
              </motion.div>
            ))}
      </div>

      <p className="mt-6 inline-flex items-center gap-1.5 text-xs text-fg-subtle">
        <ShieldCheck className="h-3.5 w-3.5 text-success" aria-hidden /> Actions wait for approval · every call is audited
        {status ? (
          <Button variant="link" size="xs" className="ml-1 h-auto text-xs" onClick={() => setToolsOpen(true)}>
            Browse tools
          </Button>
        ) : null}
      </p>
      {status ? <ToolsDialog status={status} open={toolsOpen} onOpenChange={setToolsOpen} /> : null}
    </div>
  );
}
