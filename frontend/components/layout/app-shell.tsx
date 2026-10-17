"use client";

import { Suspense, type ReactNode } from "react";

import { AuthGuard } from "@/components/layout/auth-guard";
import { CommandPalette } from "@/components/layout/command-palette";
import { PageAccessGate } from "@/components/layout/page-access";
import { MobileSidebar, Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { GlobalStartWorkflowDialog } from "@/components/workflows/start-workflow-dialog";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <AuthGuard>
      <div className="flex min-h-dvh page-bg">
        <Suspense fallback={null}>
          <Sidebar />
          <MobileSidebar />
        </Suspense>
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar />
          <main id="main" className="flex-1 px-4 py-5 sm:px-6 lg:px-8 lg:py-6">
            <div className="mx-auto w-full max-w-[1480px] animate-slide-up">
              <PageAccessGate>{children}</PageAccessGate>
            </div>
          </main>
        </div>
        <CommandPalette />
        <GlobalStartWorkflowDialog />
      </div>
    </AuthGuard>
  );
}
