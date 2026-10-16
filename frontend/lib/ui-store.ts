"use client";

import { create } from "zustand";

interface UiState {
  sidebarCollapsed: boolean;
  mobileNavOpen: boolean;
  paletteOpen: boolean;
  startWorkflowOpen: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
  setMobileNavOpen: (open: boolean) => void;
  setPaletteOpen: (open: boolean) => void;
  setStartWorkflowOpen: (open: boolean) => void;
}

const SIDEBAR_KEY = "opspilot.sidebar.collapsed";

function readSidebar(): boolean {
  try {
    return typeof window !== "undefined" && window.localStorage.getItem(SIDEBAR_KEY) === "1";
  } catch {
    return false;
  }
}

export const useUi = create<UiState>((set, get) => ({
  sidebarCollapsed: false,
  mobileNavOpen: false,
  paletteOpen: false,
  startWorkflowOpen: false,
  setSidebarCollapsed: (collapsed) => {
    try {
      window.localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
    } catch {
      // ignore storage failures
    }
    set({ sidebarCollapsed: collapsed });
  },
  toggleSidebar: () => get().setSidebarCollapsed(!get().sidebarCollapsed),
  setMobileNavOpen: (open) => set({ mobileNavOpen: open }),
  setPaletteOpen: (open) => set({ paletteOpen: open }),
  setStartWorkflowOpen: (open) => set({ startWorkflowOpen: open }),
}));

export function hydrateUiPreferences(): void {
  useUi.setState({ sidebarCollapsed: readSidebar() });
}
