"use client";

import { useCallback } from "react";

import { useSession } from "@/lib/session";

/** Mirrors backend Principal.has(): "*" grants everything except platform:admin, "scope:*" grants a whole scope. */
export function hasPermission(permissions: readonly string[] | null | undefined, permission: string): boolean {
  if (!permissions || permissions.length === 0) return false;
  if (permission === "platform:admin") return permissions.includes(permission); // never implied by wildcards
  if (permissions.includes("*") || permissions.includes(permission)) return true;
  const scope = permission.split(":")[0];
  return permissions.includes(`${scope}:*`);
}

export function useCan(): (permission: string) => boolean {
  const permissions = useSession((s) => s.user?.permissions);
  return useCallback((permission: string) => hasPermission(permissions, permission), [permissions]);
}

export function usePermission(permission: string): boolean {
  const permissions = useSession((s) => s.user?.permissions);
  return hasPermission(permissions, permission);
}
