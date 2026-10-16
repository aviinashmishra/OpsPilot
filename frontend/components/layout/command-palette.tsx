"use client";

import { Command } from "cmdk";
import { Bot, CornerDownLeft, LogOut, Moon, Play, Search, Sparkles, Sun } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useTheme } from "@/components/providers/theme-provider";
import { Kbd } from "@/components/ui/misc";
import { ALL_NAV_ITEMS } from "@/lib/constants";
import { useCan } from "@/lib/permissions";
import { useAgents } from "@/lib/queries";
import { useSession } from "@/lib/session";
import { useUi } from "@/lib/ui-store";

export function CommandPalette() {
  const open = useUi((s) => s.paletteOpen);
  const setOpen = useUi((s) => s.setPaletteOpen);
  const setStartWorkflowOpen = useUi((s) => s.setStartWorkflowOpen);
  const router = useRouter();
  const can = useCan();
  const theme = useTheme((s) => s.theme);
  const toggleTheme = useTheme((s) => s.toggle);
  const clear = useSession((s) => s.clear);
  const agents = useAgents({}, { enabled: open && can("agents:read"), staleTime: 5 * 60_000 });
  const [search, setSearch] = useState("");
  const canCopilot = can("agents:run");
  const question = search.trim();

  useEffect(() => {
    if (!open) setSearch("");
  }, [open]);

  const askCopilot = (text: string) => {
    setOpen(false);
    router.push(text ? `/copilot?q=${encodeURIComponent(text)}` : "/copilot");
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(!useUi.getState().paletteOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);

  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };

  const pages = ALL_NAV_ITEMS.filter((item) => !item.permissions || item.permissions.some((p) => can(p)));

  return (
    <Command.Dialog open={open} onOpenChange={setOpen} label="Command palette" overlayClassName="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm animate-fade-in" contentClassName="fixed left-1/2 top-[12vh] z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border border-border bg-surface shadow-pop animate-zoom-in" loop>
      <div className="flex items-center gap-2 border-b border-border px-3">
        <Search className="h-4 w-4 shrink-0 text-fg-subtle" aria-hidden />
        <Command.Input
          value={search}
          onValueChange={setSearch}
          onKeyDown={(event) => {
            // Ctrl/⌘+Enter sends whatever was typed to the Copilot.
            if (canCopilot && question && event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              event.stopPropagation();
              askCopilot(question);
            }
          }}
          placeholder={canCopilot ? "Jump to a page, agent, or action — or ask the Copilot…" : "Jump to a page, agent, or action…"}
          className="h-12 w-full bg-transparent text-sm text-fg outline-none placeholder:text-fg-subtle"
          autoFocus
        />
        <Kbd>Esc</Kbd>
      </div>
      <Command.List className="max-h-[60vh] overflow-y-auto p-2 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[0.16em] [&_[cmdk-group-heading]]:text-fg-subtle">
        <Command.Empty className="px-3 py-8 text-center text-sm text-fg-muted">{canCopilot && question ? "No pages or agents match — ask the Copilot below." : "No results."}</Command.Empty>
        <Command.Group heading="Actions">
          {canCopilot ? (
            <Command.Item value="ask copilot ai assistant chat" onSelect={() => askCopilot("")} className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm text-fg data-[selected=true]:bg-surface-2">
              <Sparkles className="h-4 w-4 text-accent" aria-hidden /> Ask Copilot…
            </Command.Item>
          ) : null}
          {can("workflows:write") ? (
            <Command.Item
              value="start workflow run"
              onSelect={() => {
                setOpen(false);
                setStartWorkflowOpen(true);
              }}
              className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm text-fg data-[selected=true]:bg-surface-2"
            >
              <Play className="h-4 w-4 text-accent" aria-hidden /> Start workflow
            </Command.Item>
          ) : null}
          <Command.Item
            value="toggle theme dark light"
            onSelect={() => {
              toggleTheme();
              setOpen(false);
            }}
            className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm text-fg data-[selected=true]:bg-surface-2"
          >
            {theme === "dark" ? <Sun className="h-4 w-4 text-fg-muted" aria-hidden /> : <Moon className="h-4 w-4 text-fg-muted" aria-hidden />} Toggle theme
          </Command.Item>
          <Command.Item
            value="sign out logout"
            onSelect={() => {
              setOpen(false);
              clear();
              router.replace("/login");
            }}
            className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm text-fg data-[selected=true]:bg-surface-2"
          >
            <LogOut className="h-4 w-4 text-fg-muted" aria-hidden /> Sign out
          </Command.Item>
        </Command.Group>
        <Command.Group heading="Pages">
          {pages.map((item) => {
            const Icon = item.icon;
            return (
              <Command.Item key={item.href} value={`page ${item.label}`} onSelect={() => go(item.href)} className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm text-fg data-[selected=true]:bg-surface-2">
                <Icon className="h-4 w-4 text-fg-muted" aria-hidden /> {item.label}
              </Command.Item>
            );
          })}
          <Command.Item value="page workflow definitions templates" onSelect={() => go("/workflows/definitions")} className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm text-fg data-[selected=true]:bg-surface-2">
            <Play className="h-4 w-4 text-fg-muted" aria-hidden /> Workflow definitions
          </Command.Item>
        </Command.Group>
        {agents.data && agents.data.length > 0 ? (
          <Command.Group heading="Agents">
            {agents.data.map((agent) => (
              <Command.Item key={agent.agent_key} value={`agent ${agent.name} ${agent.agent_key} ${agent.department_label}`} onSelect={() => go(`/agents/${agent.agent_key}`)} className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 text-sm text-fg data-[selected=true]:bg-surface-2">
                <Bot className="h-4 w-4 text-fg-muted" aria-hidden />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate">{agent.name}</span>
                  <span className="truncate text-xs text-fg-subtle">{agent.department_label}</span>
                </span>
              </Command.Item>
            ))}
          </Command.Group>
        ) : null}
      </Command.List>
      {canCopilot && question ? (
        <button
          type="button"
          onClick={() => askCopilot(question)}
          className="flex w-full items-center gap-3 border-t border-border bg-surface-2/50 px-4 py-2.5 text-left text-sm text-fg transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/50"
        >
          <Sparkles className="h-4 w-4 shrink-0 text-accent" aria-hidden />
          <span className="min-w-0 flex-1 truncate">
            Ask Copilot: <span className="font-medium">“{question}”</span>
          </span>
          <span className="hidden shrink-0 items-center gap-0.5 sm:flex" aria-hidden>
            <Kbd>Ctrl</Kbd>
            <Kbd>
              <CornerDownLeft className="h-2.5 w-2.5" />
            </Kbd>
          </span>
        </button>
      ) : null}
    </Command.Dialog>
  );
}
