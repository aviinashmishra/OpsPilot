"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn, fmtInt } from "@/lib/utils";

export interface PaginationProps {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
  className?: string;
  label?: string;
}

export function Pagination({ total, limit, offset, onChange, className, label = "items" }: PaginationProps) {
  if (total <= 0) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  const start = Math.min(offset + 1, total);
  const end = Math.min(offset + limit, total);
  return (
    <nav className={cn("flex flex-wrap items-center justify-between gap-2 text-xs text-fg-muted", className)} aria-label="Pagination">
      <p className="tabular">
        Showing {fmtInt(start)}–{fmtInt(end)} of {fmtInt(total)} {label}
      </p>
      <div className="flex items-center gap-1">
        <Button variant="outline" size="icon-sm" onClick={() => onChange(Math.max(0, offset - limit))} disabled={page <= 1} aria-label="Previous page">
          <ChevronLeft className="h-4 w-4" aria-hidden />
        </Button>
        <span className="px-2 tabular">
          Page {page} / {pages}
        </span>
        <Button variant="outline" size="icon-sm" onClick={() => onChange(offset + limit)} disabled={page >= pages} aria-label="Next page">
          <ChevronRight className="h-4 w-4" aria-hidden />
        </Button>
      </div>
    </nav>
  );
}
