"use client";

import { ArrowUpRight, Bot, KeyRound } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { ButtonLink } from "@/components/ui/button";
import { Card, CardContent, CardToolbar } from "@/components/ui/card";
import { CopyButton } from "@/components/ui/copy-button";
import { CodeBlock } from "@/components/ui/json-viewer";
import { usePermission } from "@/lib/permissions";
import { cn } from "@/lib/utils";

export const MCP_TOOLS: Array<{ name: string; description: string }> = [
  { name: "list_agents", description: "The 25 specialist agents and what they do" },
  { name: "describe_agent", description: "An agent's input schema, tools and policies" },
  { name: "run_agent", description: "Run an agent; actions stay policy-gated" },
  { name: "start_workflow", description: "Start a durable multi-agent workflow" },
  { name: "get_workflow_run", description: "Follow a workflow run step by step" },
  { name: "list_pending_approvals", description: "What is waiting for a human" },
  { name: "search_knowledge", description: "Search the tenant's documents" },
];

const DEFAULT_MCP_URL = "http://127.0.0.1:8000/mcp";

/** The API serves MCP on its own port; derive the default URL from the host the dashboard is opened on. */
export function useMcpUrl(): string {
  const [url, setUrl] = useState(DEFAULT_MCP_URL);
  useEffect(() => {
    const host = window.location.hostname;
    if (host) setUrl(`http://${host.includes(":") ? `[${host}]` : host}:8000/mcp`);
  }, []);
  return url;
}

export function mcpConfigSnippet(url: string): string {
  return JSON.stringify({ mcpServers: { opspilot: { type: "http", url, headers: { "X-API-Key": "opk_..." } } } }, null, 2);
}

export function McpConnectContent({ className }: { className?: string }) {
  const url = useMcpUrl();
  const canKeys = usePermission("apikeys:admin");
  const snippet = mcpConfigSnippet(url);
  return (
    <div className={cn("space-y-4", className)}>
      <div className="space-y-1.5">
        <p className="flex items-center gap-2 text-xs font-medium text-fg-muted">
          MCP endpoint <Badge size="sm">default</Badge> <span className="font-normal text-fg-subtle">Streamable HTTP</span>
        </p>
        <div className="flex items-center gap-1 rounded-md border border-border bg-bg/60 py-1 pl-3 pr-1">
          <code className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg" data-testid="mcp-url">
            {url}
          </code>
          <CopyButton value={url} label="Copy MCP URL" />
        </div>
      </div>
      <div className="space-y-1.5">
        <p className="text-xs font-medium text-fg-muted">Client configuration (Claude Desktop, Claude Code, Cursor…)</p>
        <CodeBlock code={snippet} language="json" maxHeight="14rem" />
        <p className="flex items-start gap-1.5 text-[11px] text-fg-subtle">
          <KeyRound className="mt-px h-3 w-3 shrink-0" aria-hidden /> The API key&apos;s scopes decide which tools work.
        </p>
      </div>
      <div className="space-y-1.5">
        <p className="text-xs font-medium text-fg-muted">Tools exposed</p>
        <ul className="grid gap-1 sm:grid-cols-2">
          {MCP_TOOLS.map((tool) => (
            <li key={tool.name} className="rounded-md border border-border bg-surface-2/50 px-2 py-1.5">
              <code className="font-mono text-[11px] text-fg">{tool.name}</code>
              <span className="block text-[11px] text-fg-subtle">{tool.description}</span>
            </li>
          ))}
        </ul>
      </div>
      {canKeys ? (
        <ButtonLink href="/admin?tab=apikeys" size="sm" variant="outline" leftIcon={<KeyRound className="h-3.5 w-3.5" aria-hidden />}>
          Create an API key <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
        </ButtonLink>
      ) : (
        <p className="text-xs text-fg-subtle">Ask an administrator for an API key (Admin → API keys).</p>
      )}
    </div>
  );
}

export function McpCard({ className }: { className?: string }) {
  return (
    <Card className={className}>
      <CardToolbar
        title={
          <span className="inline-flex items-center gap-2">
            <Bot className="h-4 w-4 text-accent" aria-hidden /> Connect an AI client (MCP)
          </span>
        }
        description="Use OpsPilot from Claude, Cursor or any MCP client."
      />
      <CardContent>
        <McpConnectContent />
      </CardContent>
    </Card>
  );
}
