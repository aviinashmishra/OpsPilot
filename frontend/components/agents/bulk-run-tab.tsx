"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Ban, CheckCircle2, ChevronDown, FileSpreadsheet, Gauge, Hourglass, Layers, ListChecks, Play, RotateCcw, Timer, XCircle } from "lucide-react";
import Link from "next/link";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Badge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardToolbar } from "@/components/ui/card";
import { CopyableId } from "@/components/ui/copy-button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/input";
import { JsonEditor } from "@/components/ui/json-editor";
import { JsonViewer } from "@/components/ui/json-viewer";
import { Meter, Segmented } from "@/components/ui/misc";
import { Pagination } from "@/components/ui/pagination";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Switch } from "@/components/ui/switch";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { api, errorMessage, isApiError } from "@/lib/api";
import { csvToObjects } from "@/lib/csv";
import { useTick } from "@/lib/hooks";
import { qk, useBatch, useBatches } from "@/lib/queries";
import { schemaDefaults } from "@/lib/schema-defaults";
import type { AgentDetailOut, BatchDetailOut, BatchIn, BatchOut, JsonObject, JsonSchema } from "@/lib/types";
import { cn, fmtCurrency, fmtDateTime, fmtInt, fmtMs, fmtNumber, fmtRelative, isPlainObject, prettyJson, safeJsonParse } from "@/lib/utils";

const MAX_ITEMS = 5000;
const ITEMS_PAGE = 25;
const ITEM_STATUSES = ["queued", "running", "completed", "needs_review", "failed", "cancelled"] as const;

type InputMode = "json" | "csv";

/** If the agent takes a single required object (e.g. `{ lead: {...} }`), CSV rows are wrapped in it by default. */
function detectWrapKey(schema: JsonSchema): string {
  const required = schema.required ?? [];
  if (required.length !== 1) return "";
  const prop = schema.properties?.[required[0]];
  if (!prop) return "";
  const type = Array.isArray(prop.type) ? prop.type : [prop.type];
  return type.includes("object") || prop.$ref ? required[0] : "";
}

function personalize(value: unknown, n: number): unknown {
  if (typeof value === "string") {
    if (value === "") return `Sample ${n}`;
    if (value.includes("@")) return value.replace("@", `+${n}@`);
    return value;
  }
  if (Array.isArray(value)) return value.map((v) => personalize(v, n));
  if (isPlainObject(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) return { name: `Sample ${n}`, email: `sample${n}@example.test` };
    return Object.fromEntries(entries.map(([k, v]) => [k, personalize(v, n)]));
  }
  return value;
}

function exampleItems(agent: AgentDetailOut): JsonObject[] {
  const base = agent.example_input ?? schemaDefaults(agent.input_schema);
  return [1, 2, 3].map((n) => personalize(JSON.parse(JSON.stringify(base)) as unknown, n) as JsonObject);
}

interface ParsedItems {
  items: JsonObject[];
  error: string | null;
}

function parseJsonItems(text: string): ParsedItems {
  if (!text.trim()) return { items: [], error: null };
  const parsed = safeJsonParse(text);
  if (!parsed.ok) return { items: [], error: parsed.error };
  const value = parsed.value;
  if (!Array.isArray(value)) return { items: [], error: "Provide a JSON array of input objects, e.g. [{…}, {…}]" };
  const bad = value.findIndex((v) => !isPlainObject(v));
  if (bad >= 0) return { items: [], error: `Item ${bad + 1} is not a JSON object` };
  return { items: value as JsonObject[], error: null };
}

