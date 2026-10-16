"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, KeyRound, Send, ShieldAlert, Wand2, XCircle } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/input";
import { JsonEditor } from "@/components/ui/json-editor";
import { JsonViewer } from "@/components/ui/json-viewer";
import { Switch } from "@/components/ui/switch";
import { api, errorMessage } from "@/lib/api";
import { qk } from "@/lib/queries";
import { schemaDefaults } from "@/lib/schema-defaults";
import type { CustomToolIn, CustomToolOut, CustomToolPatch, CustomToolTestIn, CustomToolTestOut, HttpMethod, JsonObject, JsonSchema, RiskLevel } from "@/lib/types";
import { cn, fmtMs, isPlainObject, prettyJson, safeJsonParse } from "@/lib/utils";

const METHODS: HttpMethod[] = ["GET", "POST", "PUT", "PATCH", "DELETE"];
const RISKS: RiskLevel[] = ["low", "medium", "high", "critical"];
const NAME_RE = /^[a-z][a-z0-9_]{1,47}$/;
const PLACEHOLDER_RE = /\{([a-zA-Z_][a-zA-Z0-9_]*)\}/g;

export const SCHEMA_TEMPLATE = prettyJson({
  type: "object",
  properties: {
    order_id: { type: "string", description: "Order number, e.g. ORD-5002" },
  },
  required: ["order_id"],
});

interface FormState {
  name: string;
  description: string;
  method: HttpMethod;
  url: string;
  headers: string;
  authHeader: string;
  secret: string;
  clearSecret: boolean;
  schema: string;
  sideEffect: boolean;
  risk: RiskLevel;
  timeout: string;
  enabled: boolean;
}

function initialState(tool: CustomToolOut | null): FormState {
  if (!tool) {
    return { name: "", description: "", method: "GET", url: "", headers: "{}", authHeader: "", secret: "", clearSecret: false, schema: SCHEMA_TEMPLATE, sideEffect: false, risk: "low", timeout: "15", enabled: true };
  }
  return {
    name: tool.name,
    description: tool.description,
    method: (METHODS as string[]).includes(tool.method) ? (tool.method as HttpMethod) : "GET",
    url: tool.url_template,
    headers: prettyJson(tool.headers ?? {}),
    authHeader: tool.auth_header_name ?? "",
    secret: "",
    clearSecret: false,
    schema: prettyJson(tool.input_schema ?? { type: "object", properties: {} }),
    sideEffect: tool.side_effect,
    risk: (RISKS as string[]).includes(tool.risk_level) ? (tool.risk_level as RiskLevel) : "low",
    timeout: String(tool.timeout_seconds ?? 15),
    enabled: tool.enabled,
  };
}

type Errors = Partial<Record<"name" | "description" | "url" | "headers" | "schema" | "timeout" | "authHeader", string>>;

interface Validated {
  errors: Errors;
  headers: Record<string, string>;
  schema: JsonObject;
  missingPlaceholders: string[];
}

function validate(form: FormState, isEdit: boolean): Validated {
  const errors: Errors = {};
  if (!isEdit && !NAME_RE.test(form.name)) errors.name = "2–48 characters: lowercase letters, digits and underscores, starting with a letter.";
  if (form.description.trim().length < 5) errors.description = "Describe what the tool does (at least 5 characters) — the Copilot reads this to decide when to call it.";

  let headers: Record<string, string> = {};
  const h = safeJsonParse(form.headers.trim() || "{}");
  if (!h.ok || !isPlainObject(h.value)) errors.headers = "Headers must be a JSON object of strings.";
  else if (Object.values(h.value).some((v) => typeof v !== "string")) errors.headers = "Every header value must be a string.";
  else headers = h.value as Record<string, string>;

  let schema: JsonObject = {};
  const s = safeJsonParse(form.schema.trim() || "{}");
  if (!s.ok || !isPlainObject(s.value)) errors.schema = "The input schema must be a JSON object.";
  else if ((s.value.type ?? "object") !== "object") errors.schema = 'The input schema must describe an object ("type": "object").';
  else schema = s.value;

  const placeholders = Array.from(form.url.matchAll(PLACEHOLDER_RE)).map((m) => m[1]);
  const props = isPlainObject(schema.properties) ? schema.properties : {};
  const missingPlaceholders = Array.from(new Set(placeholders.filter((p) => !(p in props))));

  const url = form.url.trim();
  if (!url) errors.url = "Enter the endpoint URL.";
  else {
    try {
      const parsed = new URL(url.replace(/[{}]/g, "x"));
      if (parsed.protocol !== "https:" && parsed.protocol !== "http:") errors.url = "Use an absolute http(s) URL.";
      else if (/[{}]/.test(url.split("/")[2] ?? "")) errors.url = "The host part cannot contain {placeholders}.";
    } catch {
      errors.url = "Use an absolute http(s) URL, e.g. https://api.example.com/v1/orders/{order_id}";
    }
  }
  if (!errors.url && missingPlaceholders.length > 0 && !errors.schema) errors.url = `Declare ${missingPlaceholders.map((p) => `{${p}}`).join(", ")} in input_schema.properties.`;

  const timeout = Number(form.timeout);
  if (!Number.isInteger(timeout) || timeout < 1 || timeout > 60) errors.timeout = "1–60 seconds.";
  if (form.authHeader && !/^[A-Za-z0-9-]{1,100}$/.test(form.authHeader)) errors.authHeader = "Letters, digits and dashes only (e.g. Authorization, X-Api-Key).";
  return { errors, headers, schema, missingPlaceholders };
}

