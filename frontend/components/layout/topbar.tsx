"use client";

import { ChevronDown, CircleHelp, LogOut, Menu, Moon, Search, ShieldAlert, Sun, User } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { useTheme } from "@/components/providers/theme-provider";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Kbd } from "@/components/ui/misc";
import { Tip } from "@/components/ui/tooltip";
import { helpHrefFor } from "@/lib/help/routes";
import { useSession } from "@/lib/session";
import { useUi } from "@/lib/ui-store";
import { cn } from "@/lib/utils";

/** ⌘ on Apple devices, Ctrl elsewhere (decided after mount to keep server and client markup equal). */
function ModKey() {
  const [mac, setMac] = useState(false);
  useEffect(() => setMac(/Mac|iPhone|iPad/.test(navigator.userAgent)), []);
  return <Kbd>{mac ? "⌘" : "Ctrl"}</Kbd>;
}

export function ThemeToggle({ className }: { className?: string }) {
  const theme = useTheme((s) => s.theme);
  const toggle = useTheme((s) => s.toggle);
  const next = theme === "dark" ? "light" : "dark";
  return (
    <Tip content={`Switch to ${next} mode`}>
      <Button variant="ghost" size="icon" onClick={toggle} aria-label={`Switch to ${next} mode`} className={className}>
        {theme === "dark" ? <Sun className="h-4 w-4" aria-hidden /> : <Moon className="h-4 w-4" aria-hidden />}
      </Button>
    </Tip>
  );
}

/** Opens the help article for the current page (or the Help center). */
export function HelpButton() {
  const pathname = usePathname() ?? "";
  const href = helpHrefFor(pathname);
  const label = href === "/help" ? "Help center" : "Help for this page";
  return (
    <Tip content={label}>
      <Link href={href} className={buttonVariants({ variant: "ghost", size: "icon" })} aria-label={label} data-testid="help-button">
        <CircleHelp className="h-4 w-4" aria-hidden />
      </Link>
    </Tip>
  );
}

export function UserMenu() {
  const user = useSession((s) => s.user);
  const clear = useSession((s) => s.clear);
  const router = useRouter();
  if (!user) return null;
  const initials = user.full_name
    .split(" ")
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button type="button" className="flex h-9 items-center gap-2 rounded-md border border-transparent px-1.5 text-sm transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" aria-label="Account menu">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-2 text-[11px] font-semibold text-white" aria-hidden>
            {initials || <User className="h-3.5 w-3.5" />}
          </span>
          <span className="hidden max-w-[140px] truncate text-fg md:inline">{user.full_name}</span>
          <ChevronDown className="hidden h-3.5 w-3.5 text-fg-subtle md:inline" aria-hidden />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel>
          <p className="text-sm font-medium text-fg">{user.full_name}</p>
          <p className="truncate text-xs font-normal text-fg-muted">{user.email}</p>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {user.roles.map((role) => (
              <Badge key={role} size="sm" tone="accent">
                {role}
              </Badge>
            ))}
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/admin">
            <User className="h-4 w-4 text-fg-muted" aria-hidden /> Workspace settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          destructive
          onSelect={() => {
            clear();
            toast.success("Signed out");
            router.replace("/login");
          }}
        >
          <LogOut className="h-4 w-4" aria-hidden /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Topbar() {
  const tenant = useSession((s) => s.tenant);
  const setMobileNavOpen = useUi((s) => s.setMobileNavOpen);
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b border-border px-3 glass sm:px-4 lg:px-6">
      <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileNavOpen(true)} aria-label="Open navigation">
        <Menu className="h-5 w-5" aria-hidden />
      </Button>
      <div className="flex min-w-0 items-center gap-2">
        <p className="truncate text-sm font-medium text-fg">{tenant?.name ?? "OpsPilot"}</p>
        {tenant ? (
          <Badge size="sm" tone="neutral" className="hidden sm:inline-flex">
            {tenant.plan}
          </Badge>
        ) : null}
        {tenant?.emergency_disabled ? (
          <Badge size="sm" tone="danger" icon={<ShieldAlert className="h-3 w-3" aria-hidden />}>
            Emergency disable active
          </Badge>
        ) : null}
      </div>
      <div className="ml-auto flex items-center gap-1 sm:gap-2">
        <button
          type="button"
          onClick={() => setPaletteOpen(true)}
          className={cn("flex h-9 items-center gap-2 rounded-md border border-border bg-surface px-2.5 text-sm text-fg-muted transition-colors hover:border-border-strong hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 sm:w-56 lg:w-72")}
          aria-label="Open command palette"
        >
          <Search className="h-4 w-4" aria-hidden />
          <span className="hidden flex-1 text-left sm:inline">Search or jump to…</span>
          <span className="hidden items-center gap-0.5 sm:flex" aria-hidden>
            <ModKey />
            <Kbd>K</Kbd>
          </span>
        </button>
        <HelpButton />
        <ThemeToggle />
        <UserMenu />
      </div>
    </header>
  );
}
