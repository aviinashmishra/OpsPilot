"use client";

import { motion, useReducedMotion } from "framer-motion";
import { AlertCircle, ChevronDown, Cpu, RotateCcw, Sparkles, User } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Markdown } from "@/components/copilot/markdown";
import { StepTrace, traceDigest } from "@/components/copilot/step-trace";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { Tip } from "@/components/ui/tooltip";
import { useTick } from "@/lib/hooks";
import type { CopilotMessageOut } from "@/lib/types";
import { cn, copilotModelLabel, fmtCurrency, fmtDateTime, fmtInt, fmtMs, parseDate } from "@/lib/utils";

function Appear({ children, className }: { children: ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }} className={className}>
      {children}
    </motion.div>
  );
}

export function CopilotAvatar({ className }: { className?: string }) {
  return (
    <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-2 text-white shadow-glow", className)} aria-hidden>
      <Sparkles className="h-4 w-4" />
    </span>
  );
}

export function UserBubble({ text, time, pending }: { text: string; time?: string | null; pending?: boolean }) {
  return (
    <Appear className="flex justify-end gap-2.5" >
      <div className={cn("max-w-[85%] rounded-2xl rounded-tr-md border border-accent/25 bg-accent/10 px-3.5 py-2.5 sm:max-w-[75%]", pending && "opacity-80")} data-testid="copilot-user-message">
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-fg">{text}</p>
        {time ? (
          <p className="mt-1 text-right text-[10px] text-fg-subtle" title={fmtDateTime(time)}>
            {fmtShortTime(time)}
          </p>
        ) : pending ? (
          <p className="mt-1 text-right text-[10px] text-fg-subtle">Sending…</p>
        ) : null}
      </div>
      <span className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border bg-surface-2 text-fg-muted sm:flex" aria-hidden>
        <User className="h-4 w-4" />
      </span>
    </Appear>
  );
}

function fmtShortTime(value: string): string {
  const date = parseDate(value);
  return date ? date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
}

function Elapsed({ since }: { since: string }) {
  useTick(1000);
  const start = parseDate(since);
  if (!start) return null;
  return <span className="tabular">{Math.max(0, Math.round((Date.now() - start.getTime()) / 1000))}s</span>;
}

function WorkingIndicator({ status, since, hasSteps }: { status: string; since: string; hasSteps: boolean }) {
  const label = status === "pending" ? "Queued — waiting for a worker" : hasSteps ? "Working through the plan" : "Planning which agents and tools to call";
  return (
    <div className="flex items-center gap-2 text-xs text-fg-muted" role="status" aria-live="polite">
      <span className="relative flex h-2 w-2" aria-hidden>
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60 motion-reduce:animate-none" />
        <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
      </span>
      <span>{label}…</span>
      <span className="text-fg-subtle">
        <Elapsed since={since} />
      </span>
    </div>
  );
}

function MessageFooter({ message }: { message: CopilotMessageOut }) {
  const u = message.usage ?? {};
  const live = copilotModelLabel(message.mode);
  const tokens = (u.input_tokens ?? 0) + (u.output_tokens ?? 0);
  const parts: ReactNode[] = [];
  if (typeof u.tool_calls === "number") parts.push(`${fmtInt(u.tool_calls)} tool call${u.tool_calls === 1 ? "" : "s"}`);
  if (typeof u.iterations === "number" && live) parts.push(`${fmtInt(u.iterations)} model turn${u.iterations === 1 ? "" : "s"}`);
  if (typeof u.latency_ms === "number") parts.push(fmtMs(u.latency_ms));
  if (live) {
    parts.push(
      <Tip key="tok" content={`${fmtInt(u.input_tokens ?? 0)} input · ${fmtInt(u.output_tokens ?? 0)} output tokens`}>
        <span className="cursor-help">{fmtInt(tokens)} tokens</span>
      </Tip>,
    );
    parts.push(fmtCurrency(u.cost_usd ?? 0));
  }
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-fg-subtle" data-testid="copilot-message-footer">
      {message.mode ? (
        live ? (
          <Badge size="sm" tone="accent" icon={<Sparkles className="h-3 w-3" aria-hidden />}>
            {live}{message.model ? ` · ${message.model}` : ""}
          </Badge>
        ) : (
          <Tip content="No LLM API key is configured, so a deterministic planner routes the request to tools.">
            <span>
              <Badge size="sm" icon={<Cpu className="h-3 w-3" aria-hidden />}>
                Offline planner
              </Badge>
            </span>
          </Tip>
        )
      ) : null}
      {parts.map((p, i) => (
        <span key={i} className="inline-flex items-center gap-2 tabular">
          {i > 0 || message.mode ? <span aria-hidden>·</span> : null}
          {p}
        </span>
      ))}
      {message.text ? <CopyButton value={message.text} label="Copy answer" className="ml-auto h-6 w-6" /> : null}
    </div>
  );
}

