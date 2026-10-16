"use client";

import { Bot, CheckSquare, Flag, GitBranch, Layers, Play, Workflow as WorkflowIcon, Wrench } from "lucide-react";
import { useMemo } from "react";
import ReactFlow, { Background, BackgroundVariant, Controls, type Edge, Handle, MarkerType, type Node, type NodeProps, Position } from "reactflow";

import "reactflow/dist/style.css";

import { StatusPill } from "@/components/ui/badge";
import type { GraphNode, NodeState, WorkflowGraph } from "@/lib/types";
import { cn, titleCase } from "@/lib/utils";

export interface GraphNodeData {
  nodeKey: string;
  node: GraphNode;
  status: string | null;
  current: boolean;
  pendingApprovals: number;
  isStart: boolean;
}

const TYPE_ICON: Record<string, typeof Bot> = {
  agent: Bot,
  condition: GitBranch,
  approval_gate: CheckSquare,
  parallel: Layers,
  workflow: WorkflowIcon,
  action: Wrench,
  end: Flag,
};

function statusClasses(status: string | null, current: boolean): string {
  const base = (() => {
    switch (status) {
      case "completed":
        return "border-success/60 bg-success/10";
      case "failed":
      case "escalated":
        return "border-danger/60 bg-danger/10";
      case "waiting":
      case "needs_approval":
        return "border-warning/60 bg-warning/10";
      case "needs_input":
        return "border-info/60 bg-info/10";
      case "running":
        return "border-accent/60 bg-accent/10";
      case "skipped":
        return "border-border bg-surface-2/60 opacity-70";
      default:
        return "border-border bg-surface opacity-80";
    }
  })();
  return cn(base, current && "ring-2 ring-accent shadow-glow opacity-100");
}

function subtitle(node: GraphNode): string {
  switch (node.type) {
    case "agent":
      return titleCase(node.agent ?? "");
    case "condition": {
      const when = node.when as { path?: string; equals?: unknown } | undefined;
      return when?.path ? `${when.path.replace(/^\$\.nodes\./, "")} = ${JSON.stringify(when.equals)}` : "condition";
    }
    case "approval_gate":
      return "Waits for pending approvals";
    case "parallel":
      return `${(node.branches ?? []).length} branches`;
    case "workflow":
      return node.workflow_key ?? "sub-workflow";
    case "action":
      return node.tool ?? node.action_type ?? "action";
    case "end":
      return "Terminal node";
    default:
      return node.type;
  }
}

function GraphNodeView({ data }: NodeProps<GraphNodeData>) {
  const Icon = TYPE_ICON[data.node.type] ?? Play;
  return (
    <div className={cn("w-[208px] rounded-lg border px-3 py-2.5 text-left shadow-soft transition-shadow", statusClasses(data.status, data.current))}>
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-border-strong" />
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface text-fg-muted">
          <Icon className="h-3.5 w-3.5" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-fg">{data.nodeKey}</span>
          <span className="block truncate text-[11px] text-fg-muted">{subtitle(data.node)}</span>
        </span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1">
        <span className="rounded bg-surface px-1.5 py-0.5 font-mono text-[10px] text-fg-subtle">{data.node.type}</span>
        {data.status ? <StatusPill status={data.status} size="sm" /> : <span className="text-[10px] text-fg-subtle">not reached</span>}
        {data.pendingApprovals > 0 ? <span className="text-[10px] text-warning">{data.pendingApprovals} pending</span> : null}
        {data.current ? <span className="text-[10px] font-medium text-accent">current</span> : null}
      </div>
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-border-strong" />
    </div>
  );
}

const nodeTypes = { opsNode: GraphNodeView };

interface LayoutEdge {
  from: string;
  to: string;
  label?: string;
  dashed?: boolean;
}

function collectEdges(graph: WorkflowGraph): LayoutEdge[] {
  const edges: LayoutEdge[] = [];
  for (const [key, node] of Object.entries(graph.nodes)) {
    if (node.type === "condition") {
      if (node.then) edges.push({ from: key, to: node.then, label: "yes" });
      if (node.else) edges.push({ from: key, to: node.else, label: "no" });
    } else if (node.type === "parallel") {
      for (const branch of node.branches ?? []) {
        edges.push({ from: key, to: branch, label: "branch" });
        if (node.next) edges.push({ from: branch, to: node.next, label: "join", dashed: true });
      }
      if (node.next && (node.branches ?? []).length === 0) edges.push({ from: key, to: node.next });
    } else if (node.next) {
      edges.push({ from: key, to: node.next });
    }
    if (node.on_failure) edges.push({ from: key, to: node.on_failure, label: "on failure", dashed: true });
    if (node.on_needs_input) edges.push({ from: key, to: node.on_needs_input, label: "needs input", dashed: true });
  }
  return edges.filter((e) => graph.nodes[e.to] !== undefined);
}

