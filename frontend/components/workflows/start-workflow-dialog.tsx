"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field } from "@/components/ui/input";
import { JsonEditor } from "@/components/ui/json-editor";
import { Select } from "@/components/ui/select";
import { InlineError } from "@/components/ui/states";
import { api, errorMessage, idempotencyKey } from "@/lib/api";
import { useWorkflowDefinitions } from "@/lib/queries";
import type { JsonObject, WorkflowDefinitionOut, WorkflowRunOut } from "@/lib/types";
import { useUi } from "@/lib/ui-store";
import { prettyJson, safeJsonParse } from "@/lib/utils";

/** Working example inputs for the built-in workflows, using the seeded demo data. */
export const WORKFLOW_EXAMPLES: Record<string, JsonObject> = {
  lead_to_crm: { lead: { name: "Ana Silva", email: "ana@globex.test", company: "Globex", title: "VP Operations", industry: "logistics", company_size: 900, budget: 80000, timeline: "this quarter", message: "We need to automate warehouse exception handling." } },
  meeting_to_tasks: {
    title: "Q4 launch planning",
    transcript: "Maya: We decided to move the launch to November 12.\nDana: Dana will send the updated pricing sheet to the sales team by Friday.\nChris: I'll have the API rate limiting done by Friday.\nDana: Open question: do we need legal review for the new terms?",
  },
  customer_query: { message: "Where is my order ORD-5002? It's late.", customer_id: "C-2003", order_id: "ORD-5002", channel: "email" },
  whatsapp_inbound: { phone: "+15550100123", message: "Where is my order ORD-5001?", profile_name: "Jordan" },
  invoice_to_review: { document_text: "Northwind Components\nInvoice No: NW-2026-201\nDate: 2026-10-01\nDue Date: 2026-10-31\nPO Number: PO-7001\nDriver units          400   12.00    4,800.00\nSubtotal: 4,800.00\nTax (0%): 0.00\nTotal Due: 4,800.00" },
  overdue_escalation: {},
  kpi_report: { period_days: 14, months: 3 },
  order_exception: { scan_all: true },
  release_watch: { service: "checkout-api", deployment_id: "DEP-301" },
  quote_to_po: { rfq_id: "RFQ-42" },
};

/** Pulls `$.input.<field>` references out of a graph to pre-fill the input editor. */
export function inputTemplateFromGraph(def: WorkflowDefinitionOut): JsonObject {
  const fields = new Set<string>();
  const walk = (value: unknown): void => {
    if (typeof value === "string") {
      const match = /^\$\.input\.([A-Za-z0-9_]+)/.exec(value);
      if (match) fields.add(match[1]);
      return;
    }
    if (Array.isArray(value)) value.forEach(walk);
    else if (value && typeof value === "object") Object.values(value).forEach(walk);
  };
  Object.values(def.graph.nodes).forEach((node) => walk(node.input));
  const template: JsonObject = {};
  fields.forEach((f) => {
    template[f] = f.endsWith("_ids") || f === "attendees" || f === "metrics" ? [] : f === "scan_all" ? false : f.endsWith("_days") || f === "months" ? 30 : "";
  });
  return template;
}

export function StartWorkflowDialog({ open, onOpenChange, initialKey }: { open: boolean; onOpenChange: (open: boolean) => void; initialKey?: string }) {
  const definitions = useWorkflowDefinitions({ enabled: open });
  const router = useRouter();
  const queryClient = useQueryClient();
  const [key, setKey] = useState(initialKey ?? "");
  const [input, setInput] = useState("{}");
  const [valid, setValid] = useState(true);

  const selectable = useMemo(() => (definitions.data ?? []).filter((d) => d.is_active && !d.key.startsWith("single_agent__")), [definitions.data]);
  const selected = selectable.find((d) => d.key === key) ?? null;

  useEffect(() => {
    if (open && initialKey) setKey(initialKey);
  }, [open, initialKey]);

  useEffect(() => {
    if (!key && selectable.length > 0) setKey(selectable[0].key);
  }, [key, selectable]);

  useEffect(() => {
    if (selected) setInput(prettyJson(WORKFLOW_EXAMPLES[selected.key] ?? inputTemplateFromGraph(selected)));
  }, [selected]);

  const start = useMutation({
    mutationFn: async () => {
      const parsed = safeJsonParse(input || "{}");
      if (!parsed.ok) throw new Error(parsed.error);
      return api<WorkflowRunOut>("/workflows", { method: "POST", body: { workflow_key: key, input: parsed.value }, headers: { "Idempotency-Key": idempotencyKey() } });
    },
    onSuccess: (run) => {
      toast.success("Workflow started", { description: `${run.workflow_key} · ${run.id.slice(0, 8)}` });
      void queryClient.invalidateQueries({ queryKey: ["workflows"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
      onOpenChange(false);
      router.push(`/workflows/${run.id}`);
    },
    onError: (error) => toast.error("Could not start workflow", { description: errorMessage(error) }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Start a workflow</DialogTitle>
          <DialogDescription>Consequential steps wait for approval.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <Field label="Workflow" htmlFor="wf-key" required>
            <Select id="wf-key" value={key} onValueChange={setKey} options={selectable.map((d) => ({ value: d.key, label: d.name, description: `${d.key} · v${d.version}` }))} placeholder={definitions.isLoading ? "Loading definitions…" : "Choose a workflow"} disabled={definitions.isLoading} />
          </Field>
          {selected ? (
            <div className="rounded-md border border-border bg-surface-2/60 p-3 text-xs text-fg-muted">
              <p>{selected.description}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge size="sm">{Object.keys(selected.graph.nodes).length} nodes</Badge>
                <Badge size="sm">timeout {selected.timeout_seconds}s</Badge>
                <Badge size="sm" tone={selected.scope === "platform" ? "accent" : "info"}>
                  {selected.scope}
                </Badge>
              </div>
            </div>
          ) : null}
          {definitions.isError ? <InlineError error={definitions.error} /> : null}
          <JsonEditor label="Input payload" value={input} onChange={setInput} onValidChange={setValid} rows={10} />
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => start.mutate()} loading={start.isPending} disabled={!key || !valid} leftIcon={<Play className="h-4 w-4" aria-hidden />}>
            Start run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Mounted once in the shell so the command palette can open it from anywhere. */
export function GlobalStartWorkflowDialog() {
  const open = useUi((s) => s.startWorkflowOpen);
  const setOpen = useUi((s) => s.setStartWorkflowOpen);
  return <StartWorkflowDialog open={open} onOpenChange={setOpen} />;
}
