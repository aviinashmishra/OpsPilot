import { clsx, type ClassValue } from "clsx";
import { format, formatDistanceToNowStrict, isValid, parseISO } from "date-fns";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** ISO date-time without a zone designator, e.g. "2026-10-16T07:24:00.653484". */
const NAIVE_ISO_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

export function parseDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  // Some API routes serialise UTC timestamps without "Z"; treat naive date-times as UTC
  // (date-only strings keep local-midnight semantics).
  const date = value instanceof Date ? value : parseISO(NAIVE_ISO_DATETIME.test(value) ? `${value}Z` : value);
  return isValid(date) ? date : null;
}

/** Relative time, e.g. "3 minutes ago" / "in 2 hours". */
export function fmtRelative(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return formatDistanceToNowStrict(date, { addSuffix: true });
}

/** Full timestamp for hover titles. */
export function fmtDateTime(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return format(date, "yyyy-MM-dd HH:mm:ss");
}

export function fmtIso(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  return date ? date.toISOString() : "";
}

export function fmtShortDate(value: string | Date | null | undefined): string {
  const date = parseDate(value);
  if (!date) return "—";
  return format(date, "MMM d");
}

const intFormatter = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const compactFormatter = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return intFormatter.format(value);
}

export function fmtCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return compactFormatter.format(value);
}

export function fmtNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(value);
}

/** Currency: 4 decimals for small AI costs (< $1), 2 otherwise. */
export function fmtCurrency(value: number | null | undefined, opts: { precise?: boolean } = {}): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  const digits = opts.precise || (abs > 0 && abs < 1) ? 4 : 2;
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}

/** Ratio (0..1) as percentage. */
export function fmtPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Minutes → hours string. */
export function fmtHours(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) return "—";
  const hours = minutes / 60;
  if (hours < 1) return `${minutes.toFixed(0)} min`;
  return `${hours.toFixed(1)} h`;
}

export function fmtMs(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value < 1000) return `${Math.round(value)} ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(1)} s`;
  return `${(value / 60_000).toFixed(1)} min`;
}

export function fmtMinutes(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (value < 60) return `${value.toFixed(1)} min`;
  return `${(value / 60).toFixed(1)} h`;
}

export function fmtBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function shortId(id: string | null | undefined, length = 8): string {
  if (!id) return "—";
  return id.length > length ? id.slice(0, length) : id;
}

export function titleCase(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function truncate(value: string, max = 80): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1)}…`;
}

export function safeJsonParse(text: string): { ok: true; value: unknown } | { ok: false; error: string } {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : "Invalid JSON" };
  }
}

export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall through to the legacy approach
  }
  try {
    const el = document.createElement("textarea");
    el.value = text;
    el.setAttribute("readonly", "");
    el.style.position = "fixed";
    el.style.opacity = "0";
    document.body.appendChild(el);
    el.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(el);
    return ok;
  } catch {
    return false;
  }
}

/** Countdown text for an expiry, e.g. "expires in 3 hours" / "expired". */
export function expiresIn(value: string | null | undefined): { text: string; expired: boolean; soon: boolean } {
  const date = parseDate(value);
  if (!date) return { text: "—", expired: false, soon: false };
  const diff = date.getTime() - Date.now();
  if (diff <= 0) return { text: "expired", expired: true, soon: false };
  return { text: `in ${formatDistanceToNowStrict(date)}`, expired: false, soon: diff < 2 * 60 * 60 * 1000 };
}

/** Model family behind a live Copilot mode ("Claude", "Gemini"), or null for the offline planner. */
export function copilotModelLabel(mode: string | null | undefined): string | null {
  if (!mode || mode === "offline_planner") return null;
  return mode === "claude" ? "Claude" : mode === "gemini" ? "Gemini" : mode === "openai" ? "OpenAI" : mode;
}