/** Longest-path layering from the start node (cycle-safe), then stacks nodes per layer. */
function layout(graph: WorkflowGraph, edges: LayoutEdge[]): Map<string, { x: number; y: number }> {
  const depth = new Map<string, number>();
  const keys = Object.keys(graph.nodes);
  const outgoing = new Map<string, string[]>();
  for (const e of edges) {
    if (e.dashed && e.label === "join") continue; // join edges should not push the target further right than needed
    outgoing.set(e.from, [...(outgoing.get(e.from) ?? []), e.to]);
  }
  const visit = (key: string, d: number, path: Set<string>) => {
    if (path.has(key) || d > keys.length + 2) return;
    if ((depth.get(key) ?? -1) >= d) return;
    depth.set(key, d);
    const next = new Set(path);
    next.add(key);
    for (const to of outgoing.get(key) ?? []) visit(to, d + 1, next);
  };
  visit(graph.start, 0, new Set());
  // Join targets (parallel.next) must sit after all branches.
  for (const e of edges) {
    if (e.label === "join") depth.set(e.to, Math.max(depth.get(e.to) ?? 0, (depth.get(e.from) ?? 0) + 1));
  }
  // End node last.
  const maxDepth = Math.max(0, ...Array.from(depth.values()));
  for (const key of keys) {
    if (!depth.has(key)) depth.set(key, maxDepth + 1);
    if (graph.nodes[key].type === "end") depth.set(key, Math.max(depth.get(key) ?? 0, maxDepth));
  }
  const layers = new Map<number, string[]>();
  for (const key of keys) {
    const d = depth.get(key) ?? 0;
    layers.set(d, [...(layers.get(d) ?? []), key]);
  }
  const positions = new Map<string, { x: number; y: number }>();
  const GAP_X = 270;
  const GAP_Y = 112;
  for (const [d, members] of layers) {
    const total = (members.length - 1) * GAP_Y;
    members.forEach((key, i) => positions.set(key, { x: d * GAP_X, y: i * GAP_Y - total / 2 }));
  }
  return positions;
}

export interface WorkflowGraphViewProps {
  graph: WorkflowGraph;
  nodeStates?: Record<string, NodeState>;
  currentNode?: string | null;
  runStatus?: string;
  className?: string;
  height?: number | string;
  interactive?: boolean;
}

export function WorkflowGraphView({ graph, nodeStates = {}, currentNode, runStatus, className, height = 420, interactive = true }: WorkflowGraphViewProps) {
  const { nodes, edges } = useMemo(() => {
    const layoutEdges = collectEdges(graph);
    const positions = layout(graph, layoutEdges);
    const reached = new Set(Object.keys(nodeStates));
    const nodes: Node<GraphNodeData>[] = Object.entries(graph.nodes).map(([key, node]) => {
      const state = nodeStates[key];
      let status: string | null = state?.status ?? null;
      if (node.type === "end" && !status && runStatus === "completed") status = "completed";
      if (currentNode === key && !status && (runStatus === "running" || runStatus === "pending")) status = "running";
      if (status) reached.add(key);
      return {
        id: key,
        type: "opsNode",
        position: positions.get(key) ?? { x: 0, y: 0 },
        data: { nodeKey: key, node, status, current: currentNode === key, pendingApprovals: state?.pending?.length ?? 0, isStart: graph.start === key },
        draggable: false,
        selectable: false,
        connectable: false,
      };
    });
    const edges: Edge[] = layoutEdges.map((e, i) => ({
      id: `${e.from}->${e.to}-${i}`,
      source: e.from,
      target: e.to,
      label: e.label,
      type: "smoothstep",
      className: reached.has(e.from) && reached.has(e.to) && !e.dashed ? "edge-taken" : undefined,
      style: e.dashed ? { strokeDasharray: "5 4" } : undefined,
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: reached.has(e.from) && reached.has(e.to) && !e.dashed ? "hsl(var(--accent))" : "hsl(var(--border-strong))" },
      labelBgPadding: [4, 2],
      labelBgBorderRadius: 4,
    }));
    return { nodes, edges };
  }, [graph, nodeStates, currentNode, runStatus]);

  return (
    <div className={cn("overflow-hidden rounded-lg border border-border bg-bg/40", className)} style={{ height }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        zoomOnScroll={interactive}
        panOnDrag={interactive}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
        minZoom={0.3}
        maxZoom={1.5}
        aria-label="Workflow graph"
      >
        <Background variant={BackgroundVariant.Dots} gap={18} size={1} color="hsl(var(--border-strong))" />
        {interactive ? <Controls showInteractive={false} /> : null}
      </ReactFlow>
    </div>
  );
}

export function GraphLegend({ className }: { className?: string }) {
  const items: Array<{ label: string; className: string }> = [
    { label: "Completed", className: "border-success/60 bg-success/10" },
    { label: "Failed", className: "border-danger/60 bg-danger/10" },
    { label: "Waiting / needs approval", className: "border-warning/60 bg-warning/10" },
    { label: "Needs input", className: "border-info/60 bg-info/10" },
    { label: "Not reached", className: "border-border bg-surface opacity-80" },
    { label: "Current node", className: "border-accent ring-2 ring-accent" },
  ];
  return (
    <ul className={cn("flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-fg-muted", className)} aria-label="Graph legend">
      {items.map((item) => (
        <li key={item.label} className="inline-flex items-center gap-1.5">
          <span className={cn("inline-block h-3 w-4 rounded-sm border", item.className)} aria-hidden />
          {item.label}
        </li>
      ))}
    </ul>
  );
}
