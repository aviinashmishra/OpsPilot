"use client";

import { Braces, Check, WandSparkles } from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn, prettyJson, safeJsonParse } from "@/lib/utils";

export interface JsonEditorProps {
  value: string;
  onChange: (value: string) => void;
  className?: string;
  rows?: number;
  label?: string;
  placeholder?: string;
  disabled?: boolean;
  /** Called with validity on every change. */
  onValidChange?: (valid: boolean) => void;
}

/** Monospace textarea with JSON validation and a format action. */
export function JsonEditor({ value, onChange, className, rows = 12, label = "JSON", placeholder = "{}", disabled, onValidChange }: JsonEditorProps) {
  const id = useId();
  const parsed = useMemo(() => safeJsonParse(value || "{}"), [value]);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    onValidChange?.(parsed.ok);
  }, [parsed.ok, onValidChange]);

  const error = !parsed.ok ? parsed.error : null;
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={id} className="inline-flex items-center gap-1 text-xs font-medium text-fg-muted">
          <Braces className="h-3.5 w-3.5" aria-hidden />
          {label}
        </label>
        <div className="flex items-center gap-1">
          {parsed.ok ? (
            <span className="inline-flex items-center gap-1 text-[11px] text-success">
              <Check className="h-3 w-3" aria-hidden /> valid
            </span>
          ) : (
            <span className="text-[11px] text-danger">invalid</span>
          )}
          <Button
            variant="ghost"
            size="xs"
            disabled={!parsed.ok || disabled}
            onClick={() => {
              if (parsed.ok) onChange(prettyJson(parsed.value));
            }}
            leftIcon={<WandSparkles className="h-3 w-3" aria-hidden />}
          >
            Format
          </Button>
        </div>
      </div>
      <textarea
        id={id}
        value={value}
        onChange={(e) => {
          setTouched(true);
          onChange(e.target.value);
        }}
        onBlur={() => setTouched(true)}
        rows={rows}
        spellCheck={false}
        placeholder={placeholder}
        disabled={disabled}
        aria-invalid={!parsed.ok}
        aria-describedby={error ? `${id}-error` : undefined}
        className={cn(
          "w-full resize-y rounded-md border border-border bg-bg/60 px-3 py-2 font-mono text-[12px] leading-relaxed text-fg placeholder:text-fg-subtle focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60",
          !parsed.ok && touched && "border-danger",
        )}
      />
      {error && touched ? (
        <p id={`${id}-error`} className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
