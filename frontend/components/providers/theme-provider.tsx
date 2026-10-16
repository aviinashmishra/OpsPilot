"use client";

import { useEffect } from "react";
import { create } from "zustand";

export type Theme = "dark" | "light";

export const THEME_STORAGE_KEY = "opspilot.theme";

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggle: () => void;
}

function applyTheme(theme: Theme): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // storage unavailable (private mode etc.)
  }
}

export const useTheme = create<ThemeState>((set, get) => ({
  theme: "dark",
  setTheme: (theme) => {
    applyTheme(theme);
    set({ theme });
  },
  toggle: () => get().setTheme(get().theme === "dark" ? "light" : "dark"),
}));

/**
 * Inline script executed before paint: picks the stored theme, else the OS
 * preference, else dark. Keeps SSR markup theme-agnostic (html has
 * suppressHydrationWarning).
 */
export const themeInitScript = `(function(){try{var k='${THEME_STORAGE_KEY}';var s=localStorage.getItem(k);var t=(s==='light'||s==='dark')?s:(window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');document.documentElement.setAttribute('data-theme',t);}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();`;

export function ThemeSync() {
  useEffect(() => {
    const current = document.documentElement.getAttribute("data-theme");
    if (current === "light" || current === "dark") useTheme.setState({ theme: current });

    const media = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = (event: MediaQueryListEvent) => {
      let stored: string | null = null;
      try {
        stored = window.localStorage.getItem(THEME_STORAGE_KEY);
      } catch {
        stored = null;
      }
      if (stored === "light" || stored === "dark") return; // explicit choice wins
      const next: Theme = event.matches ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      useTheme.setState({ theme: next });
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return null;
}
