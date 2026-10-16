import { cn } from "@/lib/utils";

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-shimmer rounded-md bg-[linear-gradient(90deg,hsl(var(--surface-2))_25%,hsl(var(--surface-3))_50%,hsl(var(--surface-2))_75%)] bg-[length:200%_100%]", className)} />;
}

export function SkeletonRows({ rows = 6, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} role="status" aria-live="polite" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  );
}

export function SkeletonCards({ count = 4, className, cardClassName }: { count?: number; className?: string; cardClassName?: string }) {
  return (
    <div className={cn("grid gap-4 sm:grid-cols-2 lg:grid-cols-4", className)} role="status" aria-label="Loading">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className={cn("h-28 w-full", cardClassName)} />
      ))}
      <span className="sr-only">Loading…</span>
    </div>
  );
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)} aria-hidden>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} className={cn("h-3.5", i === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </div>
  );
}
