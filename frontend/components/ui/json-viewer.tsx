"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState, type ReactNode } from "react";

import { CopyButton } from "@/components/ui/copy-button";
import { cn, isPlainObject, prettyJson } from "@/lib/utils";

export function CodeBlock({ code, className, language, maxHeight = "24rem", copy = true }: { code: string; className?: string; language?: string; maxHeight?: string; copy?: boolean }) {
  return (
    <div className={cn("group relative rounded-md border border-border bg-bg/60", className)}>
      {copy ? (
        <div className="absolute right-1.5 top-1.5 z-10">
          <CopyButton value={code} label="Copy" />
        </div>
      ) : null}
      <pre className="overflow-auto p-3 pr-10 font-mono text-[12px] leading-relaxed text-fg" style={{ maxHeight }} data-language={language}>
        <code>{code}</code>
      </pre>
    </div>
  );
}

function TreeNode({ name, value, depth, defaultOpen }: { name: string | null; value: unknown; depth: number; defaultOpen: boolean }): ReactNode {
  const [open, setOpen] = useState(defaultOpen);
  const isObject = isPlainObject(value);
  const isArray = Array.isArray(value);
  const keyLabel = name !== null ? <span className="text-accent">{name}</span> : null;

  if (isObject || isArray) {
    const entries: Array<[string, unknown]> = isArray ? (value as unknown[]).map((v, i) => [String(i), v]) : Object.entries(value as Record<string, unknown>);
    const summary = isArray ? `[${entries.length}]` : `{${entries.length}}`;
    return (
      <div className="font-mono text-[12px] leading-5">
        <button type="button" onClick={() => setOpen((o) => !o)} className="inline-flex items-center gap-1 rounded text-fg-muted hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" aria-expanded={open}>
          {open ? <ChevronDown className="h-3 w-3" aria-hidden /> : <ChevronRight className="h-3 w-3" aria-hidden />}
          {keyLabel}
          {name !== null ? <span className="text-fg-subtle">:</span> : null}
          <span className="text-fg-subtle">{summary}</span>
        </button>
        {open && entries.length > 0 ? (
          <div className="ml-1.5 border-l border-border pl-3">
            {entries.map(([k, v]) => (
              <TreeNode key={k} name={k} value={v} depth={depth + 1} defaultOpen={depth < 1} />
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  let rendered: ReactNode;
  if (value === null || value === undefined) rendered = <span className="text-fg-subtle">null</span>;
  else if (typeof value === "string") rendered = <span className="whitespace-pre-wrap break-words text-success">&quot;{value}&quot;</span>;
  else if (typeof value === "number") rendered = <span className="text-info tabular">{value}</span>;
  else if (typeof value === "boolean") rendered = <span className="text-warning">{String(value)}</span>;
  else rendered = <span>{String(value)}</span>;

  return (
    <div className="font-mono text-[12px] leading-5">
      {keyLabel}
      {name !== null ? <span className="text-fg-subtle">: </span> : null}
      {rendered}
    </div>
  );
}

export function JsonViewer({ value, className, collapsed = false, maxHeight = "28rem", title }: { value: unknown; className?: string; collapsed?: boolean; maxHeight?: string; title?: ReactNode }) {
  const [raw, setRaw] = useState(false);
  const text = prettyJson(value);
  const empty = value === null || value === undefined || (isPlainObject(value) && Object.keys(value).length === 0) || (Array.isArray(value) && value.length === 0);
  return (
    <div className={cn("rounded-md border border-border bg-bg/60", className)}>
      <div className="flex items-center justify-between gap-2 border-b border-border px-2 py-1">
        <span className="text-[11px] font-medium uppercase tracking-wide text-fg-subtle">{title ?? "JSON"}</span>
        <div className="flex items-center gap-0.5">
          <button type="button" onClick={() => setRaw((r) => !r)} className="rounded px-1.5 py-0.5 text-[11px] text-fg-muted hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" aria-pressed={raw}>
            {raw ? "Tree" : "Raw"}
          </button>
          <CopyButton value={text} label="Copy JSON" />
        </div>
      </div>
      <div className="overflow-auto p-3" style={{ maxHeight }}>
        {empty ? <p className="font-mono text-[12px] text-fg-subtle">{Array.isArray(value) ? "[]" : "{}"}</p> : raw ? <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-fg">{text}</pre> : <TreeNode name={null} value={value} depth={0} defaultOpen={!collapsed} />}
      </div>
    </div>
  );
}
