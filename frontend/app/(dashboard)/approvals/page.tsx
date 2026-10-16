"use client";

import { ClipboardCheck, Clock } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ApprovalDrawer } from "@/components/approvals/approval-drawer";
import { Badge, RiskBadge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tip } from "@/components/ui/tooltip";
import { APPROVAL_DECIDED_STATUSES } from "@/lib/constants";
import { useTick } from "@/lib/hooks";
import { usePermission } from "@/lib/permissions";
import { useAgents, useApprovals } from "@/lib/queries";
import { expiresIn, fmtDateTime, fmtRelative, titleCase } from "@/lib/utils";

const PAGE = 25;
type Tab = "pending" | "decided" | "all";
const TAB_STATUS: Record<Tab, string> = { pending: "pending", decided: APPROVAL_DECIDED_STATUSES, all: "all" };

function ApprovalsContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const selectedId = searchParams.get("id");
  const [tab, setTab] = useState<Tab>("pending");
  const [risk, setRisk] = useState("");
  const [agentKey, setAgentKey] = useState("");
  const [offset, setOffset] = useState(0);
  const canDecide = usePermission("approvals:decide");
  const agents = useAgents({}, { staleTime: 5 * 60_000 });
  const approvals = useApprovals({ status: TAB_STATUS[tab], risk_level: risk || undefined, agent_key: agentKey || undefined, limit: PAGE, offset });
  useTick(30_000);

  const select = (id: string | null) => {
    const params = new URLSearchParams(searchParams.toString());
    if (id) params.set("id", id);
    else params.delete("id");
    router.replace(`${pathname}${params.toString() ? `?${params.toString()}` : ""}`, { scroll: false });
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Approval center" badge={!canDecide ? <Badge tone="neutral">read-only · requires approvals:decide</Badge> : undefined} />

      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
        <Tabs
          value={tab}
          onValueChange={(v) => {
            setTab(v as Tab);
            setOffset(0);
          }}
        >
          <TabsList>
            <TabsTrigger value="pending">Pending</TabsTrigger>
            <TabsTrigger value="decided">Decided</TabsTrigger>
            <TabsTrigger value="all">All</TabsTrigger>
          </TabsList>
        </Tabs>
        <NativeSelect value={risk} onChange={(e) => { setRisk(e.target.value); setOffset(0); }} aria-label="Filter by risk" className="w-full sm:w-40">
          <option value="">All risk levels</option>
          {["low", "medium", "high", "critical"].map((r) => (
            <option key={r} value={r}>
              {titleCase(r)} risk
            </option>
          ))}
        </NativeSelect>
        <NativeSelect value={agentKey} onChange={(e) => { setAgentKey(e.target.value); setOffset(0); }} aria-label="Filter by agent" className="w-full sm:w-56">
          <option value="">All agents</option>
          {(agents.data ?? []).map((a) => (
            <option key={a.agent_key} value={a.agent_key}>
              {a.name}
            </option>
          ))}
        </NativeSelect>
      </div>

      {approvals.isError ? <ErrorState error={approvals.error} onRetry={() => approvals.refetch()} /> : null}
      {approvals.isLoading ? (
        <SkeletonRows rows={8} />
      ) : approvals.data && approvals.data.items.length === 0 ? (
        <EmptyState icon={ClipboardCheck} title={tab === "pending" ? "Nothing waiting for approval" : "No approvals match"} description={tab === "pending" ? "Agents will queue consequential actions here." : "Try another tab or filter."} />
      ) : approvals.data ? (
        <>
          <TableWrap>
            <Table className="min-w-[900px]">
              <THead>
                <TR>
                  <TH>Risk</TH>
                  <TH>Action</TH>
                  <TH>Agent</TH>
                  <TH>Status</TH>
                  <TH>Requested</TH>
                  <TH>{tab === "pending" ? "Expires" : "Reviewer"}</TH>
                  <TH align="right">Review</TH>
                </TR>
              </THead>
              <TBody>
                {approvals.data.items.map((a) => {
                  const expiry = expiresIn(a.expires_at);
                  return (
                    <TR key={a.id} interactive onClick={() => select(a.id)}>
                      <TD>
                        <RiskBadge level={a.risk_level} size="sm" />
                      </TD>
                      <TD>
                        <span className="font-medium text-fg">{a.action_type}</span>
                        <span className="block font-mono text-[11px] text-fg-subtle">{a.tool_key ?? "—"}</span>
                      </TD>
                      <TD className="text-fg-muted">{a.agent_key ? titleCase(a.agent_key) : "—"}</TD>
                      <TD>
                        <StatusPill status={a.status} size="sm" />
                      </TD>
                      <TD>
                        <Tip content={fmtDateTime(a.created_at)}>
                          <time dateTime={a.created_at} className="text-fg-muted">
                            {fmtRelative(a.created_at)}
                          </time>
                        </Tip>
                      </TD>
                      <TD>
                        {a.status === "pending" ? (
                          <span className={expiry.expired ? "text-fg-subtle" : expiry.soon ? "inline-flex items-center gap-1 text-danger" : "inline-flex items-center gap-1 text-fg-muted"}>
                            <Clock className="h-3 w-3" aria-hidden /> {expiry.text}
                          </span>
                        ) : (
                          <span className="text-fg-muted">
                            {a.reviewer_name ?? "—"}
                            {a.decided_at ? <span className="block text-[11px] text-fg-subtle">{fmtRelative(a.decided_at)}</span> : null}
                          </span>
                        )}
                      </TD>
                      <TD align="right">
                        <Button size="xs" variant={a.status === "pending" && canDecide ? "primary" : "outline"} onClick={(e) => { e.stopPropagation(); select(a.id); }}>
                          {a.status === "pending" && canDecide ? "Decide" : "View"}
                        </Button>
                      </TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
          </TableWrap>
          <Pagination total={approvals.data.total} limit={approvals.data.limit} offset={approvals.data.offset} onChange={setOffset} label="approvals" />
        </>
      ) : null}

      <ApprovalDrawer approvalId={selectedId} onClose={() => select(null)} />
    </div>
  );
}

export default function ApprovalsPage() {
  return (
    <Suspense fallback={<SkeletonRows rows={8} />}>
      <ApprovalsContent />
    </Suspense>
  );
}