function BatchProgress({ batch, onCancel, cancelling }: { batch: BatchOut; onCancel: () => void; cancelling: boolean }) {
  useTick(1000);
  const running = batch.status === "running";
  const elapsed = batch.elapsed_seconds ?? 0;
  const throughput = elapsed > 0 ? batch.processed / elapsed : null;
  const remaining = Math.max(0, batch.total - batch.processed);
  const eta = running && throughput && throughput > 0 ? remaining / throughput : null;
  const tiles = [
    { label: "Succeeded", value: batch.succeeded, icon: CheckCircle2, cls: "text-success" },
    { label: "Needs review", value: batch.needs_review, icon: Hourglass, cls: "text-warning" },
    { label: "Failed", value: batch.failed, icon: XCircle, cls: "text-danger" },
    { label: "Remaining", value: remaining, icon: Layers, cls: "text-fg-muted" },
  ];
  return (
    <div className="space-y-4" data-testid="batch-progress" data-status={batch.status}>
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill status={batch.status} />
        <span className="text-sm font-medium text-fg">{batch.name}</span>
        <span className="text-xs text-fg-subtle" title={fmtDateTime(batch.created_at)}>
          started {fmtRelative(batch.created_at)}
        </span>
        <span className="ml-auto flex items-center gap-2">
          <CopyableId value={batch.id} />
          {running ? (
            <Button variant="danger" size="xs" onClick={onCancel} loading={cancelling} leftIcon={<Ban className="h-3 w-3" aria-hidden />}>
              Cancel
            </Button>
          ) : null}
        </span>
      </div>
      <Meter value={batch.processed} max={batch.total} label={<span className="tabular">{`${fmtInt(batch.processed)} of ${fmtInt(batch.total)} processed`}</span>} tone={batch.failed > 0 && !running ? "warning" : "accent"} />
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-lg border border-border bg-surface-2/50 px-3 py-2">
            <dt className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-fg-subtle">
              <t.icon className={cn("h-3 w-3", t.cls)} aria-hidden /> {t.label}
            </dt>
            <dd className="mt-0.5 text-xl font-semibold text-fg tabular">{fmtInt(t.value)}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-fg-muted">
        <span className="inline-flex items-center gap-1">
          <Timer className="h-3.5 w-3.5 text-fg-subtle" aria-hidden /> Elapsed <span className="text-fg tabular">{fmtMs(elapsed * 1000)}</span>
        </span>
        <span className="inline-flex items-center gap-1">
          <Gauge className="h-3.5 w-3.5 text-fg-subtle" aria-hidden /> Throughput <span className="text-fg tabular">{throughput === null ? "—" : `${fmtNumber(throughput, 2)} items/s`}</span>
        </span>
        {eta !== null ? (
          <span>
            ETA <span className="text-fg tabular">{fmtMs(eta * 1000)}</span>
          </span>
        ) : null}
        <span>
          Cost <span className="text-fg tabular">{fmtCurrency(batch.cost_usd)}</span>
        </span>
        <span>{batch.execute_actions ? "Actions executed through the policy engine" : "Dry run — actions proposed only"}</span>
      </div>
    </div>
  );
}

