"use client";

import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export const TooltipProvider = TooltipPrimitive.Provider;

export function Tip({ content, children, side = "top", className, asChild = true }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right"; className?: string; asChild?: boolean }) {
  if (content === null || content === undefined || content === "") return <>{children}</>;
  return (
    <TooltipPrimitive.Root delayDuration={200}>
      <TooltipPrimitive.Trigger asChild={asChild}>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content side={side} sideOffset={6} className={cn("z-50 max-w-xs rounded-md border border-border bg-surface-2 px-2.5 py-1.5 text-xs text-fg shadow-pop animate-fade-in", className)}>
          {content}
          <TooltipPrimitive.Arrow className="fill-surface-2" />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
