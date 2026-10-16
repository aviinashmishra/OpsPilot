"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Toaster } from "sonner";

import { ThemeSync, useTheme } from "@/components/providers/theme-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { isApiError, setUnauthorizedHandler } from "@/lib/api";
import { useSession } from "@/lib/session";
import { hydrateUiPreferences } from "@/lib/ui-store";

function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        gcTime: 5 * 60_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (isApiError(error) && error.status > 0 && error.status < 500) return false;
          return failureCount < 2;
        },
      },
      mutations: { retry: 0 },
    },
  });
}

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  const router = useRouter();
  const pathname = usePathname();
  const theme = useTheme((s) => s.theme);

  useEffect(() => {
    hydrateUiPreferences();
    void useSession.persist.rehydrate();
    useSession.getState().setHydrated();
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      queryClient.clear();
      if (pathname !== "/login") router.replace(`/login?next=${encodeURIComponent(pathname)}&reason=expired`);
    });
    return () => setUnauthorizedHandler(null);
  }, [queryClient, router, pathname]);

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={200} skipDelayDuration={300}>
        <ThemeSync />
        {children}
        <Toaster theme={theme} position="bottom-right" closeButton richColors toastOptions={{ className: "font-sans" }} />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
