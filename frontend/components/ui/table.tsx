import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function TableWrap({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("w-full overflow-x-auto rounded-lg border border-border", className)}>{children}</div>;
}

export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return <table className={cn("w-full min-w-[640px] border-collapse text-sm", className)} {...props} />;
}

export function THead({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn("bg-surface-2 text-left text-xs uppercase tracking-wide text-fg-muted", className)} {...props} />;
}

export function TBody({ className, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn("divide-y divide-border", className)} {...props} />;
}

export function TR({ className, interactive, ...props }: HTMLAttributes<HTMLTableRowElement> & { interactive?: boolean }) {
  return <tr className={cn("transition-colors", interactive && "cursor-pointer hover:bg-surface-2/70", className)} {...props} />;
}

export function TH({ className, align = "left", ...props }: ThHTMLAttributes<HTMLTableCellElement> & { align?: "left" | "right" | "center" }) {
  return <th scope="col" className={cn("px-3 py-2.5 font-medium", align === "right" && "text-right", align === "center" && "text-center", className)} {...props} />;
}

export function TD({ className, align = "left", ...props }: TdHTMLAttributes<HTMLTableCellElement> & { align?: "left" | "right" | "center" }) {
  return <td className={cn("px-3 py-2.5 align-middle text-fg", align === "right" && "text-right tabular", align === "center" && "text-center", className)} {...props} />;
}

export function SortableTH({ label, active, direction, onClick, align = "left", className }: { label: ReactNode; active: boolean; direction: "asc" | "desc"; onClick: () => void; align?: "left" | "right"; className?: string }) {
  const Icon = !active ? ArrowUpDown : direction === "asc" ? ArrowUp : ArrowDown;
  return (
    <TH align={align} className={className} aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" onClick={onClick} className={cn("inline-flex items-center gap-1 rounded hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50", active && "text-fg")}>
        {label}
        <Icon className="h-3 w-3" aria-hidden />
      </button>
    </TH>
  );
}
