"use client";

import { Loader2, MessageSquare, MessageSquarePlus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useTick } from "@/lib/hooks";
import type { CopilotSessionOut } from "@/lib/types";
import { cn, fmtDateTime, fmtRelative } from "@/lib/utils";

export interface SessionListProps {
  sessions: CopilotSessionOut[] | undefined;
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (session: CopilotSessionOut) => void;
  className?: string;
}

export function SessionList({ sessions, loading, error, onRetry, selectedId, onSelect, onNew, onDelete, className }: SessionListProps) {
  useTick(30_000);
  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="p-3">
        <Button variant="primary" className="w-full" onClick={onNew} leftIcon={<MessageSquarePlus className="h-4 w-4" aria-hidden />}>
          New chat
        </Button>
      </div>
      <p className="px-4 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-subtle">Recent</p>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {error ? (
          <ErrorState compact error={error} onRetry={onRetry} title="Could not load chats" />
        ) : loading ? (
          <div className="space-y-1.5 px-1" role="status" aria-label="Loading chats">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : !sessions || sessions.length === 0 ? (
          <EmptyState compact icon={MessageSquare} title="No chats yet" description="Your chats are private and appear here." className="mx-1" />
        ) : (
          <ul className="space-y-0.5" aria-label="Copilot chats">
            {sessions.map((session) => {
              const active = session.id === selectedId;
              return (
                <li key={session.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onSelect(session.id)}
                    aria-current={active ? "true" : undefined}
                    className={cn(
                      "flex w-full items-start gap-2 rounded-md px-2.5 py-2 pr-9 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
                      active ? "bg-accent/12 text-fg" : "text-fg-muted hover:bg-surface-2 hover:text-fg",
                    )}
                  >
                    <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center" aria-hidden>
                      {session.busy ? <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" /> : <MessageSquare className={cn("h-3.5 w-3.5", active ? "text-accent" : "text-fg-subtle")} />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{session.title || "Untitled chat"}</span>
                      <span className="block text-[11px] text-fg-subtle" title={fmtDateTime(session.updated_at)}>
                        {session.busy ? "working…" : fmtRelative(session.updated_at)}
                      </span>
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(session)}
                    aria-label={`Delete chat: ${session.title}`}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1.5 text-fg-subtle opacity-100 transition-opacity hover:bg-danger/15 hover:text-danger focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 lg:opacity-0 lg:group-hover:opacity-100"
                  >
                    <Trash2 className="h-3.5 w-3.5" aria-hidden />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
