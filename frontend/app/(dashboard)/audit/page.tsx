"use client";

import { useMutation } from "@tanstack/react-query";
import { ChevronDown, ScrollText, Search, ShieldCheck, ShieldX } from "lucide-react";
import { Fragment, useState } from "react";
import { toast } from "sonner";

import { Badge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyableId } from "@/components/ui/copy-button";
import { Input, NativeSelect } from "@/components/ui/input";
import { JsonViewer } from "@/components/ui/json-viewer";
import { KeyValueList } from "@/components/ui/key-value";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { Tip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { AUDIT_SEVERITIES } from "@/lib/constants";
import { useDebounced } from "@/lib/hooks";
import { useAuditEvents } from "@/lib/queries";
import type { AuditVerifyOut } from "@/lib/types";
import { cn, fmtDateTime, fmtInt, fmtRelative, titleCase } from "@/lib/utils";

const PAGE = 50;

export default function AuditPage() {
  const [q, setQ] = useState("");
  const [action, setAction] = useState("");
  const [severity, setSeverity] = useState("");
  const [correlation, setCorrelation] = useState("");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [verification, setVerification] = useState<AuditVerifyOut | null>(null);
  const dq = useDebounced(q.trim(), 350);
  const dAction = useDebounced(action.trim(), 350);
  const dCorrelation = useDebounced(correlation.trim(), 350);
  const events = useAuditEvents({ q: dq || undefined, action: dAction || undefined, severity: severity || undefined, correlation_id: dCorrelation || undefined, limit: PAGE, offset });

  const verify = useMutation({
    mutationFn: () => api<AuditVerifyOut>("/audit-events/verify"),
    onSuccess: (result) => {
      setVerification(result);
      if (result.ok) toast.success("Hash chain intact", { description: `${fmtInt(result.checked)} events verified` });
      else toast.error("Hash chain broken", { description: `${result.reason ?? "mismatch"} at ${result.broken_at ?? "?"}` });
    },
    onError: (error) => toast.error("Verification failed", { description: errorMessage(error) }),
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Audit trail"
        actions={
          <Button variant="primary" onClick={() => verify.mutate()} loading={verify.isPending} leftIcon={<ShieldCheck className="h-4 w-4" aria-hidden />}>
            Verify hash chain
          </Button>
        }
      />
      {verification ? (
        <div role="status" className={cn("flex flex-wrap items-center gap-2 rounded-md border px-4 py-3 text-sm", verification.ok ? "border-success/40 bg-success/10 text-success" : "border-danger/40 bg-danger/10 text-danger")}>
          {verification.ok ? <ShieldCheck className="h-4 w-4" aria-hidden /> : <ShieldX className="h-4 w-4" aria-hidden />}
          {verification.ok ? `Chain intact — ${fmtInt(verification.checked)} events verified.` : `Chain broken after ${fmtInt(verification.checked)} events: ${verification.reason ?? "mismatch"} at ${verification.broken_at ?? "unknown"}.`}
          <Button size="xs" variant="ghost" className="ml-auto" onClick={() => setVerification(null)}>
            Dismiss
          </Button>
        </div>
      ) : null}

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
          <Input value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} placeholder="Search action, resource or actor…" className="pl-8" aria-label="Search audit events" />
        </div>
        <Input value={action} onChange={(e) => { setAction(e.target.value); setOffset(0); }} placeholder="Action prefix, e.g. approval." aria-label="Action prefix" />
        <NativeSelect value={severity} onChange={(e) => { setSeverity(e.target.value); setOffset(0); }} aria-label="Severity">
          <option value="">All severities</option>
          {AUDIT_SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {titleCase(s)}
            </option>
          ))}
        </NativeSelect>
        <Input value={correlation} onChange={(e) => { setCorrelation(e.target.value); setOffset(0); }} placeholder="Correlation id" aria-label="Correlation id" className="font-mono text-xs" />
      </div>

      {events.isError ? <ErrorState error={events.error} onRetry={() => events.refetch()} /> : null}
      {events.isLoading ? (
        <SkeletonRows rows={10} />
      ) : events.data && events.data.items.length === 0 ? (
        <EmptyState icon={ScrollText} title="No audit events match" />
      ) : events.data ? (
        <>
          <TableWrap>
            <Table className="min-w-[900px]">
              <THead>
                <TR>
                  <TH className="w-8">
                    <span className="sr-only">Expand</span>
                  </TH>
                  <TH>Time</TH>
                  <TH>Severity</TH>
                  <TH>Action</TH>
                  <TH>Actor</TH>
                  <TH>Resource</TH>
                  <TH>Correlation</TH>
                </TR>
              </THead>
              <TBody>
                {events.data.items.map((event) => {
                  const open = expanded === event.id;
                  return (
                    <Fragment key={event.id}>
                      <TR interactive onClick={() => setExpanded(open ? null : event.id)} aria-expanded={open}>
                        <TD>
                          <ChevronDown className={cn("h-4 w-4 text-fg-subtle transition-transform", open && "rotate-180")} aria-hidden />
                        </TD>
                        <TD>
                          <Tip content={fmtDateTime(event.created_at)}>
                            <time dateTime={event.created_at} className="text-fg-muted">
                              {fmtRelative(event.created_at)}
                            </time>
                          </Tip>
                        </TD>
                        <TD>
                          <StatusPill status={event.severity} size="sm" />
                        </TD>
                        <TD>
                          <code className="font-mono text-xs text-fg">{event.action}</code>
                        </TD>
                        <TD className="text-xs text-fg-muted">
                          <Badge size="sm" className="mr-1">
                            {event.actor_type}
                          </Badge>
                          <span className="font-mono">{event.actor_id ? event.actor_id.slice(0, 8) : "—"}</span>
                        </TD>
                        <TD className="text-xs text-fg-muted">
                          {event.resource_type}
                          {event.resource_id ? <span className="ml-1 font-mono">{event.resource_id.slice(0, 8)}</span> : null}
                        </TD>
                        <TD onClick={(e) => e.stopPropagation()}>
                          <CopyableId value={event.correlation_id} />
                        </TD>
                      </TR>
                      {open ? (
                        <TR>
                          <TD colSpan={7} className="bg-surface-2/40">
                            <div className="grid gap-4 py-2 lg:grid-cols-2">
                              <KeyValueList
                                dense
                                columns={1}
                                items={[
                                  { label: "Event id", value: event.id, mono: true },
                                  { label: "Actor", value: event.actor_id ?? "—", mono: true },
                                  { label: "Resource id", value: event.resource_id ?? "—", mono: true },
                                  { label: "Hash", value: event.hash, mono: true },
                                  { label: "Previous hash", value: event.prev_hash ?? "— (chain start)", mono: true },
                                ]}
                              />
                              <JsonViewer value={event.details} title="Details" maxHeight="20rem" />
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
          <Pagination total={events.data.total} limit={events.data.limit} offset={events.data.offset} onChange={setOffset} label="events" />
        </>
      ) : null}
    </div>
  );
}
