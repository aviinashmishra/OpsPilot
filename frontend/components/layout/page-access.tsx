"use client";

import { Lock } from "lucide-react";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { ButtonLink } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/states";
import { ALL_NAV_ITEMS, type NavItem } from "@/lib/constants";
import { useCan } from "@/lib/permissions";

function itemFor(pathname: string): NavItem | undefined {
  return ALL_NAV_ITEMS.find((item) => (item.match ? item.match(pathname) : pathname === item.href || pathname.startsWith(`${item.href}/`)));
}

/**
 * Pages use the same permission map as the sidebar: a page someone opens by URL, bookmark or link
 * without the permission explains itself instead of showing failed requests.
 */
export function PageAccessGate({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";
  const can = useCan();
  const item = itemFor(pathname);
  if (!item?.permissions || item.permissions.some((p) => can(p))) return <>{children}</>;
  const home = ALL_NAV_ITEMS.find((i) => !i.permissions || i.permissions.some((p) => can(p)));
  return (
    <EmptyState
      icon={Lock}
      title={`You don't have access to ${item.label}`}
      description="Your role doesn't include this page. Ask a workspace administrator if you need it."
      action={home ? <ButtonLink href={home.href} variant="outline" size="sm">Go to {home.label}</ButtonLink> : undefined}
      className="mt-6"
    />
  );
}
