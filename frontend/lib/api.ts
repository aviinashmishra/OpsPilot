import { useSession } from "@/lib/session";
import type { ErrorBody, JsonObject } from "@/lib/types";

/**
 * Defaults to the dashboard's own origin (`/api/v1`, served by the proxy route in
 * app/api/v1/[...path]). Set NEXT_PUBLIC_API_URL only to bypass the proxy and call
 * an API on another origin directly (that API must then allow this origin via CORS).
 */
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || "/api/v1").replace(/\/+$/, "");

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: JsonObject;
  readonly correlationId: string | null;

  constructor(status: number, body: Partial<ErrorBody> | null, fallbackMessage: string, correlationHeader: string | null) {
    super(body?.message ?? fallbackMessage);
    this.name = "ApiError";
    this.status = status;
    this.code = body?.code ?? (status === 0 ? "network_error" : "http_error");
    this.details = body?.details ?? {};
    this.correlationId = body?.correlation_id ?? correlationHeader;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

/** Human readable message for any thrown value. */
export function errorMessage(error: unknown): string {
  if (isApiError(error)) {
    const validation = error.details?.errors;
    if (error.code === "validation_failed" && Array.isArray(validation) && validation.length > 0) {
      const first = validation[0] as { loc?: unknown[]; msg?: string };
      const loc = Array.isArray(first.loc) ? first.loc.filter((p) => p !== "body").join(".") : "";
      return loc ? `${error.message}: ${loc} - ${first.msg ?? ""}` : error.message;
    }
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong";
}

export type QueryParams = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  query?: QueryParams;
  headers?: Record<string, string>;
  /** Set false for public endpoints (login, demo accounts). */
  auth?: boolean;
  signal?: AbortSignal;
}

let unauthorizedHandler: (() => void) | null = null;

/** Registered by the auth provider; invoked whenever the API answers 401. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export function buildUrl(path: string, query?: QueryParams): string {
  const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost:3000";
  const url = new URL(`${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`, origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, headers = {}, auth = true, signal } = options;
  const requestHeaders: Record<string, string> = { Accept: "application/json", ...headers };
  if (body !== undefined) requestHeaders["Content-Type"] = "application/json";
  if (auth) {
    const token = useSession.getState().token;
    if (token) requestHeaders.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers: requestHeaders,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, { code: "network_error", message: `Cannot reach the dashboard server at ${typeof window !== "undefined" ? window.location.origin : ""}${API_BASE_URL}. Is it still running?` }, "Network error", null);
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const errorBody = (data as { error?: Partial<ErrorBody> } | null)?.error ?? null;
    const apiError = new ApiError(response.status, errorBody, response.statusText || `HTTP ${response.status}`, response.headers.get("X-Correlation-ID"));
    if (response.status === 401 && auth) {
      useSession.getState().clear();
      unauthorizedHandler?.();
    }
    throw apiError;
  }
  return data as T;
}

/** Generates an RFC4122-ish random id for Idempotency-Key headers. */
export function idempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}
