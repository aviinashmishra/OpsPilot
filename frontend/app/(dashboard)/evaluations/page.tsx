"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, FlaskConical, Play } from "lucide-react";
import Link from "next/link";
import { Fragment, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { Tip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import { useAgents, useEvaluations } from "@/lib/queries";
import type { EvaluationResultOut } from "@/lib/types";
import { cn, fmtCurrency, fmtDateTime, fmtMs, fmtPercent, fmtRelative, titleCase } from "@/lib/utils";

export default function EvaluationsPage() {
  const evaluations = useEvaluations();
  const agents = useAgents({}, { staleTime: 5 * 60_000 });
  const canAdmin = usePermission("agents:admin");
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [confirmAll, setConfirmAll] = useState(false);

  const rows = useMemo(() => {
    const byAgent = new Map((evaluations.data ?? []).map((e) => [e.agent_key, e]));
    const agentList = agents.data ?? [];
    const known = new Set(agentList.map((a) => a.agent_key));
    const merged = agentList.map((a) => ({ key: a.agent_key, name: a.name, department: a.department_label, evaluation: byAgent.get(a.agent_key) ?? null }));
    for (const e of evaluations.data ?? []) {
      if (!known.has(e.agent_key)) merged.push({ key: e.agent_key, name: titleCase(e.agent_key), department: "", evaluation: e });
    }
    return merged.sort((a, b) => a.name.localeCompare(b.name));
  }, [evaluations.data, agents.data]);

  const runOne = useMutation({
    mutationFn: (agentKey: string) => api<EvaluationResultOut>("/evaluations/run", { method: "POST", body: { agent_key: agentKey } }),
    onSuccess: (result) => {
      toast[result.passed ? "success" : "warning"](`${titleCase(result.agent_key)}: ${result.passed ? "passed" : "failing cases"}`, { description: `${result.metrics.passed ?? 0}/${result.metrics.cases ?? 0} cases passed` });
      void queryClient.invalidateQueries({ queryKey: ["evaluations"] });
      void queryClient.invalidateQueries({ queryKey: ["agent", result.agent_key] });
    },
    onError: (error) => toast.error("Evaluation failed", { description: errorMessage(error) }),
  });

  const runAll = useMutation({
    mutationFn: () => api<EvaluationResultOut[]>("/evaluations/run-all", { method: "POST" }),
    onSuccess: (results) => {
      const passed = results.filter((r) => r.passed).length;
      toast[passed === results.length ? "success" : "warning"](`Evaluated ${results.length} agents`, { description: `${passed} passed, ${results.length - passed} with failing cases` });
      void queryClient.invalidateQueries({ queryKey: ["evaluations"] });
      void queryClient.invalidateQueries({ queryKey: ["agent"] });
      setConfirmAll(false);
    },
    onError: (error) => toast.error("Run-all failed", { description: errorMessage(error) }),
  });

  const passedCount = (evaluations.data ?? []).filter((e) => e.passed).length;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Evaluations"
        badge={evaluations.data ? <Badge tone={passedCount === evaluations.data.length ? "success" : "warning"}>{passedCount} / {evaluations.data.length} passing</Badge> : undefined}
        actions={
          <Button variant="primary" onClick={() => setConfirmAll(true)} disabled={!canAdmin} loading={runAll.isPending} leftIcon={<FlaskConical className="h-4 w-4" aria-hidden />}>
            Run all
          </Button>
        }
      />
      {evaluations.isError ? <ErrorState error={evaluations.error} onRetry={() => evaluations.refetch()} /> : null}
      {evaluations.isLoading || agents.isLoading ? (
        <SkeletonRows rows={10} />
      ) : rows.length === 0 ? (
        <EmptyState icon={FlaskConical} title="No evaluations yet" />
      ) : (
        <TableWrap>
          <Table className="min-w-[1000px]">
            <THead>
              <TR>
                <TH className="w-8">
                  <span className="sr-only">Expand</span>
                </TH>
                <TH>Agent</TH>
                <TH>Result</TH>
                <TH align="right">Accuracy</TH>
                <TH align="right">Cases</TH>
                <TH align="right">Unsupported claims</TH>
                <TH align="right">Intervention</TH>
                <TH align="right">p50 / p95</TH>
                <TH align="right">Cost / case</TH>
                <TH>Last run</TH>
                <TH align="right">
                  <span className="sr-only">Actions</span>
                </TH>
              </TR>
            </THead>
            <TBody>
              {rows.map((row) => {
                const e = row.evaluation;
                const open = expanded === row.key;
                return (
                  <Fragment key={row.key}>
                    <TR interactive={Boolean(e)} onClick={() => e && setExpanded(open ? null : row.key)} aria-expanded={e ? open : undefined}>
                      <TD>{e ? <ChevronDown className={cn("h-4 w-4 text-fg-subtle transition-transform", open && "rotate-180")} aria-hidden /> : null}</TD>
                      <TD onClick={(ev) => ev.stopPropagation()}>
                        <Link href={`/agents/${row.key}`} className="font-medium text-fg hover:underline">
                          {row.name}
                        </Link>
                        <span className="block text-xs text-fg-subtle">
                          {row.department}
                          {e ? ` · v${e.agent_version}` : ""}
                          {e?.model ? ` · ${e.model}` : ""}
                        </span>
                      </TD>
                      <TD>{e ? <StatusPill status={e.passed ? "passed" : "failed"} size="sm" label={e.passed ? "Passed" : "Failing"} /> : <span className="text-xs text-fg-subtle">not evaluated</span>}</TD>
                      <TD align="right">{e ? fmtPercent(e.metrics.accuracy ?? null, 0) : "—"}</TD>
                      <TD align="right">{e ? `${e.metrics.passed ?? 0} / ${e.metrics.cases ?? 0}` : "—"}</TD>
                      <TD align="right">{e ? fmtPercent(e.metrics.unsupported_claim_rate ?? null, 0) : "—"}</TD>
                      <TD align="right">{e ? fmtPercent(e.metrics.human_intervention_rate ?? null, 0) : "—"}</TD>
                      <TD align="right">{e ? `${fmtMs(e.metrics.p50_latency_ms ?? null)} / ${fmtMs(e.metrics.p95_latency_ms ?? null)}` : "—"}</TD>
                      <TD align="right">{e ? fmtCurrency(e.metrics.cost_per_case_usd ?? null) : "—"}</TD>
                      <TD>
                        {e ? (
                          <Tip content={fmtDateTime(e.created_at)}>
                            <time dateTime={e.created_at} className="text-fg-muted">
                              {fmtRelative(e.created_at)}
                            </time>
                          </Tip>
                        ) : (
                          "—"
                        )}
                      </TD>
                      <TD align="right" onClick={(ev) => ev.stopPropagation()}>
                        <Button size="xs" variant="outline" disabled={!canAdmin} loading={runOne.isPending && runOne.variables === row.key} onClick={() => runOne.mutate(row.key)} leftIcon={<Play className="h-3 w-3" aria-hidden />}>
                          Run
                        </Button>
                      </TD>
                    </TR>
                    {open && e ? (
                      <TR>
                        <TD colSpan={11} className="bg-surface-2/40">
                          <ul className="space-y-2 py-2">
                            {e.case_results.map((c, i) => (
                              <li key={`${c.name}-${i}`} className="rounded-md border border-border bg-surface p-3">
                                <div className="flex items-center gap-2">
                                  <StatusPill status={c.passed ? "passed" : "failed"} size="sm" />
                                  <span className="text-sm font-medium">{c.name}</span>
                                </div>
                                {c.checks.length > 0 ? (
                                  <ul className="mt-2 space-y-1 text-xs">
                                    {c.checks.map((check, j) => (
                                      <li key={j} className="flex flex-wrap gap-x-2">
                                        <span className={check.passed ? "text-success" : "text-danger"}>{check.passed ? "✓" : "✗"}</span>
                                        <code className="font-mono">{check.check}</code>
                                        <span className="text-fg-muted">expected {JSON.stringify(check.expected)}</span>
                                        <span className="text-fg-muted">got {JSON.stringify(check.actual)}</span>
                                      </li>
                                    ))}
                                  </ul>
                                ) : null}
                              </li>
                            ))}
                          </ul>
                        </TD>
                      </TR>
                    ) : null}
                  </Fragment>
                );
              })}
            </TBody>
          </Table>
        </TableWrap>
      )}
      <ConfirmDialog open={confirmAll} onOpenChange={setConfirmAll} title="Run evaluations for all agents?" description="Runs every agent's test dataset. This can take a while." confirmLabel="Run all" loading={runAll.isPending} onConfirm={() => runAll.mutate()} />
    </div>
  );
}
