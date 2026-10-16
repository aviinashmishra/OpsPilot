"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronDown, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { Fragment, useState } from "react";
import { toast } from "sonner";

import { StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { JsonViewer } from "@/components/ui/json-viewer";
import { Segmented } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { Tip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import { useIncidents } from "@/lib/queries";
import type { IncidentOut } from "@/lib/types";
import { cn, fmtDateTime, fmtRelative, titleCase } from "@/lib/utils";

const PAGE = 50;

export default function IncidentsPage() {
  const [status, setStatus] = useState<string>("open");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [resolving, setResolving] = useState<IncidentOut | null>(null);
  const canResolve = usePermission("incidents:write");
  const queryClient = useQueryClient();
  const incidents = useIncidents({ status: status === "all" ? undefined : status, limit: PAGE, offset });

  const resolve = useMutation({
    mutationFn: (incident: IncidentOut) => api<IncidentOut>(`/incidents/${incident.id}/resolve`, { method: "POST" }),
    onSuccess: (incident) => {
      toast.success("Incident resolved", { description: incident.title });
      void queryClient.invalidateQueries({ queryKey: ["incidents"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
      setResolving(null);
    },
    onError: (error) => toast.error("Could not resolve incident", { description: errorMessage(error) }),
  });

  return (
    <div className="space-y-5">
      <PageHeader title="Incidents" actions={<Segmented aria-label="Status" value={status} onChange={(v) => { setStatus(v); setOffset(0); }} options={[{ value: "open", label: "Open" }, { value: "resolved", label: "Resolved" }, { value: "all", label: "All" }]} />} />
      {incidents.isError ? <ErrorState error={incidents.error} onRetry={() => incidents.refetch()} /> : null}
      {incidents.isLoading ? (
        <SkeletonRows rows={6} />
      ) : incidents.data && incidents.data.items.length === 0 ? (
        <EmptyState icon={ShieldAlert} title={status === "open" ? "No open incidents" : "No incidents"} description="Nothing needs attention." />
      ) : incidents.data ? (
        <>
          <TableWrap>
            <Table className="min-w-[860px]">
              <THead>
                <TR>
                  <TH className="w-8">
                    <span className="sr-only">Expand</span>
                  </TH>
                  <TH>Severity</TH>
                  <TH>Incident</TH>
                  <TH>Source</TH>
                  <TH>Status</TH>
                  <TH>Created</TH>
                  <TH align="right">Actions</TH>
                </TR>
              </THead>
              <TBody>
                {incidents.data.items.map((incident) => {
                  const open = expanded === incident.id;
                  return (
                    <Fragment key={incident.id}>
                      <TR interactive onClick={() => setExpanded(open ? null : incident.id)} aria-expanded={open}>
                        <TD>
                          <ChevronDown className={cn("h-4 w-4 text-fg-subtle transition-transform", open && "rotate-180")} aria-hidden />
                        </TD>
                        <TD>
                          <StatusPill status={incident.severity} size="sm" />
                        </TD>
                        <TD className="max-w-[420px]">
                          <span className="block truncate font-medium text-fg">{incident.title}</span>
                          <span className="block text-xs text-fg-subtle">{incident.kind}</span>
                        </TD>
                        <TD className="text-fg-muted">{incident.source}</TD>
                        <TD>
                          <StatusPill status={incident.status} size="sm" />
                        </TD>
                        <TD>
                          <Tip content={fmtDateTime(incident.created_at)}>
                            <time dateTime={incident.created_at} className="text-fg-muted">
                              {fmtRelative(incident.created_at)}
                            </time>
                          </Tip>
                        </TD>
                        <TD align="right" onClick={(e) => e.stopPropagation()}>
                          <div className="flex justify-end gap-1">
                            {incident.run_id ? (
                              <Link href={`/workflows/${incident.run_id}`} className="inline-flex h-7 items-center rounded-md border border-border px-2 text-xs text-fg-muted hover:bg-surface-2 hover:text-fg">
                                Run
                              </Link>
                            ) : null}
                            {incident.status === "open" ? (
                              <Button size="xs" variant="primary" disabled={!canResolve} onClick={() => setResolving(incident)} leftIcon={<CheckCircle2 className="h-3 w-3" aria-hidden />}>
                                Resolve
                              </Button>
                            ) : null}
                          </div>
                        </TD>
                      </TR>
                      {open ? (
                        <TR>
                          <TD colSpan={7} className="bg-surface-2/40">
                            <div className="py-2">
                              {incident.resolved_at ? <p className="mb-2 text-xs text-fg-muted">Resolved {fmtDateTime(incident.resolved_at)}</p> : null}
                              <JsonViewer value={incident.details} title="Details" maxHeight="20rem" />
                            </div>
                          </TD>
                        </TR>
                      ) : null}
                    </Fragment>
                  );
                })}
              </TBody>
            </Table>
          </TableWrap>
          <Pagination total={incidents.data.total} limit={incidents.data.limit} offset={incidents.data.offset} onChange={setOffset} label="incidents" />
        </>
      ) : null}
      <ConfirmDialog open={resolving !== null} onOpenChange={(open) => !open && setResolving(null)} title="Resolve this incident?" description={resolving ? `${titleCase(resolving.severity)}: ${resolving.title}` : undefined} confirmLabel="Resolve" loading={resolve.isPending} onConfirm={() => resolving && resolve.mutate(resolving)} />
    </div>
  );
}
