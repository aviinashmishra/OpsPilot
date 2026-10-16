import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface Crumb {
  label: ReactNode;
  href?: string;
}

export function PageHeader({ title, description, actions, crumbs, className, badge }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; crumbs?: Crumb[]; className?: string; badge?: ReactNode }) {
  return (
    <header className={cn("flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0">
        {crumbs && crumbs.length > 0 ? (
          <nav aria-label="Breadcrumb" className="mb-1.5 flex flex-wrap items-center gap-1 text-xs text-fg-muted">
            {crumbs.map((crumb, i) => (
              <span key={i} className="flex items-center gap-1">
                {crumb.href ? (
                  <Link href={crumb.href} className="rounded hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
                    {crumb.label}
                  </Link>
                ) : (
                  <span className="text-fg">{crumb.label}</span>
                )}
                {i < crumbs.length - 1 ? <ChevronRight className="h-3 w-3" aria-hidden /> : null}
              </span>
            ))}
          </nav>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
          {badge}
        </div>
        {description ? <p className="mt-1 max-w-2xl text-sm text-fg-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
