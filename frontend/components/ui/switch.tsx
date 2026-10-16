"use client";

import * as SwitchPrimitive from "@radix-ui/react-switch";
import { forwardRef } from "react";

import { cn } from "@/lib/utils";

export interface SwitchProps extends React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root> {
  tone?: "accent" | "danger";
  size?: "sm" | "md";
}

export const Switch = forwardRef<React.ElementRef<typeof SwitchPrimitive.Root>, SwitchProps>(function Switch({ className, tone = "accent", size = "md", ...props }, ref) {
  return (
    <SwitchPrimitive.Root
      ref={ref}
      className={cn(
        "peer inline-flex shrink-0 cursor-pointer items-center rounded-full border border-transparent bg-surface-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-5 w-9" : "h-6 w-11",
        tone === "danger" ? "data-[state=checked]:bg-danger" : "data-[state=checked]:bg-accent",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        className={cn(
          "pointer-events-none block rounded-full bg-white shadow transition-transform",
          size === "sm" ? "h-4 w-4 translate-x-0.5 data-[state=checked]:translate-x-[18px]" : "h-5 w-5 translate-x-0.5 data-[state=checked]:translate-x-[22px]",
        )}
      />
    </SwitchPrimitive.Root>
  );
});
