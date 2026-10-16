"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { motion, useReducedMotion } from "framer-motion";
import { ChevronDown, ChevronsLeft, ChevronsRight, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useState } from "react";

import { BrandWordmark } from "@/components/layout/brand";
import { Tip } from "@/components/ui/tooltip";
import { DEPARTMENTS, NAV_GROUPS, type NavItem } from "@/lib/constants";
import { useCan } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { useUi } from "@/lib/ui-store";
import { cn } from "@/lib/utils";

function isActive(item: NavItem, pathname: string): boolean {
  if (item.match) return item.match(pathname);
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

function NavLink({ item, collapsed, onNavigate }: { item: NavItem; collapsed: boolean; onNavigate?: () => void }) {
  const pathname = usePathname() ?? "";
  const searchParams = useSearchParams();
  const active = isActive(item, pathname);
  const Icon = item.icon;
  const [deptOpen, setDeptOpen] = useState(() => pathname.startsWith("/agents"));
  const hasDepartments = item.href === "/agents";
  const currentDept = pathname === "/agents" ? searchParams?.get("department") ?? "" : "";
  const reduce = useReducedMotion();

  const link = (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex h-9 items-center gap-3 rounded-md px-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
        active ? "bg-accent/12 text-fg" : "text-fg-muted hover:bg-surface-2 hover:text-fg",
        collapsed && "justify-center px-0",
      )}
    >
      {active ? <motion.span layoutId={collapsed ? undefined : "nav-active"} transition={reduce ? { duration: 0 } : { type: "spring", stiffness: 500, damping: 40 }} className="absolute left-0 top-1.5 h-6 w-0.5 rounded-r bg-gradient-to-b from-accent to-accent-2" aria-hidden /> : null}
      <Icon className={cn("h-4 w-4 shrink-0", active ? "text-accent" : "text-fg-subtle group-hover:text-fg")} aria-hidden />
      {!collapsed ? <span className="truncate">{item.label}</span> : <span className="sr-only">{item.label}</span>}
      {!collapsed && hasDepartments ? (
        <button
          type="button"
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            setDeptOpen((o) => !o);
          }}
          aria-label={deptOpen ? "Collapse departments" : "Expand departments"}
          aria-expanded={deptOpen}
          className="ml-auto rounded p-0.5 text-fg-subtle hover:bg-surface-3 hover:text-fg"
        >
          <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", deptOpen && "rotate-180")} aria-hidden />
        </button>
      ) : null}
    </Link>
  );

  return (
    <li>
      {collapsed ? (
        <Tip content={item.label} side="right">
          {link}
        </Tip>
      ) : (
        link
      )}
      {!collapsed && hasDepartments && deptOpen ? (
        <ul className="ml-[22px] mt-0.5 space-y-0.5 border-l border-border pl-3" aria-label="Departments">
          {DEPARTMENTS.map((d) => {
            const activeDept = pathname === "/agents" && currentDept === d.key;
            return (
              <li key={d.key}>
                <Link
                  href={`/agents?department=${d.key}`}
                  onClick={onNavigate}
                  aria-current={activeDept ? "page" : undefined}
                  className={cn("flex h-7 items-center rounded-md px-2 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50", activeDept ? "bg-accent/12 text-fg" : "text-fg-muted hover:bg-surface-2 hover:text-fg")}
                >
                  <span className="truncate">{d.short}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      ) : null}
    </li>
  );
}

function NavGroups({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const can = useCan();
  return (
    <nav aria-label="Primary" className="flex-1 overflow-y-auto px-2 py-3">
      {NAV_GROUPS.map((group) => {
        const items = group.items.filter((item) => !item.permissions || item.permissions.some((p) => can(p)));
        if (items.length === 0) return null;
        return (
          <div key={group.label} className="mb-4">
            {!collapsed ? <p className="mb-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-subtle">{group.label}</p> : <div className="mx-2 mb-2 h-px bg-border" aria-hidden />}
            <ul className="space-y-0.5">
              {items.map((item) => (
                <NavLink key={item.href} item={item} collapsed={collapsed} onNavigate={onNavigate} />
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

export function Sidebar() {
  const collapsed = useUi((s) => s.sidebarCollapsed);
  const toggle = useUi((s) => s.toggleSidebar);
  return (
    <aside className={cn("sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-border bg-surface/60 transition-[width] duration-200 lg:flex", collapsed ? "w-[64px]" : "w-[248px]")} aria-label="Sidebar">
      <div className={cn("flex h-14 items-center border-b border-border px-3", collapsed ? "justify-center" : "justify-between")}>
        <Link href="/overview" className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" aria-label="OpsPilot home">
          <BrandWordmark compact={collapsed} />
        </Link>
      </div>
      <NavGroups collapsed={collapsed} />
      <div className="border-t border-border p-2">
        <button type="button" onClick={toggle} className="flex h-8 w-full items-center justify-center gap-2 rounded-md text-xs text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-pressed={collapsed}>
          {collapsed ? <ChevronsRight className="h-4 w-4" aria-hidden /> : <ChevronsLeft className="h-4 w-4" aria-hidden />}
          {!collapsed ? "Collapse" : null}
        </button>
      </div>
    </aside>
  );
}

export function MobileSidebar() {
  const open = useUi((s) => s.mobileNavOpen);
  const setOpen = useUi((s) => s.setMobileNavOpen);
  const tenant = useSession((s) => s.tenant);
  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/55 backdrop-blur-sm animate-fade-in lg:hidden" />
        <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 flex w-[280px] max-w-[85vw] flex-col border-r border-border bg-surface shadow-pop animate-slide-in-left focus:outline-none lg:hidden" aria-describedby={undefined}>
          <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
          <div className="flex h-14 items-center justify-between border-b border-border px-3">
            <BrandWordmark />
            <DialogPrimitive.Close className="rounded-md p-1.5 text-fg-muted hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" aria-label="Close navigation">
              <X className="h-4 w-4" aria-hidden />
            </DialogPrimitive.Close>
          </div>
          <NavGroups collapsed={false} onNavigate={() => setOpen(false)} />
          {tenant ? (
            <div className="border-t border-border p-3">
              <p className="truncate text-xs font-medium text-fg">{tenant.name}</p>
              <p className="truncate text-[11px] text-fg-subtle">
                {tenant.slug} · {tenant.plan} plan
              </p>
            </div>
          ) : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
