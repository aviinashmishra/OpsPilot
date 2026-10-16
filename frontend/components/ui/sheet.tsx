"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export interface SheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  side?: "right" | "left";
  size?: "md" | "lg" | "xl";
  className?: string;
}

/** Side drawer built on Radix Dialog (focus trap, escape, aria). */
export function Sheet({ open, onOpenChange, title, description, children, footer, side = "right", size = "lg", className }: SheetProps) {
  const widths = { md: "sm:max-w-md", lg: "sm:max-w-xl", xl: "sm:max-w-3xl" };
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm animate-fade-in" />
        <DialogPrimitive.Content
          className={cn(
            "fixed inset-y-0 z-50 flex w-full flex-col border-border bg-surface shadow-pop focus:outline-none",
            side === "right" ? "right-0 border-l animate-slide-in-right" : "left-0 border-r animate-slide-in-left",
            widths[size],
            className,
          )}
        >
          <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
            <div className="min-w-0">
              <DialogPrimitive.Title className="text-base font-semibold text-fg">{title}</DialogPrimitive.Title>
              {description ? <DialogPrimitive.Description className="mt-0.5 text-xs text-fg-muted">{description}</DialogPrimitive.Description> : null}
            </div>
            <DialogPrimitive.Close className="rounded-md p-1.5 text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" aria-label="Close panel">
              <X className="h-4 w-4" aria-hidden />
            </DialogPrimitive.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
          {footer ? <div className="border-t border-border px-5 py-3">{footer}</div> : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
