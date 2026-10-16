import { cn } from "@/lib/utils";

export function BrandMark({ className }: { className?: string }) {
  return (
    <span className={cn("relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", className)} aria-hidden>
      <span className="absolute inset-0 rounded-lg bg-gradient-to-br from-[#7c5cff] via-[#5b5bff] to-[#22d3ee] opacity-90" />
      <svg viewBox="0 0 24 24" className="relative h-[60%] w-[60%] text-white" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 14 L10 6 L14 12 L20 4" />
        <path d="M4 20 L20 20" opacity="0.7" />
        <circle cx="20" cy="4" r="1.6" fill="currentColor" stroke="none" />
      </svg>
    </span>
  );
}

export function BrandWordmark({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <BrandMark />
      {!compact ? (
        <span className="flex flex-col leading-none">
          <span className="text-sm font-semibold tracking-tight text-fg">OpsPilot</span>
          <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-subtle">AI workforce</span>
        </span>
      ) : null}
    </span>
  );
}