function BatchItems({ batch, agentKey, status, onStatus, offset, onOffset, fetching }: { batch: BatchDetailOut; agentKey: string; status: string; onStatus: (s: string) => void; offset: number; onOffset: (o: number) => void; fetching: boolean }) {
  const [openRow, setOpenRow] = useState<number | null>(null);
  const totalForFilter =
    status === ""
      ? batch.total
      : status === "completed"
        ? batch.succeeded
        : status === "needs_review"
          ? batch.needs_review
          : status === "failed"
            ? batch.failed
            : // queued / running / cancelled are not counted separately; paginate by what came back
              batch.items_offset + batch.items.length + (batch.items.length === ITEMS_PAGE ? ITEMS_PAGE : 0);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-fg-muted">Items</h4>
        <label className="ml-auto flex items-center gap-2 text-xs text-fg-muted">
          Status
          <NativeSelect value={status} onChange={(e) => onStatus(e.target.value)} className="h-8 w-40 text-xs" aria-label="Filter items by status">
            <option value="">All items</option>
            {ITEM_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ")}
              </option>
            ))}
          </NativeSelect>
        </label>
      </div>
      {batch.items.length === 0 ? (
        <EmptyState compact icon={ListChecks} title={status ? `No ${status.replace(/_/g, " ")} items` : "No items yet"} />
      ) : (
        <TableWrap className={cn(fetching && "opacity-80")}>
          <Table className="min-w-[760px]">
            <THead>
              <TR>
                <TH className="w-12">#</TH>
                <TH className="w-36">Status</TH>
                <TH>Result</TH>
                <TH align="right" className="w-24">
                  Latency
                </TH>
                <TH className="w-56">Links</TH>
                <TH className="w-10">
                  <span className="sr-only">Input</span>
                </TH>
              </TR>
            </THead>
            <TBody>
              {batch.items.map((item) => (
                <Fragment key={item.index}>
                  <TR>
                    <TD className="text-fg-subtle tabular">{item.index + 1}</TD>
                    <TD>
                      <StatusPill status={item.status} size="sm" />
                    </TD>
                    <TD className="max-w-[420px]">
                      {item.error ? <p className="line-clamp-2 text-xs text-danger">{item.error}</p> : item.summary ? <p className="line-clamp-2 text-xs text-fg-muted">{item.summary}</p> : <span className="text-xs text-fg-subtle">—</span>}
                    </TD>
                    <TD align="right" className="text-xs text-fg-muted">
                      {fmtMs(item.latency_ms)}
                    </TD>
                    <TD>
                      <div className="flex flex-col gap-0.5 text-xs">
                        {item.approval_ids.map((id) => (
                          <Link key={id} href={`/approvals?id=${encodeURIComponent(id)}`} className="inline-flex items-center gap-1 text-warning hover:underline">
                            Review approval {id.slice(0, 8)} <ArrowUpRight className="h-3 w-3" aria-hidden />
                          </Link>
                        ))}
                        {item.agent_run_id ? (
                          <Link href={`/agents/${encodeURIComponent(agentKey)}?tab=runs`} className="inline-flex items-center gap-1 text-accent hover:underline" title={item.agent_run_id}>
                            Agent run {item.agent_run_id.slice(0, 8)} <ArrowUpRight className="h-3 w-3" aria-hidden />
                          </Link>
                        ) : null}
                        {item.approval_ids.length === 0 && !item.agent_run_id ? <span className="text-fg-subtle">—</span> : null}
                      </div>
                    </TD>
                    <TD>
                      <Button variant="ghost" size="icon-sm" onClick={() => setOpenRow(openRow === item.index ? null : item.index)} aria-expanded={openRow === item.index} aria-label={`Show input of item ${item.index + 1}`}>
                        <ChevronDown className={cn("h-4 w-4 transition-transform", openRow === item.index && "rotate-180")} aria-hidden />
                      </Button>
                    </TD>
                  </TR>
                  {openRow === item.index ? (
                    <TR>
                      <TD colSpan={6} className="bg-surface-2/40">
                        <JsonViewer value={item.input} title={`Input · item ${item.index + 1}`} maxHeight="14rem" />
                      </TD>
                    </TR>
                  ) : null}
                </Fragment>
              ))}
            </TBody>
          </Table>
        </TableWrap>
      )}
      <Pagination total={totalForFilter} limit={ITEMS_PAGE} offset={offset} onChange={onOffset} label="items" />
    </div>
  );
}

