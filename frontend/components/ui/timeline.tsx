import type { ReactNode } from "react";

import { statusTone } from "@/components/ui/badge";
import { cn, fmtDateTime, fmtRelative } from "@/lib/utils";

export interface TimelineItem {
  id: string;
  title: ReactNode;
  status?: string;
  time?: string | null;
  meta?: ReactNode;
  detail?: ReactNode;
}

const dotTone: Record<string, string> = {
  neutral: "bg-fg-subtle",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
  accent: "bg-accent",
};

export function Timeline({ items, className }: { items: TimelineItem[]; className?: string }) {
  return (
    <ol className={cn("relative space-y-0 border-l border-border pl-5", className)}>
      {items.map((item) => (
        <li key={item.id} className="relative pb-5 last:pb-0">
          <span className={cn("absolute -left-[25px] top-1 h-2.5 w-2.5 rounded-full ring-4 ring-surface", dotTone[statusTone(item.status)])} aria-hidden />
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
            <p className="text-sm font-medium text-fg">{item.title}</p>
            {item.time ? (
              <time dateTime={item.time} title={fmtDateTime(item.time)} className="text-xs text-fg-subtle tabular">
                {fmtRelative(item.time)}
              </time>
            ) : null}
          </div>
          {item.meta ? <div className="mt-0.5 text-xs text-fg-muted">{item.meta}</div> : null}
          {item.detail ? <div className="mt-2">{item.detail}</div> : null}
        </li>
      ))}
    </ol>
  );
}
