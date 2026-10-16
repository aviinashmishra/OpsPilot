import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import type { Tone } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const iconTones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-fg-muted",
  success: "bg-success/12 text-success",
  warning: "bg-warning/12 text-warning",
  danger: "bg-danger/12 text-danger",
  info: "bg-info/12 text-info",
  accent: "bg-accent/12 text-accent",
};

export interface StatTileProps {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  icon?: LucideIcon;
  tone?: Tone;
  className?: string;
  loading?: boolean;
  footer?: ReactNode;
}

export function StatTile({ label, value, hint, icon: Icon, tone = "neutral", className, loading, footer }: StatTileProps) {
  return (
    <div className={cn("surface-card flex flex-col gap-2 p-4", className)}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium text-fg-muted">{label}</p>
        {Icon ? (
          <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-md", iconTones[tone])}>
            <Icon className="h-4 w-4" aria-hidden />
          </span>
        ) : null}
      </div>
      {loading ? <Skeleton className="h-8 w-24" /> : <p className="text-2xl font-semibold leading-none tracking-tight text-fg tabular">{value}</p>}
      {hint ? <p className="text-xs text-fg-subtle">{hint}</p> : null}
      {footer}
    </div>
  );
}