function RecentBatches({ agentKey, activeId, onOpen }: { agentKey: string; activeId: string | null; onOpen: (id: string) => void }) {
  const [offset, setOffset] = useState(0);
  const batches = useBatches({ agent_key: agentKey, limit: 10, offset });
  return (
    <Card>
      <CardToolbar title="Recent bulk runs" />
      <CardContent>
        {batches.isError ? (
          <ErrorState compact error={batches.error} onRetry={() => batches.refetch()} />
        ) : batches.isLoading ? (
          <SkeletonRows rows={3} />
        ) : !batches.data || batches.data.items.length === 0 ? (
          <EmptyState compact icon={Layers} title="No bulk runs yet" description="Paste a list of inputs above to run this agent over all of them." />
        ) : (
          <div className="space-y-3">
            <TableWrap>
              <Table className="min-w-[720px]">
                <THead>
                  <TR>
                    <TH>Batch</TH>
                    <TH>Status</TH>
                    <TH className="w-48">Progress</TH>
                    <TH align="right">OK / review / failed</TH>
                    <TH align="right">Elapsed</TH>
                    <TH>Started</TH>
                  </TR>
                </THead>
                <TBody>
                  {batches.data.items.map((b) => (
                    <TR key={b.id} className={cn("hover:bg-surface-2/70", b.id === activeId && "bg-accent/5")}>
                      <TD>
                        <button type="button" onClick={() => onOpen(b.id)} className="text-left font-medium text-fg hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
                          {b.name}
                        </button>
                        <span className="block font-mono text-[11px] text-fg-subtle">{b.id.slice(0, 8)}</span>
                      </TD>
                      <TD>
                        <StatusPill status={b.status} size="sm" />
                      </TD>
                      <TD>
                        <div className="flex items-center gap-2">
                          <Meter value={b.processed} max={b.total} className="flex-1" />
                          <span className="w-16 text-right text-xs text-fg-muted tabular">
                            {fmtInt(b.processed)}/{fmtInt(b.total)}
                          </span>
                        </div>
                      </TD>
                      <TD align="right" className="text-xs">
                        <span className="text-success">{fmtInt(b.succeeded)}</span> / <span className="text-warning">{fmtInt(b.needs_review)}</span> / <span className="text-danger">{fmtInt(b.failed)}</span>
                      </TD>
                      <TD align="right" className="text-xs text-fg-muted">
                        {b.elapsed_seconds === null ? "—" : fmtMs(b.elapsed_seconds * 1000)}
                      </TD>
                      <TD className="text-xs text-fg-muted" title={fmtDateTime(b.created_at)}>
                        {fmtRelative(b.created_at)}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </TableWrap>
            <Pagination total={batches.data.total} limit={batches.data.limit} offset={batches.data.offset} onChange={setOffset} label="batches" />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function BulkRunTab({ agent, canRun }: { agent: AgentDetailOut; canRun: boolean }) {
  const queryClient = useQueryClient();
  const example = useMemo(() => prettyJson(exampleItems(agent)), [agent]);
  const defaultWrap = useMemo(() => detectWrapKey(agent.input_schema), [agent.input_schema]);
  const [mode, setMode] = useState<InputMode>("json");
  const [jsonText, setJsonText] = useState(example);
  const [csvText, setCsvText] = useState("");
  const [wrapKey, setWrapKey] = useState(defaultWrap);
  const [name, setName] = useState("");
  const [executeActions, setExecuteActions] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [itemStatus, setItemStatus] = useState("");
  const [itemOffset, setItemOffset] = useState(0);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [serverErrors, setServerErrors] = useState<Array<{ index: number; error: string }>>([]);
  const progressRef = useRef<HTMLDivElement>(null);

  const parsed: ParsedItems = useMemo(() => {
    if (mode === "json") return parseJsonItems(jsonText);
    const res = csvToObjects(csvText, wrapKey);
    return { items: res.items as JsonObject[], error: res.error };
  }, [mode, jsonText, csvText, wrapKey]);
  const count = parsed.items.length;
  const tooMany = count > MAX_ITEMS;
  const valid = !parsed.error && count > 0 && !tooMany;

  const batch = useBatch(activeId, { status: itemStatus || undefined, limit: ITEMS_PAGE, offset: itemOffset });

  const wasRunning = useRef(false);
  useEffect(() => {
    const running = batch.data?.status === "running";
    if (wasRunning.current && !running && batch.data) {
      toast.success(`Bulk run ${batch.data.status}`, { description: `${batch.data.succeeded} succeeded · ${batch.data.needs_review} need review · ${batch.data.failed} failed` });
      void queryClient.invalidateQueries({ queryKey: ["batches"] });
      void queryClient.invalidateQueries({ queryKey: ["agent", agent.agent_key] });
      void queryClient.invalidateQueries({ queryKey: ["agent-runs", agent.agent_key] });
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
    }
    wasRunning.current = running;
  }, [batch.data, queryClient, agent.agent_key]);

  const start = useMutation({
    mutationFn: () => {
      const body: BatchIn = { items: parsed.items, name: name.trim() || null, execute_actions: executeActions };
      return api<BatchOut>(`/agents/${encodeURIComponent(agent.agent_key)}/batches`, { method: "POST", body });
    },
    onSuccess: (created) => {
      setServerErrors([]);
      setItemStatus("");
      setItemOffset(0);
      queryClient.setQueryData(qk.batch(created.id, { limit: ITEMS_PAGE, offset: 0 }), { ...created, items: [], items_limit: ITEMS_PAGE, items_offset: 0 } satisfies BatchDetailOut);
      setActiveId(created.id);
      wasRunning.current = created.status === "running";
      toast.success(`Bulk run started · ${fmtInt(created.total)} items`);
      void queryClient.invalidateQueries({ queryKey: ["batches"] });
      window.setTimeout(() => progressRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    },
    onError: (error) => {
      const details = isApiError(error) && Array.isArray(error.details.errors) ? (error.details.errors as Array<{ index?: number; error?: string }>) : [];
      setServerErrors(details.filter((d) => typeof d.index === "number").map((d) => ({ index: d.index as number, error: String(d.error ?? "invalid") })));
      toast.error("Could not start the bulk run", { description: errorMessage(error) });
    },
  });

  const cancel = useMutation({
    mutationFn: (id: string) => api<BatchOut>(`/batches/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
    onSuccess: () => {
      toast.success("Remaining items cancelled");
      setConfirmCancel(false);
      void queryClient.invalidateQueries({ queryKey: ["batch"] });
      void queryClient.invalidateQueries({ queryKey: ["batches"] });
    },
    onError: (error) => toast.error("Could not cancel", { description: errorMessage(error) }),
  });

  const reset = () => {
    if (mode === "json") setJsonText(example);
    else setCsvText("");
    setServerErrors([]);
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardToolbar
            title="Inputs"
            description="One run per item."
            actions={
              <Segmented<InputMode>
                aria-label="Input format"
                value={mode}
                onChange={setMode}
                options={[
                  { value: "json", label: "JSON array" },
                  { value: "csv", label: "CSV" },
                ]}
              />
            }
          />
          <CardContent className="space-y-3">
            {mode === "json" ? (
              <JsonEditor label="Items (JSON array)" value={jsonText} onChange={setJsonText} rows={14} placeholder="[{…}, {…}]" />
            ) : (
              <div className="space-y-3">
                <Field label="CSV (header row first)" htmlFor="bulk-csv" hint="Dotted headers like lead.email create nested fields.">
                  <Textarea
                    id="bulk-csv"
                    rows={10}
                    value={csvText}
                    onChange={(e) => setCsvText(e.target.value)}
                    spellCheck={false}
                    className="font-mono text-[12px]"
                    placeholder={"name,email,company,budget,timeline\nAda Lovelace,ada@example.test,Analytical Engines,50000,this quarter\nGrace Hopper,grace@example.test,Compilers Inc,120000,next month"}
                  />
                </Field>
                <Field label="Wrap each row as" htmlFor="bulk-wrap" hint={wrapKey ? `Each row becomes { "${wrapKey}": { …columns } }.` : "Leave empty to use each row's columns as the top-level input fields."}>
                  <Input id="bulk-wrap" value={wrapKey} onChange={(e) => setWrapKey(e.target.value.replace(/[^A-Za-z0-9_]/g, ""))} placeholder="e.g. lead" className="max-w-xs font-mono" />
                </Field>
              </div>
            )}
            <div role="status" aria-live="polite" className={cn("flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-xs", parsed.error || tooMany ? "border-danger/40 bg-danger/10 text-danger" : count > 0 ? "border-success/35 bg-success/10 text-success" : "border-border bg-surface-2/50 text-fg-muted")} data-testid="bulk-item-count">
              {parsed.error ? (
                <>
                  <XCircle className="h-3.5 w-3.5" aria-hidden /> {parsed.error}
                </>
              ) : tooMany ? (
                <>
                  <XCircle className="h-3.5 w-3.5" aria-hidden /> {fmtInt(count)} items — at most {fmtInt(MAX_ITEMS)} per bulk run
                </>
              ) : count > 0 ? (
                <>
                  <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> {fmtInt(count)} item{count === 1 ? "" : "s"} ready
                </>
              ) : (
                <>
                  <FileSpreadsheet className="h-3.5 w-3.5" aria-hidden /> No items yet
                </>
              )}
            </div>
            {serverErrors.length > 0 ? (
              <div role="alert" className="rounded-md border border-danger/40 bg-danger/5 px-3 py-2 text-xs">
                <p className="font-medium text-danger">These items don&apos;t match the agent&apos;s input schema:</p>
                <ul className="mt-1 space-y-0.5 text-fg-muted">
                  {serverErrors.map((e) => (
                    <li key={e.index}>
                      <span className="font-mono text-fg">#{e.index + 1}</span> {e.error}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {mode === "csv" && count > 0 && !parsed.error ? <JsonViewer value={parsed.items[0]} title="Preview · first item" collapsed maxHeight="10rem" /> : null}
          </CardContent>
        </Card>

        <Card className="xl:col-span-2">
          <CardToolbar title="Run settings" />
          <CardContent className="space-y-4">
            <Field label="Name (optional)" htmlFor="bulk-name">
              <Input id="bulk-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={`${agent.name} × ${count || "N"}`} maxLength={200} />
            </Field>
            <label className="flex items-start justify-between gap-3 rounded-md border border-border bg-surface-2/50 px-3 py-2.5">
              <span>
                <span className="block text-sm font-medium text-fg">Execute actions</span>
                <span className="block text-xs text-fg-muted">Off = dry run. Consequential actions still need approval.</span>
              </span>
              <Switch checked={executeActions} onCheckedChange={setExecuteActions} aria-label="Execute actions" />
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="primary" onClick={() => start.mutate()} loading={start.isPending} disabled={!canRun || !valid || !agent.enabled} leftIcon={<Play className="h-4 w-4" aria-hidden />}>
                Start bulk run{count > 0 && valid ? ` · ${fmtInt(count)}` : ""}
              </Button>
              <Button variant="ghost" onClick={reset} leftIcon={<RotateCcw className="h-4 w-4" aria-hidden />}>
                Reset
              </Button>
            </div>
            {!canRun ? <p className="text-xs text-fg-subtle">Requires agents:run</p> : !agent.enabled ? <p className="text-xs text-danger">Agent is disabled</p> : null}
            <p className="text-xs text-fg-subtle">Up to {fmtInt(MAX_ITEMS)} items. A failed item doesn&apos;t stop the batch.</p>
          </CardContent>
        </Card>
      </div>

      {activeId ? (
        <div ref={progressRef} className="scroll-mt-20">
          <Card>
            <CardToolbar title="Live progress" description={batch.data?.status === "running" ? "Refreshing every 1.5 s" : batch.data ? `Finished ${fmtRelative(batch.data.finished_at)}` : undefined} actions={<Badge size="sm">{agent.agent_key}</Badge>} />
            <CardContent className="space-y-5">
              {batch.isError ? (
                <ErrorState compact error={batch.error} onRetry={() => batch.refetch()} />
              ) : !batch.data ? (
                <SkeletonRows rows={4} />
              ) : (
                <>
                  <BatchProgress batch={batch.data} onCancel={() => setConfirmCancel(true)} cancelling={cancel.isPending} />
                  <BatchItems
                    batch={batch.data}
                    agentKey={agent.agent_key}
                    status={itemStatus}
                    onStatus={(s) => {
                      setItemStatus(s);
                      setItemOffset(0);
                    }}
                    offset={itemOffset}
                    onOffset={setItemOffset}
                    fetching={batch.isFetching && batch.isPlaceholderData}
                  />
                </>
              )}
            </CardContent>
          </Card>
        </div>
      ) : null}

      <RecentBatches
        agentKey={agent.agent_key}
        activeId={activeId}
        onOpen={(id) => {
          setActiveId(id);
          setItemStatus("");
          setItemOffset(0);
          window.setTimeout(() => progressRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
        }}
      />

      <ConfirmDialog
        open={confirmCancel}
        onOpenChange={setConfirmCancel}
        title="Cancel the remaining items?"
        description="Items that are already running finish normally; queued items are marked cancelled. Completed results are kept."
        confirmLabel="Cancel remaining"
        cancelLabel="Keep running"
        tone="danger"
        loading={cancel.isPending}
        onConfirm={() => activeId && cancel.mutate(activeId)}
      />
    </div>
  );
}
