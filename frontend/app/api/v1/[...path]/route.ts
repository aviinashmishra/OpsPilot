/**
 * Same-origin proxy: the browser talks only to the dashboard's own origin
 * (`/api/v1/*`), and this route forwards to the OpsPilot API server.
 *
 * Why: it removes every localhost / 127.0.0.1 / LAN-IP / CORS mismatch, and the
 * API location is configured at *runtime* via OPSPILOT_API_ORIGIN (default
 * http://127.0.0.1:8000) instead of being baked into the bundle at build time.
 */
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
// Serverless hosts (Vercel) cut functions off at 10 s by default; agent runs with a real LLM take longer.
export const maxDuration = 60;

const API_ORIGIN = (process.env.OPSPILOT_API_ORIGIN ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
const FORWARD_REQUEST_HEADERS = ["authorization", "content-type", "accept", "idempotency-key", "x-api-key", "x-correlation-id", "x-opspilot-signature", "x-hub-signature-256", "x-shopify-hmac-sha256", "x-shopify-topic"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "x-correlation-id", "retry-after", "content-disposition", "cache-control"];

async function proxy(request: NextRequest, { params }: { params: { path: string[] } }): Promise<Response> {
  const path = (params.path ?? []).map(encodeURIComponent).join("/");
  const target = `${API_ORIGIN}/api/v1/${path}${request.nextUrl.search}`;
  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const forwardedFor = request.headers.get("x-forwarded-for") ?? request.ip;
  if (forwardedFor) headers.set("x-forwarded-for", forwardedFor);

  const hasBody = !["GET", "HEAD"].includes(request.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return Response.json(
      {
        error: {
          code: "api_unreachable",
          message: `The dashboard cannot reach the OpsPilot API at ${API_ORIGIN}. Start it with scripts\\start.ps1 (or python -m app.cli serve) and retry.`,
          details: { api_origin: API_ORIGIN },
          correlation_id: null,
        },
      },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers();
  for (const name of FORWARD_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  if (upstream.status === 204 || upstream.status === 304) return new Response(null, { status: upstream.status, headers: responseHeaders });
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as PUT, proxy as DELETE };