export function AssistantMessage({ message, isLatest, onRetry, retrying }: { message: CopilotMessageOut; isLatest: boolean; onRetry?: () => void; retrying?: boolean }) {
  const working = message.status === "pending" || message.status === "running";
  const failed = message.status === "failed";
  const [traceOpen, setTraceOpen] = useState<boolean | null>(null);
  const showTrace = traceOpen ?? (working || isLatest);
  const hasSteps = message.steps.length > 0;

  return (
    <Appear className="flex gap-2.5" >
      <CopilotAvatar className="mt-0.5" />
      <div className="min-w-0 flex-1 space-y-3" data-testid="copilot-assistant-message" data-status={message.status}>
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-fg">Copilot</span>
          {working ? <WorkingIndicator status={message.status} since={message.created_at} hasSteps={hasSteps} /> : null}
        </div>

        {hasSteps ? (
          <div className="rounded-xl border border-border bg-surface-2/40 p-3">
            <button
              type="button"
              onClick={() => setTraceOpen(!showTrace)}
              aria-expanded={showTrace}
              className="flex w-full items-center justify-between gap-2 rounded text-left text-xs font-medium text-fg-muted hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
            >
              <span>{working ? "Live tool-call trace" : `Tool-call trace · ${traceDigest(message.steps)}`}</span>
              <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 transition-transform", showTrace && "rotate-180")} aria-hidden />
            </button>
            {showTrace ? <StepTrace steps={message.steps} className="mt-3" /> : null}
          </div>
        ) : working ? (
          <div className="space-y-2 rounded-xl border border-dashed border-border p-3" aria-hidden>
            <div className="h-3 w-2/3 animate-shimmer rounded bg-[linear-gradient(90deg,hsl(var(--surface-2))_25%,hsl(var(--surface-3))_50%,hsl(var(--surface-2))_75%)] bg-[length:200%_100%]" />
            <div className="h-3 w-1/2 animate-shimmer rounded bg-[linear-gradient(90deg,hsl(var(--surface-2))_25%,hsl(var(--surface-3))_50%,hsl(var(--surface-2))_75%)] bg-[length:200%_100%]" />
          </div>
        ) : null}

        {failed ? (
          <div role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-sm font-medium text-danger">
              <AlertCircle className="h-4 w-4 shrink-0" aria-hidden /> The Copilot couldn&apos;t finish this request
            </p>
            {message.error ? <p className="mt-1 break-words font-mono text-[11px] text-fg-muted">{message.error}</p> : null}
            {onRetry ? (
              <Button variant="outline" size="xs" className="mt-2" onClick={onRetry} loading={retrying} leftIcon={<RotateCcw className="h-3 w-3" aria-hidden />}>
                Retry
              </Button>
            ) : null}
          </div>
        ) : message.text ? (
          <Markdown text={message.text} />
        ) : null}

        {!working ? <MessageFooter message={message} /> : null}
      </div>
    </Appear>
  );
}

export function PendingAssistant() {
  const [since] = useState(() => new Date().toISOString());
  return (
    <Appear className="flex gap-2.5">
      <CopilotAvatar className="mt-0.5" />
      <div className="min-w-0 flex-1 space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-fg">Copilot</span>
          <WorkingIndicator status="pending" since={since} hasSteps={false} />
        </div>
      </div>
    </Appear>
  );
}
