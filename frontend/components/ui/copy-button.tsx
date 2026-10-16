"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Tip } from "@/components/ui/tooltip";
import { cn, copyToClipboard } from "@/lib/utils";

export function CopyButton({ value, label = "Copy", className, size = "icon-sm" }: { value: string; label?: string; className?: string; size?: "icon-sm" | "icon" | "xs" | "sm" }) {
  const [copied, setCopied] = useState(false);
  const iconOnly = size === "icon-sm" || size === "icon";
  return (
    <Tip content={copied ? "Copied" : label}>
      <Button
        variant="ghost"
        size={size}
        className={cn("shrink-0", className)}
        aria-label={copied ? "Copied" : label}
        onClick={async (event) => {
          event.stopPropagation();
          const ok = await copyToClipboard(value);
          if (ok) {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
          }
        }}
      >
        {copied ? <Check className="h-3.5 w-3.5 text-success" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
        {!iconOnly ? <span>{copied ? "Copied" : label}</span> : null}
      </Button>
    </Tip>
  );
}

/** Inline monospace identifier with copy affordance. */
export function CopyableId({ value, short = 8, className }: { value: string | null | undefined; short?: number; className?: string }) {
  if (!value) return <span className="text-fg-subtle">—</span>;
  return (
    <span className={cn("inline-flex items-center gap-0.5", className)}>
      <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-fg-muted" title={value}>
        {value.length > short ? `${value.slice(0, short)}…` : value}
      </code>
      <CopyButton value={value} label="Copy id" />
    </span>
  );
}
