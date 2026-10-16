"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useReducedMotion } from "framer-motion";
import { Lock, MessageSquare, MessageSquarePlus, Sparkles } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Composer, type ComposerHandle } from "@/components/copilot/composer";
import { CopilotHero, CopilotModeBadge, toolCountsText } from "@/components/copilot/hero";
import { AssistantMessage, PendingAssistant, UserBubble } from "@/components/copilot/messages";
import { SessionList } from "@/components/copilot/session-list";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Sheet } from "@/components/ui/sheet";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { api, errorMessage, isApiError } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import { qk, useCopilotSession, useCopilotSessions, useCopilotStatus } from "@/lib/queries";
import type { CopilotMessageIn, CopilotSessionOut } from "@/lib/types";

interface PendingSend {
  sessionId: string | null;
  text: string;
}

function CopilotContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const reduce = useReducedMotion();
  const urlSelected = searchParams.get("s");
  const prefill = searchParams.get("q");
  // Mirrors ?s= but updates synchronously, so a freshly created chat never flashes the empty state.
  const [selectedId, setSelectedId] = useState<string | null>(urlSelected);
  useEffect(() => setSelectedId(urlSelected), [urlSelected]);

  const status = useCopilotStatus();
  const sessions = useCopilotSessions();
  const session = useCopilotSession(selectedId);

  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<PendingSend | null>(null);
  const [deleting, setDeleting] = useState<CopilotSessionOut | null>(null);
  const [mobileListOpen, setMobileListOpen] = useState(false);
  const composer = useRef<ComposerHandle>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const setSelected = useCallback(
    (id: string | null) => {
      setSelectedId(id);
      const params = new URLSearchParams(searchParams.toString());
      if (id) params.set("s", id);
      else params.delete("s");
      params.delete("q");
      const qs = params.toString();
      router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  // ?q= prefill (e.g. from the command palette "Ask Copilot…").
  useEffect(() => {
    if (!prefill) return;
    setDraft(prefill);
    const params = new URLSearchParams(searchParams.toString());
    params.delete("q");
    const qs = params.toString();
    router.replace(`${pathname}${qs ? `?${qs}` : ""}`, { scroll: false });
    window.setTimeout(() => composer.current?.focus(), 50);
  }, [prefill, pathname, router, searchParams]);

  const onSent = useCallback(
    (data: CopilotSessionOut) => {
      queryClient.setQueryData(qk.copilotSession(data.id), data);
      void queryClient.invalidateQueries({ queryKey: qk.copilotSessions });
      setPending(null);
      stickToBottom.current = true;
    },
    [queryClient],
  );

  const create = useMutation({
    mutationFn: (text: string) => api<CopilotSessionOut>("/copilot/sessions", { method: "POST", body: { message: text } satisfies CopilotMessageIn }),
    onSuccess: (data) => {
      onSent(data);
      setSelected(data.id);
    },
    onError: (error, text) => {
      setPending(null);
      setDraft((d) => d || text);
      toast.error("Could not start the conversation", { description: errorMessage(error) });
    },
  });

  const send = useMutation({
    mutationFn: ({ sessionId, text }: { sessionId: string; text: string }) => api<CopilotSessionOut>(`/copilot/sessions/${encodeURIComponent(sessionId)}/messages`, { method: "POST", body: { message: text } satisfies CopilotMessageIn }),
    onSuccess: (data) => onSent(data),
    onError: (error, vars) => {
      setPending(null);
      setDraft((d) => d || vars.text);
      const busy = isApiError(error) && error.status === 409;
      toast.error(busy ? "The Copilot is still answering" : "Could not send the message", { description: busy ? "Wait for the current answer to finish, then send again." : errorMessage(error) });
      if (busy) void queryClient.invalidateQueries({ queryKey: qk.copilotSession(vars.sessionId) });
    },
  });

  const remove = useMutation({
    mutationFn: (target: CopilotSessionOut) => api<void>(`/copilot/sessions/${encodeURIComponent(target.id)}`, { method: "DELETE" }),
    onSuccess: (_, target) => {
      toast.success("Chat deleted");
      queryClient.setQueryData<CopilotSessionOut[]>(qk.copilotSessions, (prev) => prev?.filter((s) => s.id !== target.id));
      queryClient.removeQueries({ queryKey: qk.copilotSession(target.id) });
      void queryClient.invalidateQueries({ queryKey: qk.copilotSessions });
      if (target.id === selectedId) setSelected(null);
      setDeleting(null);
    },
    onError: (error) => toast.error("Could not delete the chat", { description: errorMessage(error) }),
  });

  const data = selectedId ? session.data : undefined;
  const sending = create.isPending || send.isPending;
  const busy = Boolean(data?.busy) || sending;

  const submit = useCallback(
    (text: string) => {
      const message = text.trim();
      if (!message || busy) return;
      setDraft("");
      stickToBottom.current = true;
      setPending({ sessionId: selectedId, text: message });
      if (selectedId) send.mutate({ sessionId: selectedId, text: message });
      else create.mutate(message);
    },
    [busy, create, selectedId, send],
  );

  // When an answer finishes, refresh everything it may have touched.
  const wasBusy = useRef(false);
  useEffect(() => {
    const nowBusy = Boolean(data?.busy);
    if (wasBusy.current && !nowBusy) {
      void queryClient.invalidateQueries({ queryKey: qk.copilotSessions });
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
    }
    wasBusy.current = nowBusy;
  }, [data?.busy, queryClient]);

  // Auto-scroll while the conversation grows, unless the reader scrolled up.
  const messages = data?.messages;
  const growth = useMemo(() => {
    if (!messages) return "";
    const last = messages[messages.length - 1];
    return `${messages.length}:${last?.steps.length ?? 0}:${last?.steps.filter((s) => s.status !== "running").length ?? 0}:${last?.text.length ?? 0}:${last?.status ?? ""}`;
  }, [messages]);
  const inConversation = Boolean(selectedId) || pending !== null;
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (!inConversation) {
      el.scrollTo({ top: 0 });
      return;
    }
    if (!stickToBottom.current) return;
    el.scrollTo({ top: el.scrollHeight, behavior: reduce ? "auto" : "smooth" });
  }, [growth, pending, reduce, inConversation]);
  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  const retryFrom = (index: number) => {
    if (!messages) return;
    for (let i = index - 1; i >= 0; i -= 1) {
      if (messages[i].role === "user") {
        submit(messages[i].text);
        return;
      }
    }
  };

  const showPending = pending && (pending.sessionId === null ? !selectedId : pending.sessionId === selectedId);
  const isEmpty = !selectedId && !showPending;

  const list = (
    <SessionList
      sessions={sessions.data}
      loading={sessions.isLoading}
      error={sessions.error}
      onRetry={() => sessions.refetch()}
      selectedId={selectedId}
      onSelect={(id) => {
        setSelected(id);
        setMobileListOpen(false);
        stickToBottom.current = true;
      }}
      onNew={() => {
        setSelected(null);
        setMobileListOpen(false);
        window.setTimeout(() => composer.current?.focus(), 50);
      }}
      onDelete={setDeleting}
      className="h-full"
    />
  );

  return (
    <div className="flex h-[calc(100dvh-3.5rem-2.5rem)] min-h-[480px] gap-4 lg:h-[calc(100dvh-3.5rem-3rem)]">
      <aside className="surface-card hidden w-72 shrink-0 flex-col overflow-hidden lg:flex" aria-label="Copilot chats">
        {list}
      </aside>

      <section className="surface-card relative flex min-w-0 flex-1 flex-col overflow-hidden" aria-label="Conversation">
        <header className="flex items-center gap-2 border-b border-border px-3 py-2.5 sm:px-4">
          <Button variant="ghost" size="icon-sm" className="lg:hidden" onClick={() => setMobileListOpen(true)} aria-label="Show chats">
            <MessageSquare className="h-4 w-4" aria-hidden />
          </Button>
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-accent-2 text-white" aria-hidden>
            <Sparkles className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold leading-tight">{data?.title ?? (showPending && pending ? pending.text : "Ops Copilot")}</h1>
            <p className="truncate text-[11px] text-fg-subtle" data-testid="copilot-tool-counts">{status.data ? toolCountsText(status.data) : null}</p>
          </div>
          <div className="hidden sm:block">
            <CopilotModeBadge status={status.data} compact />
          </div>
          {selectedId ? (
            <Button variant="ghost" size="sm" onClick={() => setSelected(null)} leftIcon={<MessageSquarePlus className="h-4 w-4" aria-hidden />} className="shrink-0">
              <span className="hidden sm:inline">New chat</span>
              <span className="sr-only sm:hidden">New chat</span>
            </Button>
          ) : null}
        </header>

        <div ref={scroller} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto" aria-live="off">
          {isEmpty ? (
            <CopilotHero status={status.data} statusError={status.error} statusLoading={status.isLoading} onSuggestion={submit} disabled={sending} />
          ) : selectedId && session.isError ? (
            <div className="p-6">
              <ErrorState error={session.error} onRetry={() => session.refetch()} title="Could not load this chat" />
            </div>
          ) : selectedId && session.isLoading && !showPending ? (
            <div className="p-6">
              <SkeletonRows rows={5} />
            </div>
          ) : (
            <div className="mx-auto w-full max-w-3xl space-y-6 px-3 py-6 sm:px-6">
              {(messages ?? []).map((message, index) =>
                message.role === "user" ? (
                  <UserBubble key={message.id} text={message.text} time={message.created_at} />
                ) : (
                  <AssistantMessage key={message.id} message={message} isLatest={index === (messages?.length ?? 0) - 1} onRetry={!busy ? () => retryFrom(index) : undefined} retrying={sending} />
                ),
              )}
              {showPending && pending ? (
                <>
                  <UserBubble text={pending.text} pending />
                  <PendingAssistant />
                </>
              ) : null}
            </div>
          )}
        </div>

        <div className="border-t border-border bg-surface/80 px-3 pb-3 pt-3 sm:px-4">
          <div className="mx-auto w-full max-w-3xl">
            <Composer ref={composer} value={draft} onChange={setDraft} onSubmit={submit} busy={Boolean(data?.busy)} sending={sending} />
          </div>
        </div>
      </section>

      <Sheet open={mobileListOpen} onOpenChange={setMobileListOpen} side="left" size="md" title="Copilot chats" description="Private to you" className="max-w-[85vw]">
        <div className="-mx-5 -my-4 h-[calc(100%+2rem)]">{list}</div>
      </Sheet>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title="Delete this chat?"
        description={deleting ? `“${deleting.title}” and its tool-call trace will be removed. Approvals, agent runs and audit records it created are kept.` : undefined}
        confirmLabel="Delete chat"
        tone="danger"
        loading={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </div>
  );
}

export default function CopilotPage() {
  const canRun = usePermission("agents:run");
  if (!canRun) {
    return (
      <div className="space-y-5">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">Ops Copilot</h1>
        <EmptyState
          icon={Lock}
          title="The Copilot needs permission to run agents"
          description="Ask an administrator for a role that includes agents:run, such as operator."
        />
      </div>
    );
  }
  return (
    <Suspense fallback={<SkeletonRows rows={8} />}>
      <CopilotContent />
    </Suspense>
  );
}
