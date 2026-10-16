"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckCircle2, KeyRound, PlugZap, RefreshCw, Settings2, XCircle } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { ConfigureIntegrationDialog } from "@/components/integrations/configure-dialog";
import { CustomToolsTab } from "@/components/integrations/custom-tools-tab";
import { integrationIcon } from "@/components/integrations/integration-icon";
import { McpConnectContent } from "@/components/integrations/mcp-card";
import { ToolCatalogTab } from "@/components/integrations/tool-catalog-tab";
import { Badge, ModeBadge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ChipList } from "@/components/ui/key-value";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonCards, SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import { useIntegrationCatalog, useIntegrations } from "@/lib/queries";
import type { ConnectionTestOut, IntegrationOut } from "@/lib/types";
import { fmtDateTime, fmtRelative, titleCase } from "@/lib/utils";

const TABS = ["providers", "custom", "catalog"] as const;
type Tab = (typeof TABS)[number];

function IntegrationsContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const requested = searchParams.get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(requested ?? "") ? (requested as Tab) : "providers";
  const canAdmin = usePermission("integrations:admin");
  const integrations = useIntegrations();
  const [mcpOpen, setMcpOpen] = useState(false);
  const sandboxCount = integrations.data?.filter((i) => i.mode !== "live").length ?? 0;
  const liveCount = (integrations.data?.length ?? 0) - sandboxCount;

  const setTab = (next: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (next === "providers") params.delete("tab");
    else params.set("tab", next);
    const qs = params.toString();
    router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Integrations"
        badge={integrations.data ? <Badge>{sandboxCount} sandbox · {liveCount} live</Badge> : undefined}
        actions={
          <Button variant="outline" size="sm" onClick={() => setMcpOpen(true)} leftIcon={<Bot className="h-4 w-4" aria-hidden />}>
            Connect an AI client (MCP)
          </Button>
        }
      />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="w-full justify-start sm:w-auto">
          <TabsTrigger value="providers">Providers</TabsTrigger>
          <TabsTrigger value="custom">Custom tools</TabsTrigger>
          <TabsTrigger value="catalog">Tool catalog</TabsTrigger>
        </TabsList>
        <TabsContent value="providers">
          <ProvidersTab canAdmin={canAdmin} />
        </TabsContent>
        <TabsContent value="custom">
          <CustomToolsTab canAdmin={canAdmin} />
        </TabsContent>
        <TabsContent value="catalog">
          <ToolCatalogTab />
        </TabsContent>
      </Tabs>
      <Dialog open={mcpOpen} onOpenChange={setMcpOpen}>
        <DialogContent size="lg">
          <DialogHeader>
            <DialogTitle>Connect an AI client (MCP)</DialogTitle>
            <DialogDescription>Use OpsPilot from Claude, Cursor or any MCP client.</DialogDescription>
          </DialogHeader>
          <DialogBody>
            <McpConnectContent />
          </DialogBody>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function IntegrationsPage() {
  return (
    <Suspense fallback={<SkeletonRows rows={8} />}>
      <IntegrationsContent />
    </Suspense>
  );
}

function ProvidersTab({ canAdmin }: { canAdmin: boolean }) {
  const integrations = useIntegrations();
  const catalog = useIntegrationCatalog();
  const queryClient = useQueryClient();
  const [configuring, setConfiguring] = useState<IntegrationOut | null>(null);

  const test = useMutation({
    mutationFn: (integration: IntegrationOut) => api<ConnectionTestOut>(`/integrations/${integration.id}/test`, { method: "POST" }),
    onSuccess: (result) => {
      toast[result.ok ? "success" : "error"](`${titleCase(result.provider)} · ${result.mode === "mock" ? "sandbox" : "live"} test ${result.ok ? "passed" : "failed"}`, { description: result.message });
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
    },
    onError: (error) => toast.error("Connection test failed", { description: errorMessage(error) }),
  });

  const sync = useMutation({
    mutationFn: (integration: IntegrationOut) => api<IntegrationOut>(`/integrations/${integration.id}/sync`, { method: "POST" }),
    onSuccess: (updated) => {
      toast.success(`${updated.provider_label} sync checkpoint recorded`, { description: fmtDateTime(updated.last_sync_at) });
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
    },
    onError: (error) => toast.error("Sync failed", { description: errorMessage(error) }),
  });

  const families = new Map((catalog.data?.families ?? []).map((f) => [f.key, f]));

  return (
    <div className="space-y-5">
      {integrations.isError ? <ErrorState error={integrations.error} onRetry={() => integrations.refetch()} /> : null}
      {integrations.isLoading ? (
        <SkeletonCards count={6} className="lg:grid-cols-3" cardClassName="h-64" />
      ) : integrations.data && integrations.data.length === 0 ? (
        <EmptyState icon={PlugZap} title="No integrations" />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {(integrations.data ?? []).map((integration) => {
            const family = families.get(integration.provider);
            const Icon = integrationIcon(family?.icon);
            const live = integration.mode === "live";
            return (
              <article key={integration.id} className="surface-card flex flex-col gap-3 p-4">
                <div className="flex items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-surface-2 text-fg-muted">
                    <Icon className="h-5 w-5" aria-hidden />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h3 className="truncate text-sm font-semibold text-fg">{integration.provider_label}</h3>
                    <p className="truncate text-xs text-fg-muted">{integration.name}</p>
                  </div>
                  <ModeBadge mode={integration.mode} status={integration.status} />
                </div>
                <p className="text-xs text-fg-muted">
                  {live ? (
                    <>
                      Live provider: <span className="font-medium text-fg">{titleCase(integration.live_provider ?? "—")}</span>
                    </>
                  ) : (
                    <span className="inline-flex items-center gap-1">Sandbox (no external system connected){family && family.live_supported.length > 0 ? ` · live available: ${family.live_supported.map(titleCase).join(", ")}` : " · no live adapter yet"}</span>
                  )}
                </p>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
                  <div>
                    <dt className="text-fg-subtle">Status</dt>
                    <dd>
                      <StatusPill status={integration.status} size="sm" />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-fg-subtle">Last test</dt>
                    <dd className="text-fg">
                      {integration.last_test_at ? (
                        <Tip content={fmtDateTime(integration.last_test_at)}>
                          <span className="inline-flex items-center gap-1">
                            {integration.last_test_ok ? <CheckCircle2 className="h-3 w-3 text-success" aria-hidden /> : <XCircle className="h-3 w-3 text-danger" aria-hidden />}
                            {integration.last_test_ok ? "ok" : "failed"} · {fmtRelative(integration.last_test_at)}
                          </span>
                        </Tip>
                      ) : (
                        <span className="text-fg-subtle">never</span>
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-fg-subtle">Last sync</dt>
                    <dd className="text-fg">{integration.last_sync_at ? <span title={fmtDateTime(integration.last_sync_at)}>{fmtRelative(integration.last_sync_at)}</span> : <span className="text-fg-subtle">never</span>}</dd>
                  </div>
                  <div>
                    <dt className="text-fg-subtle">Secrets</dt>
                    <dd className="inline-flex items-center gap-1 text-fg">
                      <KeyRound className="h-3 w-3 text-fg-subtle" aria-hidden />
                      {integration.has_credentials ? "credentials stored" : "no credentials"}
                      {integration.has_webhook_secret ? " · webhook secret" : ""}
                    </dd>
                  </div>
                </dl>
                {integration.last_error ? <p className="rounded-md border border-danger/40 bg-danger/10 px-2 py-1 text-xs text-danger">{integration.last_error}</p> : null}
                {typeof integration.health.last_message === "string" && !integration.last_error ? <p className="text-xs text-fg-subtle">{integration.health.last_message}</p> : null}
                <div className="space-y-1.5">
                  <p className="text-[11px] font-medium uppercase tracking-wide text-fg-subtle">Capabilities</p>
                  <ChipList items={integration.capabilities} empty="None" />
                </div>
                {integration.scopes.length > 0 ? (
                  <div className="space-y-1.5">
                    <p className="text-[11px] font-medium uppercase tracking-wide text-fg-subtle">Scopes</p>
                    <ChipList items={integration.scopes} tone="accent" />
                  </div>
                ) : null}
                <div className="flex items-center justify-between text-xs text-fg-muted">
                  <Tip content={<ul className="max-h-60 space-y-0.5 overflow-auto font-mono text-[11px]">{integration.tools.map((t) => <li key={t}>{t}</li>)}</ul>}>
                    <span className="cursor-help underline decoration-dotted">{integration.tools.length} tools</span>
                  </Tip>
                </div>
                <div className="mt-auto flex flex-wrap gap-2 border-t border-border pt-3">
                  <Button size="sm" variant="primary" onClick={() => setConfiguring(integration)} disabled={!canAdmin} leftIcon={<Settings2 className="h-3.5 w-3.5" aria-hidden />}>
                    Configure
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => test.mutate(integration)} loading={test.isPending && test.variables?.id === integration.id} disabled={!canAdmin} leftIcon={<PlugZap className="h-3.5 w-3.5" aria-hidden />}>
                    Test connection
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => sync.mutate(integration)} loading={sync.isPending && sync.variables?.id === integration.id} disabled={!canAdmin} leftIcon={<RefreshCw className="h-3.5 w-3.5" aria-hidden />}>
                    Sync
                  </Button>
                </div>
              </article>
            );
          })}
        </div>
      )}
      {!canAdmin ? <p className="text-xs text-fg-subtle">Configuring, testing and syncing integrations requires integrations:admin.</p> : null}
      <ConfigureIntegrationDialog integration={configuring} family={configuring ? families.get(configuring.provider) ?? null : null} open={configuring !== null} onOpenChange={(open) => !open && setConfiguring(null)} />
    </div>
  );
}
