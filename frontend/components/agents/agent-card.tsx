"use client";

import { motion, useReducedMotion } from "framer-motion";
import { ArrowUpRight, Bot } from "lucide-react";
import Link from "next/link";

import { Badge, RiskBadge, StatusPill } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Tip } from "@/components/ui/tooltip";
import type { AgentCatalogOut } from "@/lib/types";
import { fmtCurrency, fmtInt, fmtPercent } from "@/lib/utils";

export function AgentCard({ agent, canAdmin, onToggle, index = 0 }: { agent: AgentCatalogOut; canAdmin: boolean; onToggle: (agent: AgentCatalogOut, enabled: boolean) => void; index?: number }) {
  const reduce = useReducedMotion();
  const stats = agent.stats;
  return (
    <motion.article initial={reduce ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, delay: Math.min(index, 12) * 0.02 }} className="surface-card group relative flex flex-col gap-3 p-4 transition-colors hover:border-accent/50">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-accent/20 to-accent-2/20 text-accent">
          <Bot className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <Link href={`/agents/${agent.agent_key}`} className="block truncate text-sm font-semibold text-fg hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
            {agent.name}
            <ArrowUpRight className="ml-1 inline h-3 w-3 text-fg-subtle opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
          </Link>
          <p className="truncate text-xs text-fg-muted">
            {agent.department_label} · v{agent.current_version}
          </p>
        </div>
        <Tip content={canAdmin ? (agent.enabled ? "Disable for this tenant" : "Enable for this tenant") : "Requires agents:admin"}>
          <span>
            <Switch size="sm" checked={agent.enabled} disabled={!canAdmin || !agent.globally_enabled} onCheckedChange={(checked) => onToggle(agent, checked)} aria-label={`${agent.enabled ? "Disable" : "Enable"} ${agent.name}`} />
          </span>
        </Tip>
      </div>
      <p className="line-clamp-2 text-xs leading-relaxed text-fg-muted">{agent.description}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusPill status={agent.enabled ? "active" : "disabled"} size="sm" label={agent.enabled ? "Enabled" : "Disabled"} />
        <RiskBadge level={agent.risk_level} size="sm" />
        {!agent.globally_enabled ? (
          <Badge size="sm" tone="danger">
            globally disabled
          </Badge>
        ) : null}
      </div>
      {agent.disabled_reason ? <p className="text-[11px] text-danger">{agent.disabled_reason}</p> : null}
      <dl className="mt-auto grid grid-cols-3 gap-2 border-t border-border pt-3 text-xs">
        <div>
          <dt className="text-fg-subtle">Success</dt>
          <dd className="font-medium text-fg tabular">{fmtPercent(stats.success_rate, 0)}</dd>
        </div>
        <div>
          <dt className="text-fg-subtle">Runs</dt>
          <dd className="font-medium text-fg tabular">{fmtInt(stats.runs)}</dd>
        </div>
        <div>
          <dt className="text-fg-subtle">Cost</dt>
          <dd className="font-medium text-fg tabular">{fmtCurrency(stats.cost_usd)}</dd>
        </div>
      </dl>
    </motion.article>
  );
}
