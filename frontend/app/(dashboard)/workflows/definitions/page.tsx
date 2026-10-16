"use client";

import { Play, Workflow } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button, ButtonLink } from "@/components/ui/button";
import { Card, CardContent, CardToolbar } from "@/components/ui/card";
import { JsonViewer } from "@/components/ui/json-viewer";
import { Collapsible } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonCards } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { StartWorkflowDialog } from "@/components/workflows/start-workflow-dialog";
import { WorkflowGraphView } from "@/components/workflows/workflow-graph";
import { usePermission } from "@/lib/permissions";
import { useWorkflowDefinitions } from "@/lib/queries";
import type { JsonObject, WorkflowDefinitionOut } from "@/lib/types";

function triggerSummary(trigger: JsonObject): string {
  const parts: string[] = [];
  if (Array.isArray(trigger.event_types)) parts.push(`events: ${(trigger.event_types as string[]).join(", ")}`);
  if (typeof trigger.schedule === "string") parts.push(`schedule: ${trigger.schedule}`);
  if (trigger.manual) parts.push("manual");
  return parts.join(" · ") || "manual";
}

function DefinitionCard({ def, onStart, canStart }: { def: WorkflowDefinitionOut; onStart: (key: string) => void; canStart: boolean }) {
  const agents = Object.values(def.graph.nodes)
    .filter((n) => n.type === "agent" && n.agent)
    .map((n) => n.agent as string);
  return (
    <Card>
      <CardToolbar
        title={def.name}
        description={def.description ?? undefined}
        actions={
          <Button size="sm" variant="primary" onClick={() => onStart(def.key)} disabled={!canStart || !def.is_active} leftIcon={<Play className="h-3.5 w-3.5" aria-hidden />}>
            Start
          </Button>
        }
      />
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-1.5">
          <Badge size="sm" tone="accent">
            {def.key}
          </Badge>
          <Badge size="sm">v{def.version}</Badge>
          <Badge size="sm" tone={def.scope === "platform" ? "info" : "neutral"}>
            {def.scope}
          </Badge>
          <Badge size="sm" tone={def.is_active ? "success" : "danger"}>
            {def.is_active ? "active" : "inactive"}
          </Badge>
          <Badge size="sm">timeout {def.timeout_seconds}s</Badge>
          <Badge size="sm">{Object.keys(def.graph.nodes).length} nodes</Badge>
        </div>
        <p className="text-xs text-fg-muted">Trigger: {triggerSummary(def.trigger)}</p>
        {agents.length > 0 ? <p className="text-xs text-fg-muted">Agents: {Array.from(new Set(agents)).join(", ")}</p> : null}
        <WorkflowGraphView graph={def.graph} height={240} interactive={false} />
        <Collapsible title={<span className="text-xs text-fg-muted">Graph JSON</span>} className="bg-transparent">
          <JsonViewer value={def.graph} collapsed />
        </Collapsible>
      </CardContent>
    </Card>
  );
}

export default function WorkflowDefinitionsPage() {
  const definitions = useWorkflowDefinitions();
  const canStart = usePermission("workflows:write");
  const [startKey, setStartKey] = useState<string | null>(null);
  const templates = (definitions.data ?? []).filter((d) => !d.key.startsWith("single_agent__"));
  const wrappers = (definitions.data ?? []).filter((d) => d.key.startsWith("single_agent__"));

  return (
    <div className="space-y-5">
      <PageHeader crumbs={[{ label: "Workflows", href: "/workflows" }, { label: "Definitions" }]} title="Workflow definitions" />
      {definitions.isError ? <ErrorState error={definitions.error} onRetry={() => definitions.refetch()} /> : null}
      {definitions.isLoading ? (
        <SkeletonCards count={4} className="lg:grid-cols-2" cardClassName="h-96" />
      ) : templates.length === 0 ? (
        <EmptyState icon={Workflow} title="No workflow definitions" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {templates.map((def) => (
            <DefinitionCard key={def.id} def={def} onStart={setStartKey} canStart={canStart} />
          ))}
        </div>
      )}
      {wrappers.length > 0 ? (
        <Collapsible title={<span className="text-sm font-medium">Auto-generated single-agent wrappers ({wrappers.length})</span>}>
          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {wrappers.map((def) => (
              <li key={def.id} className="flex items-center justify-between gap-2 rounded-md border border-border bg-surface-2/60 px-3 py-2 text-sm">
                <span className="min-w-0">
                  <span className="block truncate font-medium">{def.name}</span>
                  <span className="block truncate font-mono text-[11px] text-fg-subtle">{def.key}</span>
                </span>
                <ButtonLink size="xs" variant="outline" href={`/agents/${def.key.replace(/^single_agent__/, "")}?tab=playground`}>
                  Playground
                </ButtonLink>
              </li>
            ))}
          </ul>
        </Collapsible>
      ) : null}
      <StartWorkflowDialog open={startKey !== null} onOpenChange={(open) => !open && setStartKey(null)} initialKey={startKey ?? undefined} />
    </div>
  );
}
