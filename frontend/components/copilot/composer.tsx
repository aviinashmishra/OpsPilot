"use client";

import { ArrowUp, Loader2 } from "lucide-react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, type KeyboardEvent } from "react";

import { Kbd } from "@/components/ui/misc";
import { cn } from "@/lib/utils";

const MAX_LENGTH = 8000;
const MAX_HEIGHT = 220;

export interface ComposerHandle {
  focus: () => void;
}

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (text: string) => void;
  /** The Copilot is still answering: typing is allowed, sending is not. */
  busy: boolean;
  sending?: boolean;
  disabled?: boolean;
  placeholder?: string;
}

/** Auto-growing message box: Enter sends, Shift+Enter inserts a newline. */
export const Composer = forwardRef<ComposerHandle, ComposerProps>(function Composer({ value, onChange, onSubmit, busy, sending, disabled, placeholder }, ref) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  useImperativeHandle(ref, () => ({ focus: () => textarea.current?.focus() }), []);

  const resize = useCallback(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
    el.style.overflowY = el.scrollHeight > MAX_HEIGHT ? "auto" : "hidden";
  }, []);

  useEffect(() => {
    resize();
  }, [value, resize]);

  const trimmed = value.trim();
  const blocked = busy || sending || disabled;
  const canSend = trimmed.length > 0 && !blocked && value.length <= MAX_LENGTH;

  const submit = () => {
    if (!canSend) return;
    onSubmit(trimmed);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="relative"
    >
      <div className={cn("flex items-end gap-2 rounded-xl border border-border bg-surface px-3 py-2 shadow-soft transition-colors focus-within:border-accent/60 focus-within:ring-2 focus-within:ring-ring/30", disabled && "opacity-60")}>
        <label htmlFor="copilot-input" className="sr-only">
          Message the Copilot
        </label>
        <textarea
          id="copilot-input"
          ref={textarea}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          maxLength={MAX_LENGTH}
          disabled={disabled}
          placeholder={busy ? "The Copilot is working — you can draft your next message…" : placeholder ?? "Ask about orders, stock, approvals, KPIs, customers…"}
          aria-describedby="copilot-input-hint"
          className="max-h-[220px] min-h-[36px] flex-1 resize-none bg-transparent py-1.5 text-sm leading-relaxed text-fg outline-none placeholder:text-fg-subtle disabled:cursor-not-allowed"
        />
        <button
          type="submit"
          disabled={!canSend}
          aria-label={busy ? "Wait for the current answer" : "Send message"}
          className="mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg gradient-accent text-white shadow-soft transition-[filter,opacity,transform] hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 active:translate-y-px disabled:pointer-events-none disabled:opacity-40"
        >
          {sending || busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <ArrowUp className="h-4 w-4" aria-hidden />}
        </button>
      </div>
      <div id="copilot-input-hint" className="mt-1.5 flex items-center justify-between gap-2 px-1 text-[11px] text-fg-subtle">
        <span className="hidden items-center gap-1 sm:inline-flex">
          <Kbd>Enter</Kbd> to send · <Kbd>Shift</Kbd>+<Kbd>Enter</Kbd> for a new line
        </span>
        <span className={cn("tabular", value.length > MAX_LENGTH * 0.9 && "text-warning")}>{value.length > 500 ? `${value.length.toLocaleString()} / ${MAX_LENGTH.toLocaleString()}` : null}</span>
      </div>
    </form>
  );
});
