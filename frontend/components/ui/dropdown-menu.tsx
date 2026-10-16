"use client";

import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { forwardRef } from "react";

import { cn } from "@/lib/utils";

export const DropdownMenu = DropdownMenuPrimitive.Root;
export const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;
export const DropdownMenuGroup = DropdownMenuPrimitive.Group;

export const DropdownMenuContent = forwardRef<React.ElementRef<typeof DropdownMenuPrimitive.Content>, React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Content>>(function DropdownMenuContent(
  { className, sideOffset = 6, ...props },
  ref,
) {
  return (
    <DropdownMenuPrimitive.Portal>
      <DropdownMenuPrimitive.Content ref={ref} sideOffset={sideOffset} className={cn("z-50 min-w-[12rem] overflow-hidden rounded-lg border border-border bg-surface p-1 shadow-pop animate-zoom-in", className)} {...props} />
    </DropdownMenuPrimitive.Portal>
  );
});

export const DropdownMenuItem = forwardRef<React.ElementRef<typeof DropdownMenuPrimitive.Item>, React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Item> & { destructive?: boolean }>(function DropdownMenuItem(
  { className, destructive, ...props },
  ref,
) {
  return (
    <DropdownMenuPrimitive.Item
      ref={ref}
      className={cn(
        "relative flex cursor-pointer select-none items-center gap-2 rounded-md px-2 py-1.5 text-sm outline-none transition-colors data-[highlighted]:bg-surface-2 data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
        destructive ? "text-danger" : "text-fg",
        className,
      )}
      {...props}
    />
  );
});

export const DropdownMenuLabel = forwardRef<React.ElementRef<typeof DropdownMenuPrimitive.Label>, React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Label>>(function DropdownMenuLabel({ className, ...props }, ref) {
  return <DropdownMenuPrimitive.Label ref={ref} className={cn("px-2 py-1.5 text-xs font-medium text-fg-subtle", className)} {...props} />;
});

export const DropdownMenuSeparator = forwardRef<React.ElementRef<typeof DropdownMenuPrimitive.Separator>, React.ComponentPropsWithoutRef<typeof DropdownMenuPrimitive.Separator>>(function DropdownMenuSeparator({ className, ...props }, ref) {
  return <DropdownMenuPrimitive.Separator ref={ref} className={cn("-mx-1 my-1 h-px bg-border", className)} {...props} />;
});
