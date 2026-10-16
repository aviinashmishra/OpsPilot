"use client";

import { useEffect, useState } from "react";

export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(handle);
  }, [value, delay]);
  return debounced;
}

/** Re-renders every `ms` milliseconds (for countdowns / relative times). */
export function useTick(ms = 30_000): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const handle = window.setInterval(() => setTick((t) => t + 1), ms);
    return () => window.clearInterval(handle);
  }, [ms]);
  return tick;
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const media = window.matchMedia(query);
    setMatches(media.matches);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}
