"use client";

import { ChevronDown } from "lucide-react";
import { useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return <kbd className={cn("inline-flex h-5 min-w-5 items-center justify-center rounded border border-border bg-surface-2 px-1 font-mono text-[10px] font-medium text-fg-muted", className)}>{children}</kbd>;
}

export interface SegmentOption<T extends string | number> {
  value: T;
  label: ReactNode;
  disabled?: boolean;
}

export function Segmented<T extends string | number>({ value, onChange, options, className, size = "sm", "aria-label": ariaLabel }: { value: T; onChange: (v: T) => void; options: SegmentOption<T>[]; className?: string; size?: "sm" | "md"; "aria-label"?: string }) {
  return (
    <div role="group" aria-label={ariaLabel} className={cn("inline-flex max-w-full items-center gap-0.5 overflow-x-auto rounded-md border border-border bg-surface-2 p-0.5", className)}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={String(option.value)}
            type="button"
            disabled={option.disabled}
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "whitespace-nowrap rounded px-2.5 font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50",
              size === "sm" ? "h-7 text-xs" : "h-8 text-sm",
              active ? "bg-surface text-fg shadow-soft" : "text-fg-muted hover:text-fg",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function Chip({ active, onClick, children, className }: { active?: boolean; onClick?: () => void; children: ReactNode; className?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex h-7 items-center gap-1 whitespace-nowrap rounded-full border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
        active ? "border-accent/50 bg-accent/15 text-accent" : "border-border bg-surface text-fg-muted hover:border-border-strong hover:text-fg",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Meter({ value, max, label, tone = "accent", className, format }: { value: number; max: number; label?: ReactNode; tone?: "accent" | "success" | "warning" | "danger"; className?: string; format?: (v: number, m: number) => string }) {
  const ratio = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  const fills = { accent: "gradient-bar", success: "bg-success", warning: "bg-warning", danger: "bg-danger" };
  return (
    <div className={cn("space-y-1.5", className)}>
      {label ? (
        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="text-fg-muted">{label}</span>
          <span className="text-fg tabular">{format ? format(value, max) : `${Math.round(ratio * 100)}%`}</span>
        </div>
      ) : null}
      <div className="h-2 w-full overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}>
        <div className={cn("h-full rounded-full transition-[width] duration-500", fills[tone])} style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}

export function Collapsible({ title, children, defaultOpen = false, className, summary }: { title: ReactNode; children: ReactNode; defaultOpen?: boolean; className?: string; summary?: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={cn("rounded-lg border border-border bg-surface", className)}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
        <div className="min-w-0 flex-1">{title}</div>
        {summary ? <div className="hidden shrink-0 sm:block">{summary}</div> : null}
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-fg-muted transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open ? <div className="border-t border-border px-4 py-3">{children}</div> : null}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <span className={cn("inline-block h-4 w-4 animate-spin rounded-full border-2 border-fg-subtle border-t-accent", className)} role="status" aria-label="Loading" />;
}

export function SectionTitle({ children, className, actions }: { children: ReactNode; className?: string; actions?: ReactNode }) {
  return (
    <div className={cn("flex items-center justify-between gap-2", className)}>
      <h2 className="text-sm font-semibold uppercase tracking-wide text-fg-muted">{children}</h2>
      {actions}
    </div>
  );
}
