import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface KeyValueItem {
  label: ReactNode;
  value: ReactNode;
  mono?: boolean;
  /** Spans the full width on wide layouts. */
  wide?: boolean;
}

export function KeyValueList({ items, className, columns = 2, dense }: { items: KeyValueItem[]; className?: string; columns?: 1 | 2 | 3; dense?: boolean }) {
  const cols = { 1: "sm:grid-cols-1", 2: "sm:grid-cols-2", 3: "sm:grid-cols-3" }[columns];
  return (
    <dl className={cn("grid grid-cols-1 gap-x-6", dense ? "gap-y-2" : "gap-y-3", cols, className)}>
      {items.map((item, i) => (
        <div key={i} className={cn("min-w-0", item.wide && "sm:col-span-full")}>
          <dt className="text-[11px] font-medium uppercase tracking-wide text-fg-subtle">{item.label}</dt>
          <dd className={cn("mt-0.5 break-words text-sm text-fg", item.mono && "font-mono text-xs")}>{item.value ?? <span className="text-fg-subtle">—</span>}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ChipList({ items, tone = "neutral", empty = "None", className }: { items: string[] | null | undefined; tone?: "neutral" | "accent"; empty?: string; className?: string }) {
  if (!items || items.length === 0) return <span className="text-sm text-fg-subtle">{empty}</span>;
  return (
    <ul className={cn("flex flex-wrap gap-1.5", className)}>
      {items.map((item) => (
        <li key={item} className={cn("rounded-md border px-1.5 py-0.5 font-mono text-[11px]", tone === "accent" ? "border-accent/30 bg-accent/10 text-accent" : "border-border bg-surface-2 text-fg-muted")}>
          {item}
        </li>
      ))}
    </ul>
  );
}
