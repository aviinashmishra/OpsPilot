"use client";

import { AlertCircle, Inbox, Lock, type LucideIcon, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { errorMessage, isApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

export function EmptyState({ icon: Icon = Inbox, title, description, action, className, compact }: { icon?: LucideIcon; title: ReactNode; description?: ReactNode; action?: ReactNode; className?: string; compact?: boolean }) {
  return (
    <div className={cn("flex flex-col items-center justify-center rounded-lg border border-dashed border-border text-center", compact ? "px-4 py-8" : "px-6 py-14", className)}>
      <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-fg-muted">
        <Icon className="h-5 w-5" aria-hidden />
      </span>
      <p className="text-sm font-medium text-fg">{title}</p>
      {description ? <p className="mt-1 max-w-sm text-xs text-fg-muted">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry, title = "Could not load data", className, compact }: { error: unknown; onRetry?: () => void; title?: ReactNode; className?: string; compact?: boolean }) {
  if (isApiError(error) && error.status === 403) {
    // A permission gap, not a failure: explain it in plain words, no retry or technical ids.
    return <EmptyState icon={Lock} title="You don't have access to this" description="Your role doesn't include it. Ask a workspace administrator if you need it." className={className} compact={compact} />;
  }
  const message = errorMessage(error);
  const correlation = isApiError(error) ? error.correlationId : null;
  const code = isApiError(error) ? error.code : null;
  return (
    <div role="alert" className={cn("flex flex-col items-center justify-center rounded-lg border border-danger/40 bg-danger/5 text-center", compact ? "px-4 py-6" : "px-6 py-12", className)}>
      <span className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-danger/15 text-danger">
        <AlertCircle className="h-5 w-5" aria-hidden />
      </span>
      <p className="text-sm font-medium text-fg">{title}</p>
      <p className="mt-1 max-w-md text-xs text-fg-muted">{message}</p>
      {code || correlation ? (
        <p className="mt-2 font-mono text-[11px] text-fg-subtle">
          {code ? <span>code: {code}</span> : null}
          {code && correlation ? " · " : null}
          {correlation ? <span>correlation: {correlation}</span> : null}
        </p>
      ) : null}
      {onRetry ? (
        <Button variant="outline" size="sm" className="mt-4" onClick={onRetry} leftIcon={<RefreshCw className="h-3.5 w-3.5" aria-hidden />}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

export function InlineError({ error, className }: { error: unknown; className?: string }) {
  return (
    <p role="alert" className={cn("flex items-center gap-1.5 text-xs text-danger", className)}>
      <AlertCircle className="h-3.5 w-3.5 shrink-0" aria-hidden />
      {errorMessage(error)}
    </p>
  );
}
