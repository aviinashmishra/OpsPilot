"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, LayoutGrid, List, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { toast } from "sonner";

import { AgentCard } from "@/components/agents/agent-card";
import { RiskBadge, StatusPill } from "@/components/ui/badge";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Input, Textarea } from "@/components/ui/input";
import { Chip, Segmented } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonCards } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Switch } from "@/components/ui/switch";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { api, errorMessage } from "@/lib/api";
import { DEPARTMENTS } from "@/lib/constants";
import { usePermission } from "@/lib/permissions";
import { useAgents } from "@/lib/queries";
import type { AgentCatalogOut, AgentSettingIn } from "@/lib/types";
import { fmtCurrency, fmtInt, fmtPercent } from "@/lib/utils";

function AgentsContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const department = searchParams.get("department") ?? "";
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"grid" | "list">("grid");
  const [pendingToggle, setPendingToggle] = useState<{ agent: AgentCatalogOut; enabled: boolean } | null>(null);
  const [reason, setReason] = useState("");
  const canAdmin = usePermission("agents:admin");
  const queryClient = useQueryClient();
  const agents = useAgents({});

  const setDepartment = (key: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (key) params.set("department", key);
    else params.delete("department");
    router.replace(`${pathname}${params.toString() ? `?${params.toString()}` : ""}`);
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (agents.data ?? []).filter((a) => (!department || a.department === department) && (!q || `${a.name} ${a.description} ${a.agent_key} ${a.use_cases.join(" ")}`.toLowerCase().includes(q)));
  }, [agents.data, department, search]);

  const toggle = useMutation({
    mutationFn: ({ agent, enabled }: { agent: AgentCatalogOut; enabled: boolean }) => {
      const body: AgentSettingIn = { enabled, disabled_reason: enabled ? null : reason.trim() || "Disabled from dashboard" };
      return api<AgentCatalogOut>(`/agents/${agent.agent_key}`, { method: "PATCH", body });
    },
    onSuccess: (updated) => {
      toast.success(`${updated.name} ${updated.enabled ? "enabled" : "disabled"}`);
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["agent", updated.agent_key] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
      setPendingToggle(null);
      setReason("");
    },
    onError: (error) => toast.error("Could not update agent", { description: errorMessage(error) }),
  });

  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const a of agents.data ?? []) map.set(a.department, (map.get(a.department) ?? 0) + 1);
    return map;
  }, [agents.data]);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Agents"
        description={agents.data ? `${agents.data.length} agents · ${agents.data.filter((a) => a.enabled).length} enabled` : undefined}
        actions={<Segmented aria-label="View" value={view} onChange={setView} options={[{ value: "grid", label: <LayoutGrid className="h-3.5 w-3.5" aria-label="Grid view" /> }, { value: "list", label: <List className="h-3.5 w-3.5" aria-label="List view" /> }]} />}
      />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by department">
          <Chip active={!department} onClick={() => setDepartment("")}>
            All {agents.data ? `(${agents.data.length})` : ""}
          </Chip>
          {DEPARTMENTS.map((d) => (
            <Chip key={d.key} active={department === d.key} onClick={() => setDepartment(d.key)}>
              {d.short} {counts.get(d.key) !== undefined ? `(${counts.get(d.key)})` : ""}
            </Chip>
          ))}
        </div>
        <div className="relative w-full lg:w-72">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search agents…" className="pl-8" aria-label="Search agents" />
        </div>
      </div>

      {agents.isError ? <ErrorState error={agents.error} onRetry={() => agents.refetch()} /> : null}
      {agents.isLoading ? (
        <SkeletonCards count={8} cardClassName="h-52" className="lg:grid-cols-3 xl:grid-cols-4" />
      ) : filtered.length === 0 ? (
        <EmptyState icon={Bot} title="No agents match" description="Try a different department or search term." />
      ) : view === "grid" ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((agent, i) => (
            <AgentCard key={agent.agent_key} agent={agent} index={i} canAdmin={canAdmin} onToggle={(a, enabled) => setPendingToggle({ agent: a, enabled })} />
          ))}
        </div>
      ) : (
        <TableWrap>
          <Table>
            <THead>
              <TR>
                <TH>Agent</TH>
                <TH>Department</TH>
                <TH>Status</TH>
                <TH>Risk</TH>
                <TH align="right">Success</TH>
                <TH align="right">Runs</TH>
                <TH align="right">Cost</TH>
                <TH align="center">Enabled</TH>
              </TR>
            </THead>
            <TBody>
              {filtered.map((agent) => (
                <TR key={agent.agent_key}>
                  <TD>
                    <Link href={`/agents/${agent.agent_key}`} className="font-medium text-fg hover:underline">
                      {agent.name}
                    </Link>
                    <span className="block text-xs text-fg-subtle">v{agent.current_version}</span>
                  </TD>
                  <TD className="text-fg-muted">{agent.department_label}</TD>
                  <TD>
                    <StatusPill status={agent.enabled ? "active" : "disabled"} size="sm" label={agent.enabled ? "Enabled" : "Disabled"} />
                  </TD>
                  <TD>
                    <RiskBadge level={agent.risk_level} size="sm" />
                  </TD>
                  <TD align="right">{fmtPercent(agent.stats.success_rate, 0)}</TD>
                  <TD align="right">{fmtInt(agent.stats.runs)}</TD>
                  <TD align="right">{fmtCurrency(agent.stats.cost_usd)}</TD>
                  <TD align="center">
                    <Switch size="sm" checked={agent.enabled} disabled={!canAdmin || !agent.globally_enabled} onCheckedChange={(checked) => setPendingToggle({ agent, enabled: checked })} aria-label={`${agent.enabled ? "Disable" : "Enable"} ${agent.name}`} />
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </TableWrap>
      )}

      <ConfirmDialog
        open={pendingToggle !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingToggle(null);
            setReason("");
          }
        }}
        title={pendingToggle?.enabled ? `Enable ${pendingToggle.agent.name}?` : `Disable ${pendingToggle?.agent.name}?`}
        description={pendingToggle?.enabled ? "The agent will be available to workflows and the playground for this tenant." : "Workflows that reach this agent will fail with agent_disabled until it is re-enabled."}
        confirmLabel={pendingToggle?.enabled ? "Enable" : "Disable"}
        tone={pendingToggle?.enabled ? "primary" : "danger"}
        loading={toggle.isPending}
        onConfirm={() => pendingToggle && toggle.mutate(pendingToggle)}
      >
        {pendingToggle && !pendingToggle.enabled ? (
          <div className="space-y-1.5">
            <label htmlFor="disable-reason" className="text-xs text-fg-muted">
              Reason (shown to operators)
            </label>
            <Textarea id="disable-reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="e.g. Pending policy review" />
          </div>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}

export default function AgentsPage() {
  return (
    <Suspense fallback={<SkeletonCards count={8} cardClassName="h-52" className="lg:grid-cols-3 xl:grid-cols-4" />}>
      <AgentsContent />
    </Suspense>
  );
}
