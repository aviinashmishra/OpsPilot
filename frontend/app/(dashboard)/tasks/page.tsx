"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckSquare, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Badge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Pagination } from "@/components/ui/pagination";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Switch } from "@/components/ui/switch";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { Tip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { TASK_PRIORITIES, TASK_STATUSES } from "@/lib/constants";
import { useDebounced } from "@/lib/hooks";
import { usePermission } from "@/lib/permissions";
import { useTasks } from "@/lib/queries";
import type { TaskIn, TaskOut, TaskPriority, TaskStatus, TaskUpdateIn } from "@/lib/types";
import { fmtDateTime, fmtRelative, titleCase } from "@/lib/utils";

const PAGE = 50;
const PRIORITY_TONE: Record<string, "neutral" | "info" | "warning" | "danger"> = { low: "neutral", medium: "info", high: "warning", critical: "danger" };

export default function TasksPage() {
  const [status, setStatus] = useState("");
  const [overdue, setOverdue] = useState(false);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const q = useDebounced(search.trim(), 350);
  const canWrite = usePermission("tasks:write");
  const queryClient = useQueryClient();
  const tasks = useTasks({ status: status || undefined, overdue: overdue || undefined, q: q || undefined, limit: PAGE, offset });

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: TaskUpdateIn }) => api<TaskOut>(`/tasks/${id}`, { method: "PATCH", body }),
    onSuccess: (task) => {
      toast.success(`Task updated`, { description: `${task.title} → ${titleCase(task.status)}` });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (error) => toast.error("Could not update task", { description: errorMessage(error) }),
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Tasks"
        actions={
          <Button variant="primary" onClick={() => setCreateOpen(true)} disabled={!canWrite} leftIcon={<Plus className="h-4 w-4" aria-hidden />}>
            New task
          </Button>
        }
      />
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
        <div className="relative w-full sm:w-72">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
          <Input value={search} onChange={(e) => { setSearch(e.target.value); setOffset(0); }} placeholder="Search by title…" className="pl-8" aria-label="Search tasks" />
        </div>
        <NativeSelect value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} aria-label="Filter by status" className="w-full sm:w-44">
          <option value="">All statuses</option>
          {TASK_STATUSES.map((s) => (
            <option key={s} value={s}>
              {titleCase(s)}
            </option>
          ))}
        </NativeSelect>
        <label className="flex h-9 items-center gap-2 rounded-md border border-border bg-surface px-3 text-sm text-fg-muted">
          <Switch size="sm" checked={overdue} onCheckedChange={(c) => { setOverdue(c); setOffset(0); }} aria-label="Only overdue tasks" />
          Overdue only
        </label>
      </div>

      {tasks.isError ? <ErrorState error={tasks.error} onRetry={() => tasks.refetch()} /> : null}
      {tasks.isLoading ? (
        <SkeletonRows rows={8} />
      ) : tasks.data && tasks.data.items.length === 0 ? (
        <EmptyState icon={CheckSquare} title="No tasks" description={overdue ? "Nothing is overdue." : "Create a task or let an agent create one."} />
      ) : tasks.data ? (
        <>
          <TableWrap>
            <Table className="min-w-[960px]">
              <THead>
                <TR>
                  <TH>Task</TH>
                  <TH>Status</TH>
                  <TH>Priority</TH>
                  <TH>Owner</TH>
                  <TH>Due</TH>
                  <TH align="center">Escalation</TH>
                  <TH>Source</TH>
                  <TH>Evidence</TH>
                </TR>
              </THead>
              <TBody>
                {tasks.data.items.map((task) => (
                  <TR key={task.id}>
                    <TD className="max-w-[360px]">
                      <span className="font-medium text-fg">{task.title}</span>
                      {task.description ? <span className="mt-0.5 line-clamp-2 block whitespace-pre-line text-xs text-fg-muted">{task.description}</span> : null}
                      {task.labels.length > 0 ? (
                        <span className="mt-1 flex flex-wrap gap-1">
                          {task.labels.map((l) => (
                            <Badge key={l} size="sm">
                              {l}
                            </Badge>
                          ))}
                        </span>
                      ) : null}
                    </TD>
                    <TD>
                      {canWrite ? (
                        <NativeSelect value={task.status} onChange={(e) => update.mutate({ id: task.id, body: { status: e.target.value as TaskStatus } })} aria-label={`Status of ${task.title}`} className="h-8 w-36 text-xs">
                          {TASK_STATUSES.map((s) => (
                            <option key={s} value={s}>
                              {titleCase(s)}
                            </option>
                          ))}
                        </NativeSelect>
                      ) : (
                        <StatusPill status={task.status} size="sm" />
                      )}
                    </TD>
                    <TD>
                      <Badge size="sm" tone={PRIORITY_TONE[task.priority] ?? "neutral"}>
                        {titleCase(task.priority)}
                      </Badge>
                    </TD>
                    <TD className="text-fg-muted">{task.owner_name ?? <span className="text-fg-subtle">unassigned</span>}</TD>
                    <TD>
                      {task.due_at ? (
                        <Tip content={fmtDateTime(task.due_at)}>
                          <span className={task.overdue ? "inline-flex items-center gap-1 text-danger" : "text-fg-muted"}>
                            {task.overdue ? <AlertTriangle className="h-3 w-3" aria-hidden /> : null}
                            {fmtRelative(task.due_at)}
                            {task.overdue ? " (overdue)" : ""}
                          </span>
                        </Tip>
                      ) : (
                        <span className="text-fg-subtle">—</span>
                      )}
                    </TD>
                    <TD align="center">{task.escalation_level > 0 ? <Badge size="sm" tone="warning">L{task.escalation_level}</Badge> : <span className="text-fg-subtle">—</span>}</TD>
                    <TD className="text-xs text-fg-muted">
                      {task.source}
                      {task.source_run_id ? (
                        <Link href={`/workflows/${task.source_run_id}`} className="ml-1 text-accent hover:underline">
                          run
                        </Link>
                      ) : null}
                    </TD>
                    <TD>
                      {task.evidence_refs.length > 0 ? (
                        <Tip content={<ul className="space-y-0.5 font-mono text-[11px]">{task.evidence_refs.map((r) => <li key={r}>{r}</li>)}</ul>}>
                          <span className="cursor-help text-xs text-fg-muted underline decoration-dotted">{task.evidence_refs.length} ref{task.evidence_refs.length > 1 ? "s" : ""}</span>
                        </Tip>
                      ) : (
                        <span className="text-fg-subtle">—</span>
                      )}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </TableWrap>
          <Pagination total={tasks.data.total} limit={tasks.data.limit} offset={tasks.data.offset} onChange={setOffset} label="tasks" />
        </>
      ) : null}
      <CreateTaskDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}

function CreateTaskDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<TaskPriority>("medium");
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const [labels, setLabels] = useState("");

  const create = useMutation({
    mutationFn: () => {
      const body: TaskIn = {
        title: title.trim(),
        description: description.trim() || null,
        priority,
        owner_name: owner.trim() || null,
        due_at: due ? new Date(due).toISOString() : null,
        labels: labels
          .split(",")
          .map((l) => l.trim())
          .filter(Boolean),
      };
      return api<TaskOut>("/tasks", { method: "POST", body });
    },
    onSuccess: (task) => {
      toast.success("Task created", { description: task.title });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      onOpenChange(false);
      setTitle("");
      setDescription("");
      setPriority("medium");
      setOwner("");
      setDue("");
      setLabels("");
    },
    onError: (error) => toast.error("Could not create task", { description: errorMessage(error) }),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="flex min-h-0 flex-col">
          <DialogHeader>
            <DialogTitle>New task</DialogTitle>
            <DialogDescription>Manual tasks sit alongside agent-created work.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            <Field label="Title" htmlFor="task-title" required>
              <Input id="task-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} required />
            </Field>
            <Field label="Description" htmlFor="task-desc">
              <Textarea id="task-desc" value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Priority" htmlFor="task-priority">
                <NativeSelect id="task-priority" value={priority} onChange={(e) => setPriority(e.target.value as TaskPriority)}>
                  {TASK_PRIORITIES.map((p) => (
                    <option key={p} value={p}>
                      {titleCase(p)}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field label="Due" htmlFor="task-due">
                <Input id="task-due" type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} />
              </Field>
              <Field label="Owner name" htmlFor="task-owner">
                <Input id="task-owner" value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="e.g. Olive Operator" />
              </Field>
              <Field label="Labels" htmlFor="task-labels" hint="Comma separated">
                <Input id="task-labels" value={labels} onChange={(e) => setLabels(e.target.value)} placeholder="ops, follow-up" />
              </Field>
            </div>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" loading={create.isPending} disabled={!title.trim()}>
              Create task
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