export function CustomToolDialog({ open, onOpenChange, tool }: { open: boolean; onOpenChange: (open: boolean) => void; tool: CustomToolOut | null }) {
  const queryClient = useQueryClient();
  const isEdit = tool !== null;
  const [form, setForm] = useState<FormState>(() => initialState(tool));
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (open) {
      setForm(initialState(tool));
      setSubmitted(false);
    }
  }, [open, tool]);

  const v = useMemo(() => validate(form, isEdit), [form, isEdit]);
  const hasErrors = Object.keys(v.errors).length > 0;
  const show = (key: keyof Errors) => (submitted ? v.errors[key] : undefined);
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));

  const save = useMutation({
    mutationFn: () => {
      const common = {
        description: form.description.trim(),
        method: form.method,
        url_template: form.url.trim(),
        headers: v.headers,
        auth_header_name: form.authHeader.trim() || null,
        input_schema: v.schema,
        side_effect: form.sideEffect,
        risk_level: form.risk,
        timeout_seconds: Number(form.timeout),
        enabled: form.enabled,
      };
      if (isEdit && tool) {
        const patch: CustomToolPatch = { ...common };
        if (form.clearSecret) patch.auth_secret = "";
        else if (form.secret) patch.auth_secret = form.secret;
        return api<CustomToolOut>(`/custom-tools/${encodeURIComponent(tool.id)}`, { method: "PATCH", body: patch });
      }
      const body: CustomToolIn = { name: form.name.trim(), ...common, auth_secret: form.secret || null };
      return api<CustomToolOut>("/custom-tools", { method: "POST", body });
    },
    onSuccess: (saved) => {
      toast.success(isEdit ? `Saved ${saved.name}` : `Custom tool ${saved.name} created`, { description: saved.side_effect ? "Side-effecting: calls from the Copilot wait for approval." : "Read-only: the Copilot can call it directly." });
      void queryClient.invalidateQueries({ queryKey: qk.customTools });
      void queryClient.invalidateQueries({ queryKey: qk.toolCatalog });
      void queryClient.invalidateQueries({ queryKey: qk.copilotStatus });
      onOpenChange(false);
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (hasErrors) return;
    save.mutate();
  };

  const addPlaceholders = () => {
    const s = safeJsonParse(form.schema.trim() || "{}");
    if (!s.ok || !isPlainObject(s.value)) return;
    const schema = { type: "object", ...s.value } as JsonObject;
    const props = isPlainObject(schema.properties) ? { ...schema.properties } : {};
    const required = Array.isArray(schema.required) ? [...(schema.required as string[])] : [];
    for (const p of v.missingPlaceholders) {
      props[p] = { type: "string" };
      if (!required.includes(p)) required.push(p);
    }
    set("schema", prettyJson({ ...schema, properties: props, required }));
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !save.isPending && onOpenChange(next)}>
      {/* overflow-clip: the shell must never be scrolled by focus / scrollIntoView, only the body */}
      <DialogContent size="lg" className="overflow-clip">
        <form onSubmit={onSubmit} className="flex max-h-[calc(100dvh-2rem)] min-h-0 flex-1 flex-col" noValidate>
          <DialogHeader>
            <DialogTitle>{isEdit ? `Edit ${tool?.name}` : "New custom tool"}</DialogTitle>
            <DialogDescription>Register a REST endpoint the Copilot can call. {"{placeholders}"} in the URL are filled from the tool input.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            {save.isError ? (
              <div role="alert" className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
                <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                <span>{errorMessage(save.error)}</span>
              </div>
            ) : null}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Name" htmlFor="ct-name" required error={show("name")} hint={isEdit ? "Names can't be changed." : "Lowercase slug, e.g. order_lookup"}>
                <Input id="ct-name" value={form.name} onChange={(e) => set("name", e.target.value.toLowerCase())} disabled={isEdit} placeholder="order_lookup" aria-invalid={Boolean(show("name"))} autoComplete="off" className="font-mono" />
              </Field>
              <Field label="Timeout (seconds)" htmlFor="ct-timeout" error={show("timeout")}>
                <Input id="ct-timeout" type="number" min={1} max={60} value={form.timeout} onChange={(e) => set("timeout", e.target.value)} aria-invalid={Boolean(show("timeout"))} />
              </Field>
            </div>
            <Field label="Description" htmlFor="ct-desc" required error={show("description")}>
              <Textarea id="ct-desc" rows={2} value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="Looks up an order in our legacy order system by order number." aria-invalid={Boolean(show("description"))} className="min-h-[64px]" />
            </Field>
            <div className="grid gap-4 sm:grid-cols-[120px_1fr]">
              <Field label="Method" htmlFor="ct-method">
                <NativeSelect id="ct-method" value={form.method} onChange={(e) => set("method", e.target.value as HttpMethod)}>
                  {METHODS.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field
                label="URL template"
                htmlFor="ct-url"
                required
                error={show("url")}
                hint={
                  v.missingPlaceholders.length > 0 && !v.errors.schema ? (
                    <button type="button" onClick={addPlaceholders} className="inline-flex items-center gap-1 text-accent hover:underline">
                      <Wand2 className="h-3 w-3" aria-hidden /> Add {v.missingPlaceholders.map((p) => `{${p}}`).join(", ")} to the input schema
                    </button>
                  ) : (
                    "https only — private, loopback and link-local destinations are blocked."
                  )
                }
              >
                <Input id="ct-url" value={form.url} onChange={(e) => set("url", e.target.value)} placeholder="https://api.example.com/v1/orders/{order_id}" aria-invalid={Boolean(show("url"))} className="font-mono text-xs" autoComplete="off" spellCheck={false} />
              </Field>
            </div>
            {submitted && v.missingPlaceholders.length > 0 && v.errors.url ? (
              <button type="button" onClick={addPlaceholders} className="-mt-2 inline-flex items-center gap-1 text-xs text-accent hover:underline">
                <Wand2 className="h-3 w-3" aria-hidden /> Add the missing placeholders to the schema
              </button>
            ) : null}

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Auth header name" htmlFor="ct-auth-header" error={show("authHeader")} hint="Optional, e.g. Authorization or X-Api-Key">
                <Input id="ct-auth-header" value={form.authHeader} onChange={(e) => set("authHeader", e.target.value)} placeholder="Authorization" autoComplete="off" />
              </Field>
              <Field
                label={
                  <span className="inline-flex items-center gap-1.5">
                    Auth secret
                    {isEdit && tool?.has_secret && !form.clearSecret ? (
                      <Badge size="sm" tone="success" icon={<KeyRound className="h-3 w-3" aria-hidden />}>
                        secret set
                      </Badge>
                    ) : null}
                  </span>
                }
                htmlFor="ct-secret"
                hint={isEdit && tool?.has_secret ? "Write-only. Leave blank to keep the stored secret." : "Write-only: stored encrypted, never shown again."}
              >
                <Input id="ct-secret" type="password" value={form.secret} onChange={(e) => set("secret", e.target.value)} placeholder={isEdit && tool?.has_secret ? "•••••••• (unchanged)" : "Bearer sk_live_…"} autoComplete="new-password" disabled={form.clearSecret} />
              </Field>
            </div>
            {isEdit && tool?.has_secret ? (
              <label className="-mt-2 flex items-center gap-2 text-xs text-fg-muted">
                <input type="checkbox" checked={form.clearSecret} onChange={(e) => set("clearSecret", e.target.checked)} className="h-3.5 w-3.5 accent-[hsl(var(--danger))]" /> Remove the stored secret
              </label>
            ) : null}

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="space-y-1">
                <JsonEditor label="Input schema (JSON Schema)" value={form.schema} onChange={(value) => set("schema", value)} rows={10} />
                {show("schema") ? <p className="text-xs text-danger">{show("schema")}</p> : <p className="text-[11px] text-fg-subtle">The Copilot fills these fields; inputs are validated before any request is sent.</p>}
              </div>
              <div className="space-y-1">
                <JsonEditor label="Static headers" value={form.headers} onChange={(value) => set("headers", value)} rows={10} placeholder='{"Accept": "application/json"}' />
                {show("headers") ? <p className="text-xs text-danger">{show("headers")}</p> : <p className="text-[11px] text-fg-subtle">Non-secret headers sent with every call.</p>}
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className={cn("flex items-start justify-between gap-3 rounded-md border px-3 py-2.5", form.sideEffect ? "border-warning/40 bg-warning/5" : "border-border bg-surface-2/50")}>
                <span>
                  <span className="block text-sm font-medium text-fg">Has side effects</span>
                  <span className="block text-xs text-fg-muted">Changes data outside OpsPilot. Copilot calls then wait for human approval.</span>
                </span>
                <Switch checked={form.sideEffect} onCheckedChange={(checked) => setForm((f) => ({ ...f, sideEffect: checked, risk: checked && f.risk === "low" ? "medium" : f.risk }))} aria-label="Has side effects" />
              </label>
              <div className="space-y-3">
                <Field label="Risk level" htmlFor="ct-risk" hint={form.sideEffect && form.risk === "low" ? "Side-effecting tools are at least medium risk." : undefined}>
                  <NativeSelect id="ct-risk" value={form.risk} onChange={(e) => set("risk", e.target.value as RiskLevel)}>
                    {RISKS.map((r) => (
                      <option key={r} value={r} disabled={form.sideEffect && r === "low"}>
                        {r}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
                <label className="flex items-center justify-between gap-3 text-sm">
                  <span className="text-fg">Enabled</span>
                  <Switch checked={form.enabled} onCheckedChange={(checked) => set("enabled", checked)} aria-label="Enabled" />
                </label>
              </div>
            </div>
          </DialogBody>
          <DialogFooter className="flex-row justify-end">
            {submitted && hasErrors ? (
              <p className="mr-auto self-center text-xs text-danger" role="alert">
                Fix the highlighted fields.
              </p>
            ) : null}
            <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={save.isPending}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={save.isPending}>
              {isEdit ? "Save changes" : "Create tool"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function CustomToolTestDialog({ tool, onOpenChange }: { tool: CustomToolOut | null; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const defaults = useMemo(() => prettyJson(schemaDefaults((tool?.input_schema ?? {}) as JsonSchema)), [tool]);
  const [input, setInput] = useState(defaults);
  const [valid, setValid] = useState(true);
  const [confirm, setConfirm] = useState(false);

  const test = useMutation({
    mutationFn: () => {
      if (!tool) throw new Error("No tool selected");
      const parsed = safeJsonParse(input || "{}");
      if (!parsed.ok) throw new Error(parsed.error);
      if (!isPlainObject(parsed.value)) throw new Error("Input must be a JSON object");
      const body: CustomToolTestIn = { input: parsed.value, confirm_side_effect: confirm };
      return api<CustomToolTestOut>(`/custom-tools/${encodeURIComponent(tool.id)}/test`, { method: "POST", body });
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: qk.customTools });
    },
  });

  useEffect(() => {
    setInput(defaults);
    setConfirm(false);
    test.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when a different tool is opened
  }, [tool?.id, defaults]);

  const result = test.data;
  const blocked = Boolean(tool?.side_effect) && !confirm;

  return (
    <Dialog open={tool !== null} onOpenChange={(next) => !test.isPending && onOpenChange(next)}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Test {tool?.name}</DialogTitle>
          <DialogDescription>
            Sends one real <span className="font-mono">{tool?.method}</span> request to <span className="break-all font-mono text-xs">{tool?.url_template}</span>.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <JsonEditor label="Input" value={input} onChange={setInput} onValidChange={setValid} rows={8} />
          {tool?.side_effect ? (
            <label className="flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-fg">
              <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} className="mt-0.5 h-3.5 w-3.5 accent-[hsl(var(--warning))]" aria-describedby="ct-side-effect-note" />
              <span id="ct-side-effect-note">
                <span className="flex items-center gap-1 font-medium text-warning">
                  <ShieldAlert className="h-3.5 w-3.5" aria-hidden /> This tool has side effects
                </span>
                I understand this test sends a real request that may change data in the external system (approval is bypassed for this manual test).
              </span>
            </label>
          ) : null}

          {test.isError ? (
            <div role="alert" className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> {errorMessage(test.error)}
            </div>
          ) : null}
          {result ? (
            <div className="space-y-2" data-testid="custom-tool-test-result" data-ok={result.ok}>
              <div className="flex flex-wrap items-center gap-2">
                {result.ok ? (
                  <Badge tone="success" icon={<CheckCircle2 className="h-3 w-3" aria-hidden />}>
                    Success
                  </Badge>
                ) : (
                  <Badge tone="danger" icon={<XCircle className="h-3 w-3" aria-hidden />}>
                    Failed
                  </Badge>
                )}
                <span className="text-xs text-fg-muted tabular">{fmtMs(result.latency_ms)}</span>
              </div>
              {result.error ? (
                <div role="alert" className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-fg">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
                  <span className="break-words">{result.error}</span>
                </div>
              ) : null}
              {result.result !== null && result.result !== undefined ? <JsonViewer value={result.result} title="Response" maxHeight="18rem" /> : null}
            </div>
          ) : null}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={test.isPending}>
            Close
          </Button>
          <Button variant="primary" onClick={() => test.mutate()} loading={test.isPending} disabled={!valid || blocked} leftIcon={<Send className="h-4 w-4" aria-hidden />}>
            Send test request
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
