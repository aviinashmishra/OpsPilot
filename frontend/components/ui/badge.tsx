import {
  AlertOctagon,
  AlertTriangle,
  Ban,
  CheckCircle2,
  CircleDashed,
  CircleDot,
  Clock,
  HelpCircle,
  Hourglass,
  Loader2,
  type LucideIcon,
  PauseCircle,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import type { HTMLAttributes, ReactNode } from "react";

import { cn, titleCase } from "@/lib/utils";

export type Tone = "neutral" | "success" | "warning" | "danger" | "info" | "accent";

const toneClasses: Record<Tone, string> = {
  neutral: "bg-surface-3 text-fg-muted border-border-strong/60",
  success: "bg-success/12 text-success border-success/35",
  warning: "bg-warning/12 text-warning border-warning/35",
  danger: "bg-danger/12 text-danger border-danger/35",
  info: "bg-info/12 text-info border-info/35",
  accent: "bg-accent/12 text-accent border-accent/35",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  icon?: ReactNode;
  size?: "sm" | "md";
}

export function Badge({ tone = "neutral", icon, size = "md", className, children, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border font-medium",
        size === "sm" ? "px-1.5 py-0 text-[11px] leading-5" : "px-2 py-0.5 text-xs",
        toneClasses[tone],
        className,
      )}
      {...props}
    >
      {icon}
      {children}
    </span>
  );
}

interface StatusMeta {
  tone: Tone;
  icon: LucideIcon;
  label?: string;
  spin?: boolean;
}

const STATUS_META: Record<string, StatusMeta> = {
  // workflow / agent runs
  pending: { tone: "neutral", icon: CircleDashed },
  queued: { tone: "neutral", icon: CircleDashed },
  running: { tone: "info", icon: Loader2, spin: true },
  waiting_approval: { tone: "warning", icon: Hourglass, label: "Waiting approval" },
  waiting_input: { tone: "warning", icon: PauseCircle, label: "Waiting input" },
  waiting: { tone: "warning", icon: Hourglass },
  completed: { tone: "success", icon: CheckCircle2 },
  succeeded: { tone: "success", icon: CheckCircle2 },
  failed: { tone: "danger", icon: XCircle },
  timed_out: { tone: "danger", icon: Clock, label: "Timed out" },
  cancelled: { tone: "neutral", icon: Ban },
  skipped: { tone: "neutral", icon: CircleDashed },
  needs_approval: { tone: "warning", icon: Hourglass, label: "Needs approval" },
  needs_input: { tone: "warning", icon: HelpCircle, label: "Needs input" },
  needs_review: { tone: "warning", icon: Hourglass, label: "Needs review" },
  // job queue / workers
  dead: { tone: "danger", icon: AlertOctagon },
  alive: { tone: "success", icon: CheckCircle2 },
  lost: { tone: "danger", icon: AlertTriangle },
  stopped: { tone: "neutral", icon: PauseCircle },
  escalated: { tone: "danger", icon: ShieldAlert },
  // approvals
  approved: { tone: "success", icon: CheckCircle2 },
  executed: { tone: "success", icon: CheckCircle2 },
  rejected: { tone: "danger", icon: XCircle },
  execution_failed: { tone: "danger", icon: AlertOctagon, label: "Execution failed" },
  expired: { tone: "neutral", icon: Clock },
  // tasks
  open: { tone: "info", icon: CircleDot },
  in_progress: { tone: "accent", icon: Loader2, label: "In progress" },
  blocked: { tone: "danger", icon: Ban },
  done: { tone: "success", icon: CheckCircle2 },
  // integrations
  sandbox: { tone: "neutral", icon: CircleDashed },
  connected: { tone: "success", icon: CheckCircle2 },
  pending_test: { tone: "warning", icon: Hourglass, label: "Pending test" },
  error: { tone: "danger", icon: XCircle },
  // incidents / misc
  resolved: { tone: "success", icon: CheckCircle2 },
  active: { tone: "success", icon: CheckCircle2 },
  suspended: { tone: "warning", icon: PauseCircle },
  disabled: { tone: "danger", icon: Ban },
  clean: { tone: "success", icon: CheckCircle2 },
  flagged: { tone: "danger", icon: AlertTriangle },
  passed: { tone: "success", icon: CheckCircle2 },
  // severity
  info: { tone: "info", icon: CircleDot },
  warning: { tone: "warning", icon: AlertTriangle },
  critical: { tone: "danger", icon: AlertOctagon },
  high: { tone: "danger", icon: AlertTriangle },
  medium: { tone: "warning", icon: AlertTriangle },
  low: { tone: "success", icon: CheckCircle2 },
};

export function statusTone(status: string | null | undefined): Tone {
  if (!status) return "neutral";
  return STATUS_META[status]?.tone ?? "neutral";
}

export function StatusPill({ status, className, size = "md", label }: { status: string | null | undefined; className?: string; size?: "sm" | "md"; label?: string }) {
  const key = status ?? "unknown";
  const meta = STATUS_META[key] ?? { tone: "neutral" as Tone, icon: CircleDashed };
  const Icon = meta.icon;
  return (
    <Badge tone={meta.tone} size={size} className={className} icon={<Icon className={cn("h-3 w-3", meta.spin && "animate-spin")} aria-hidden />}>
      {label ?? meta.label ?? titleCase(key)}
    </Badge>
  );
}

export function RiskBadge({ level, className, size = "md" }: { level: string | null | undefined; className?: string; size?: "sm" | "md" }) {
  const key = level ?? "unknown";
  const meta = STATUS_META[key] ?? { tone: "neutral" as Tone, icon: HelpCircle };
  const Icon = meta.icon;
  return (
    <Badge tone={meta.tone} size={size} className={className} icon={<Icon className="h-3 w-3" aria-hidden />}>
      {titleCase(key)} risk
    </Badge>
  );
}

export function ModeBadge({ mode, status, size = "md" }: { mode: string; status?: string; size?: "sm" | "md" }) {
  if (mode === "live") {
    const ok = status === "connected";
    return (
      <Badge tone={ok ? "success" : status === "error" ? "danger" : "warning"} size={size} icon={ok ? <CheckCircle2 className="h-3 w-3" aria-hidden /> : <AlertTriangle className="h-3 w-3" aria-hidden />}>
        Live{ok ? " · connected" : status === "error" ? " · error" : " · untested"}
      </Badge>
    );
  }
  return (
    <Badge tone="neutral" size={size} icon={<CircleDashed className="h-3 w-3" aria-hidden />}>
      Sandbox
    </Badge>
  );
}
