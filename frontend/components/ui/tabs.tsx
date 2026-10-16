"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import { forwardRef } from "react";

import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;

export const TabsList = forwardRef<React.ElementRef<typeof TabsPrimitive.List>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>>(function TabsList({ className, ...props }, ref) {
  return <TabsPrimitive.List ref={ref} className={cn("inline-flex h-9 max-w-full items-center gap-1 overflow-x-auto rounded-lg border border-border bg-surface-2 p-1", className)} {...props} />;
});

export const TabsTrigger = forwardRef<React.ElementRef<typeof TabsPrimitive.Trigger>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>>(function TabsTrigger({ className, ...props }, ref) {
  return (
    <TabsPrimitive.Trigger
      ref={ref}
      className={cn(
        "inline-flex h-7 items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 text-sm font-medium text-fg-muted transition-colors hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 data-[state=active]:bg-surface data-[state=active]:text-fg data-[state=active]:shadow-soft disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
});

export const TabsContent = forwardRef<React.ElementRef<typeof TabsPrimitive.Content>, React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>>(function TabsContent({ className, ...props }, ref) {
  return <TabsPrimitive.Content ref={ref} className={cn("mt-4 focus-visible:outline-none", className)} {...props} />;
});
