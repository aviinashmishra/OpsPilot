"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, KeyRound, Lock, Pencil, Plus, ShieldCheck, Sparkles, Trash2, Webhook } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { CustomToolDialog, CustomToolTestDialog } from "@/components/integrations/custom-tool-dialogs";
import { McpCard } from "@/components/integrations/mcp-card";
import { Badge, RiskBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardToolbar } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Switch } from "@/components/ui/switch";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { Tip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { qk, useCustomTools } from "@/lib/queries";
import type { CustomToolOut, CustomToolPatch } from "@/lib/types";
import { cn, fmtDateTime, fmtInt, fmtRelative } from "@/lib/utils";

const METHOD_TONE: Record<string, string> = {
  GET: "text-success border-success/35 bg-success/10",
  POST: "text-info border-info/35 bg-info/10",
  PUT: "text-warning border-warning/35 bg-warning/10",
  PATCH: "text-warning border-warning/35 bg-warning/10",
  DELETE: "text-danger border-danger/35 bg-danger/10",
};

export function MethodTag({ method }: { method: string }) {
  return <span className={cn("inline-flex h-5 shrink-0 items-center rounded border px-1.5 font-mono text-[10px] font-semibold", METHOD_TONE[method] ?? "border-border text-fg-muted")}>{method}</span>;
}

export function CustomToolsTab({ canAdmin }: { canAdmin: boolean }) {
  const tools = useCustomTools();
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<CustomToolOut | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [testing, setTesting] = useState<CustomToolOut | null>(null);
  const [deleting, setDeleting] = useState<CustomToolOut | null>(null);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: qk.customTools });
    void queryClient.invalidateQueries({ queryKey: qk.toolCatalog });
    void queryClient.invalidateQueries({ queryKey: qk.copilotStatus });
  };

  const toggle = useMutation({
    mutationFn: ({ tool, enabled }: { tool: CustomToolOut; enabled: boolean }) => api<CustomToolOut>(`/custom-tools/${encodeURIComponent(tool.id)}`, { method: "PATCH", body: { enabled } satisfies CustomToolPatch }),
    onMutate: async ({ tool, enabled }) => {
      await queryClient.cancelQueries({ queryKey: qk.customTools });
      const previous = queryClient.getQueryData<CustomToolOut[]>(qk.customTools);
      queryClient.setQueryData<CustomToolOut[]>(qk.customTools, (list) => list?.map((t) => (t.id === tool.id ? { ...t, enabled } : t)));
      return { previous };
    },
    onSuccess: (updated) => toast.success(`${updated.name} ${updated.enabled ? "enabled" : "disabled"}`),
    onError: (error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(qk.customTools, context.previous);
      toast.error("Could not update the tool", { description: errorMessage(error) });
    },
    onSettled: invalidate,
  });

  const remove = useMutation({
    mutationFn: (tool: CustomToolOut) => api<void>(`/custom-tools/${encodeURIComponent(tool.id)}`, { method: "DELETE" }),
    onSuccess: (_, tool) => {
      toast.success(`Deleted ${tool.name}`);
      setDeleting(null);
      invalidate();
    },
    onError: (error) => toast.error("Could not delete the tool", { description: errorMessage(error) }),
  });

  const openNew = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <div className="space-y-4 xl:col-span-2">
        <Card>
          <CardToolbar
            title="Custom HTTP tools"
            actions={
              canAdmin ? (
                <Button variant="primary" size="sm" onClick={openNew} leftIcon={<Plus className="h-4 w-4" aria-hidden />}>
                  New tool
                </Button>
              ) : (
                <Badge size="sm" icon={<Lock className="h-3 w-3" aria-hidden />}>
                  read-only · integrations:admin to manage
                </Badge>
              )
            }
          />
          <CardContent>
            {tools.isError ? (
              <ErrorState error={tools.error} onRetry={() => tools.refetch()} compact />
            ) : tools.isLoading ? (
              <SkeletonRows rows={3} />
            ) : !tools.data || tools.data.length === 0 ? (
              <EmptyState
                icon={Webhook}
                title="No custom tools yet"
                description="Register your own REST endpoint so the Copilot can call it."
                action={
                  canAdmin ? (
                    <Button variant="primary" size="sm" onClick={openNew} leftIcon={<Plus className="h-4 w-4" aria-hidden />}>
                      New tool
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <TableWrap>
                <Table className="min-w-[860px]">
                  <THead>
                    <TR>
                      <TH>Tool</TH>
                      <TH>Endpoint</TH>
                      <TH>Behaviour</TH>
                      <TH align="right">Calls</TH>
                      <TH>Last called</TH>
                      <TH>Enabled</TH>
                      <TH align="right">
                        <span className="sr-only">Actions</span>
                      </TH>
                    </TR>
                  </THead>
                  <TBody>
                    {tools.data.map((tool) => (
                      <TR key={tool.id} data-testid="custom-tool-row">
                        <TD className="max-w-[240px]">
                          <span className="font-mono text-sm font-medium text-fg">{tool.name}</span>
                          <span className="block truncate text-xs text-fg-muted" title={tool.description}>
                            {tool.description}
                          </span>
                        </TD>
                        <TD className="max-w-[280px]">
                          <span className="flex items-center gap-1.5">
                            <MethodTag method={tool.method} />
                            <code className="truncate font-mono text-[11px] text-fg-muted" title={tool.url_template}>
                              {tool.url_template}
                            </code>
                          </span>
                          {tool.has_secret ? (
                            <span className="mt-1 inline-flex items-center gap-1 text-[11px] text-fg-subtle">
                              <KeyRound className="h-3 w-3" aria-hidden /> {tool.auth_header_name ?? "auth"} secret set
                            </span>
                          ) : null}
                        </TD>
                        <TD>
                          <div className="flex flex-wrap gap-1">
                            {tool.side_effect ? (
                              <Badge size="sm" tone="warning">
                                side effect · approval
                              </Badge>
                            ) : (
                              <Badge size="sm">read-only</Badge>
                            )}
                            <RiskBadge level={tool.risk_level} size="sm" />
                          </div>
                        </TD>
                        <TD align="right">{fmtInt(tool.call_count)}</TD>
                        <TD className="text-xs text-fg-muted" title={fmtDateTime(tool.last_called_at)}>
                          {tool.last_called_at ? fmtRelative(tool.last_called_at) : "never"}
                        </TD>
                        <TD>
                          <Switch size="sm" checked={tool.enabled} disabled={!canAdmin || (toggle.isPending && toggle.variables?.tool.id === tool.id)} onCheckedChange={(enabled) => toggle.mutate({ tool, enabled })} aria-label={`${tool.enabled ? "Disable" : "Enable"} ${tool.name}`} />
                        </TD>
                        <TD align="right">
                          <div className="flex justify-end gap-1">
                            <Button size="xs" variant="outline" onClick={() => setTesting(tool)} disabled={!canAdmin} leftIcon={<FlaskConical className="h-3 w-3" aria-hidden />}>
                              Test
                            </Button>
                            <Tip content="Edit">
                              <Button
                                size="icon-sm"
                                variant="ghost"
                                disabled={!canAdmin}
                                onClick={() => {
                                  setEditing(tool);
                                  setDialogOpen(true);
                                }}
                                aria-label={`Edit ${tool.name}`}
                              >
                                <Pencil className="h-3.5 w-3.5" aria-hidden />
                              </Button>
                            </Tip>
                            <Tip content="Delete">
                              <Button size="icon-sm" variant="ghost" disabled={!canAdmin} onClick={() => setDeleting(tool)} aria-label={`Delete ${tool.name}`} className="hover:text-danger">
                                <Trash2 className="h-3.5 w-3.5" aria-hidden />
                              </Button>
                            </Tip>
                          </div>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              </TableWrap>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="space-y-4">
        <Card>
          <CardToolbar title="How custom tools are used" />
          <CardContent>
            <ul className="space-y-3 text-sm text-fg-muted">
              <li className="flex gap-2.5">
                <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" aria-hidden />
                <span>
                  Used by the Copilot for people with the <code className="font-mono text-xs">tools:custom</code> permission.
                </span>
              </li>
              <li className="flex gap-2.5">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
                <span>
Side-effecting tools require approval.</span>
              </li>
              <li className="flex gap-2.5">
                <Lock className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
                <span>
Private-network destinations are blocked; public https only.</span>
              </li>
              <li className="flex gap-2.5">
                <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-fg-subtle" aria-hidden />
                <span>Secrets are encrypted; every call is audited.</span>
              </li>
            </ul>
          </CardContent>
        </Card>
        <McpCard />
      </div>

      <CustomToolDialog open={dialogOpen} onOpenChange={setDialogOpen} tool={editing} />
      <CustomToolTestDialog tool={testing} onOpenChange={(open) => !open && setTesting(null)} />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete ${deleting?.name ?? "tool"}?`}
        description="The Copilot can no longer call it. Past calls stay in the audit trail."
        confirmLabel="Delete tool"
        tone="danger"
        loading={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </div>
  );
}
