"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Check, Clock, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge, RiskBadge, StatusPill } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, Textarea } from "@/components/ui/input";
import { JsonViewer } from "@/components/ui/json-viewer";
import { ChipList, KeyValueList } from "@/components/ui/key-value";
import { Sheet } from "@/components/ui/sheet";
import { SkeletonText } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { api, errorMessage } from "@/lib/api";
import { useTick } from "@/lib/hooks";
import { usePermission } from "@/lib/permissions";
import { useApproval } from "@/lib/queries";
import type { ApprovalDecisionOut, ApprovalOut, JsonObject } from "@/lib/types";
import { expiresIn, fmtDateTime, fmtRelative, isPlainObject, titleCase } from "@/lib/utils";

function contextValue(context: JsonObject, key: string): string | null {
  const value = context[key];
  if (value === null || value === undefined) return null;
  return typeof value === "string" ? value : JSON.stringify(value);
}

export function ApprovalDrawer({ approvalId, onClose }: { approvalId: string | null; onClose: () => void }) {
  const approval = useApproval(approvalId);
  const canDecide = usePermission("approvals:decide");
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState<"approve" | "reject" | null>(null);
  const [decision, setDecision] = useState<ApprovalDecisionOut | null>(null);
  useTick(15_000);

  useEffect(() => {
    setNote("");
    setConfirm(null);
    setDecision(null);
  }, [approvalId]);

  const decide = useMutation({
    mutationFn: (kind: "approve" | "reject") => {
      if (!approval.data) throw new Error("Approval not loaded");
      return api<ApprovalDecisionOut>(`/approvals/${approval.data.id}/decision`, { method: "POST", body: { decision: kind, note: note.trim() || null, payload_hash: approval.data.payload_hash } });
    },
    onSuccess: (result, kind) => {
      setDecision(result);
      setConfirm(null);
      queryClient.setQueryData(["approval", result.approval.id], result.approval);
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      void queryClient.invalidateQueries({ queryKey: ["workflow"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
      void queryClient.invalidateQueries({ queryKey: ["audit"] });
      if (kind === "approve") {
        if (result.status === "executed") toast.success("Approved and executed", { description: "The action ran exactly once." });
        else toast.warning(`Approved · ${titleCase(result.status)}`, { description: "See the execution result for details." });
      } else {
        toast.success("Rejected", { description: "The agent's proposed action will not run." });
      }
    },
    onError: (error) => toast.error("Decision failed", { description: errorMessage(error) }),
  });

  const a: ApprovalOut | undefined = approval.data;
  const expiry = a ? expiresIn(a.expires_at) : null;
  const pending = a?.status === "pending" && !expiry?.expired;
  const context = a?.context ?? {};
  const inputPreview = isPlainObject(context.input_preview) ? (context.input_preview as JsonObject) : null;
  const runId = a?.run_id ?? contextValue(context, "workflow_run_id");

  return (
    <Sheet open={approvalId !== null} onOpenChange={(open) => !open && onClose()} title={a ? `${a.action_type}` : "Approval"} description={a ? `${titleCase(a.agent_key ?? "agent")} · requested ${fmtRelative(a.created_at)}` : undefined} size="xl" footer={a && pending ? (
      <div className="flex flex-col gap-3">
        <Field label={`Reviewer note${confirm === "reject" ? " (required to reject)" : " (optional)"}`} htmlFor="decision-note">
          <Textarea id="decision-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why are you approving or rejecting this action?" disabled={!canDecide} />
        </Field>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {!canDecide ? <span className="mr-auto text-xs text-fg-subtle">You need approvals:decide to act on this request.</span> : null}
          <Button variant="danger" onClick={() => setConfirm("reject")} disabled={!canDecide} leftIcon={<X className="h-4 w-4" aria-hidden />}>
            Reject
          </Button>
          <Button variant="primary" onClick={() => setConfirm("approve")} disabled={!canDecide} leftIcon={<Check className="h-4 w-4" aria-hidden />}>
            Approve
          </Button>
        </div>
      </div>
    ) : undefined}>
      {approval.isError ? <ErrorState error={approval.error} onRetry={() => approval.refetch()} compact /> : null}
      {approval.isLoading || !a ? (
        <SkeletonText lines={8} />
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill status={a.status} />
            <RiskBadge level={a.risk_level} />
            {pending && expiry ? (
              <Badge tone={expiry.soon ? "danger" : "warning"} icon={<Clock className="h-3 w-3" aria-hidden />}>
                expires {expiry.text}
              </Badge>
            ) : expiry?.expired && a.status === "pending" ? (
              <Badge tone="neutral" icon={<Clock className="h-3 w-3" aria-hidden />}>
                expired
              </Badge>
            ) : null}
            <Badge size="sm">requires {a.required_permission}</Badge>
          </div>

          {decision ? (
            <div className="rounded-md border border-accent/40 bg-accent/5 p-3">
              <p className="text-sm font-medium text-fg">Decision recorded: {titleCase(decision.status)}</p>
              {decision.execution ? <JsonViewer value={decision.execution} title="Execution result" collapsed className="mt-2" maxHeight="16rem" /> : null}
            </div>
          ) : null}

          {a.status !== "pending" ? (
            <KeyValueList
              dense
              className="rounded-md border border-border bg-surface-2/60 p-3"
              items={[
                { label: "Reviewer", value: a.reviewer_name ?? a.reviewer_id ?? "—" },
                { label: "Decided", value: a.decided_at ? <span title={fmtDateTime(a.decided_at)}>{fmtRelative(a.decided_at)}</span> : "—" },
                { label: "Decision note", value: a.decision_note ?? "—", wide: true },
                { label: "Executed", value: a.executed_at ? <span title={fmtDateTime(a.executed_at)}>{fmtRelative(a.executed_at)}</span> : "—" },
              ]}
            />
          ) : null}

          {contextValue(context, "summary") ? <p className="rounded-md border border-border bg-surface-2/60 px-3 py-2 text-sm text-fg">{contextValue(context, "summary")}</p> : null}

          <div>
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">Exact action payload</h4>
            <JsonViewer value={a.action_payload} maxHeight="20rem" title={a.tool_key ?? "payload"} />
            <div className="mt-2 flex items-center gap-1 text-xs text-fg-muted">
              <ShieldCheck className="h-3.5 w-3.5 text-success" aria-hidden />
              <span>payload hash</span>
              <code className="truncate font-mono text-[11px] text-fg" title={a.payload_hash}>
                {a.payload_hash}
              </code>
              <CopyButton value={a.payload_hash} label="Copy payload hash" />
            </div>
            <p className="text-[11px] text-fg-subtle">If the payload changes before you decide, your decision is rejected.</p>
          </div>

          <KeyValueList
            dense
            columns={2}
            items={[
              { label: "Agent", value: a.agent_key ? <a href={`/agents/${a.agent_key}`} className="text-accent hover:underline">{titleCase(a.agent_key)}</a> : "—" },
              { label: "Tool", value: a.tool_key ?? "—", mono: true },
              { label: "Node", value: a.node_key ?? "—", mono: true },
              { label: "Policy", value: a.policy_id ? `${a.policy_id} · ${a.policy_version ?? ""}` : "—", mono: true },
              { label: "Reason", value: a.reason ?? "—", wide: true },
              { label: "Agent reason", value: contextValue(context, "agent_reason") ?? "—", wide: true },
              { label: "Requested by", value: a.requested_by ?? "—", mono: true },
              { label: "Expires", value: fmtDateTime(a.expires_at) },
            ]}
          />

          <div>
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">Evidence</h4>
            <ChipList items={a.evidence} empty="No evidence references" />
          </div>

          {inputPreview ? (
            <div>
              <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-fg-muted">Input preview</h4>
              <JsonViewer value={inputPreview} collapsed maxHeight="16rem" title="input_preview" />
            </div>
          ) : null}

          {a.execution_result && !decision ? <JsonViewer value={a.execution_result} title="Execution result" collapsed maxHeight="16rem" /> : null}

          <div className="flex flex-wrap gap-2">
            {runId ? (
              <ButtonLink href={`/workflows/${runId}`} size="sm" variant="outline" leftIcon={<ArrowUpRight className="h-3.5 w-3.5" aria-hidden />}>
                Open workflow run
              </ButtonLink>
            ) : null}
            {a.agent_run_id ? <Badge size="sm">agent run {a.agent_run_id.slice(0, 8)}</Badge> : null}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => !open && setConfirm(null)}
        title={confirm === "approve" ? "Approve and execute this action?" : "Reject this action?"}
        description={confirm === "approve" ? `${a?.tool_key ?? "The tool"} will run exactly once with the payload shown. This cannot be undone.` : "The agent's proposed action will be discarded and the workflow resumes without it."}
        confirmLabel={confirm === "approve" ? "Approve" : "Reject"}
        tone={confirm === "approve" ? "primary" : "danger"}
        loading={decide.isPending}
        onConfirm={() => {
          if (confirm === "reject" && !note.trim()) {
            toast.error("A note is required to reject");
            return;
          }
          if (confirm) decide.mutate(confirm);
        }}
      >
        {confirm === "reject" && !note.trim() ? <p className="text-xs text-danger">Add a reviewer note before rejecting.</p> : null}
      </ConfirmDialog>
    </Sheet>
  );
}
