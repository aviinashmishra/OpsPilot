"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { BrandMark } from "@/components/layout/brand";
import { isSessionValid, useSession } from "@/lib/session";

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const hydrated = useSession((s) => s.hydrated);
  const token = useSession((s) => s.token);
  const expiresAt = useSession((s) => s.expiresAt);
  const valid = isSessionValid({ token, expiresAt });

  useEffect(() => {
    if (!hydrated) return;
    if (!valid) {
      useSession.getState().clear();
      router.replace(`/login?next=${encodeURIComponent(pathname || "/overview")}`);
    }
  }, [hydrated, valid, router, pathname]);

  if (!hydrated || !valid) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-bg" role="status" aria-live="polite">
        <div className="flex flex-col items-center gap-3 text-fg-muted">
          <BrandMark className="h-10 w-10 animate-pulse" />
          <p className="text-sm">{hydrated ? "Redirecting to sign in…" : "Loading your workspace…"}</p>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
