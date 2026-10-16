"use client";

import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

export interface SelectProps {
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  className?: string;
  disabled?: boolean;
  "aria-label"?: string;
  id?: string;
  size?: "sm" | "md";
}

export function Select({ value, onValueChange, options, placeholder = "Select…", className, disabled, id, size = "md", ...rest }: SelectProps) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectPrimitive.Trigger
        id={id}
        aria-label={rest["aria-label"]}
        className={cn(
          "inline-flex w-full items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 text-sm text-fg transition-colors hover:border-border-strong focus:outline-none focus:ring-2 focus:ring-ring/40 data-[placeholder]:text-fg-subtle disabled:opacity-60",
          size === "sm" ? "h-8 text-xs" : "h-9",
          className,
        )}
      >
        <span className="truncate">
          <SelectPrimitive.Value placeholder={placeholder} />
        </span>
        <SelectPrimitive.Icon>
          <ChevronDown className="h-4 w-4 shrink-0 text-fg-subtle" aria-hidden />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content position="popper" sideOffset={6} className="z-50 max-h-72 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg border border-border bg-surface shadow-pop animate-zoom-in">
          <SelectPrimitive.Viewport className="p-1">
            {options.map((option) => (
              <SelectPrimitive.Item
                key={option.value}
                value={option.value}
                disabled={option.disabled}
                className="relative flex cursor-pointer select-none items-center rounded-md py-1.5 pl-8 pr-3 text-sm text-fg outline-none data-[highlighted]:bg-surface-2 data-[disabled]:opacity-50 data-[disabled]:pointer-events-none"
              >
                <span className="absolute left-2 flex h-4 w-4 items-center justify-center">
                  <SelectPrimitive.ItemIndicator>
                    <Check className="h-3.5 w-3.5 text-accent" aria-hidden />
                  </SelectPrimitive.ItemIndicator>
                </span>
                <div className="min-w-0">
                  <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
                  {option.description ? <p className="text-xs text-fg-subtle">{option.description}</p> : null}
                </div>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
