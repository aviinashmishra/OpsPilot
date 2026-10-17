"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, KeyRound, Plug, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { JsonEditor } from "@/components/ui/json-editor";
import { Collapsible } from "@/components/ui/misc";
import { api, errorMessage } from "@/lib/api";
import type { ConnectionField, ConnectionTestOut, IntegrationFamily, IntegrationIn, IntegrationOut, JsonObject } from "@/lib/types";
import { cn, prettyJson, safeJsonParse, titleCase } from "@/lib/utils";

const SANDBOX = "__sandbox__";

/** Connect a system family: sample data (sandbox) or a real system, with a guided form per provider. */
export function ConfigureIntegrationDialog({ integration, family, open, onOpenChange }: { integration: IntegrationOut | null; family: IntegrationFamily | null; open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const liveSupported = useMemo(() => family?.live_supported ?? [], [family]);
  const [choice, setChoice] = useState<string>(SANDBOX);
  const [values, setValues] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [extraConfig, setExtraConfig] = useState("{}");
  const [extraValid, setExtraValid] = useState(true);
  const [webhookSecret, setWebhookSecret] = useState("");
  const [scopes, setScopes] = useState("");
  const [result, setResult] = useState<ConnectionTestOut | null>(null);

  const spec = choice !== SANDBOX ? family?.connection?.[choice] : undefined;
  const fields: ConnectionField[] = useMemo(() => spec?.fields ?? (choice !== SANDBOX ? (family?.required_credentials[choice] ?? []).map((k) => ({ key: k, label: titleCase(k), store: "credentials" as const, secret: true, required: true, placeholder: "", help: "" })) : []), [spec, choice, family]);
  const configKeys = useMemo(() => new Set(Object.values(family?.connection ?? {}).flatMap((s) => s.fields.filter((f) => f.store === "config").map((f) => f.key))), [family]);
  const sameProvider = integration?.mode === "live" && integration.live_provider === choice;

  useEffect(() => {
    if (!open || !integration) return;
    const live = integration.mode === "live" && integration.live_provider && liveSupported.includes(integration.live_provider);
    setChoice(live ? (integration.live_provider as string) : SANDBOX);
    const cfg = integration.config ?? {};
    setValues(Object.fromEntries(Object.entries(cfg).filter(([k, v]) => configKeys.has(k) && v !== null && v !== undefined).map(([k, v]) => [k, String(v)])));
    setExtraConfig(prettyJson(Object.fromEntries(Object.entries(cfg).filter(([k]) => !configKeys.has(k) && k !== "live_provider"))));
    setName(integration.name);
    setWebhookSecret("");
    setScopes(integration.scopes.join(", "));
    setResult(null);
  }, [open, integration, liveSupported, configKeys]);

  const missing = fields.filter((f) => f.required && !values[f.key]?.trim() && !(f.store === "credentials" && sameProvider && integration?.has_credentials));
  const ready = extraValid && (choice === SANDBOX || missing.length === 0);

  const save = useMutation({
    mutationFn: async () => {
      if (!integration) throw new Error("No integration selected");
      const extra = safeJsonParse(extraConfig || "{}");
      if (!extra.ok) throw new Error(extra.error);
      const live = choice !== SANDBOX;
      const config: JsonObject = { ...((extra.value ?? {}) as JsonObject) };
      const credentials: Record<string, string> = {};
      for (const f of fields) {
        const v = values[f.key]?.trim();
        if (!v) continue;
        if (f.store === "config") config[f.key] = v;
        else credentials[f.key] = v;
      }
      const body: IntegrationIn = {
        provider: integration.provider,
        name: name.trim() || (live ? `${family?.label ?? integration.provider_label} (${spec?.label ?? titleCase(choice)})` : `${family?.label ?? integration.provider_label} (sandbox)`),
        mode: live ? "live" : "mock",
        live_provider: live ? choice : null,
        config,
        credentials: Object.keys(credentials).length > 0 ? credentials : null,
        webhook_secret: webhookSecret.trim() || null,
        scopes: scopes.split(",").map((s) => s.trim()).filter(Boolean),
      };
      const saved = await api<IntegrationOut>("/integrations", { method: "POST", body });
      return api<ConnectionTestOut>(`/integrations/${saved.id}/test`, { method: "POST" });
    },
    onSuccess: (test) => {
      setResult(test);
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
      void queryClient.invalidateQueries({ queryKey: ["onboarding"] });
      if (test.ok) {
        toast.success(choice === SANDBOX ? `${family?.label ?? "System"} uses sample data` : `${spec?.label ?? "System"} connected`, { description: test.message });
        onOpenChange(false);
      }
    },
    onError: (error) => toast.error("Could not save the connection", { description: errorMessage(error) }),
  });

  const options = [SANDBOX, ...liveSupported];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Connect {family?.label ?? integration?.provider_label ?? "a system"}</DialogTitle>
          <DialogDescription>Agents use this connection. Secrets are stored encrypted.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div role="radiogroup" aria-label="Connection" className="grid gap-2 sm:grid-cols-2">
            {options.map((opt) => {
              const selected = choice === opt;
              const label = opt === SANDBOX ? "Sample data (sandbox)" : family?.connection?.[opt]?.label ?? titleCase(opt);
              return (
                <button
                  key={opt}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => {
                    setChoice(opt);
                    setResult(null);
                  }}
                  className={cn("rounded-lg border px-3 py-2.5 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50", selected ? "border-accent bg-accent/10 text-fg" : "border-border hover:border-accent/50")}
                >
                  <span className="block font-medium">{label}</span>
                  <span className="block text-xs text-fg-muted">{opt === SANDBOX ? "Built-in simulator. Nothing leaves OpsPilot." : "Your real system"}</span>
                </button>
              );
            })}
          </div>
          {liveSupported.length === 0 ? <p className="text-xs text-fg-subtle">No live connector exists for this system yet; agents use the workspace records. You can also call your own API with a custom tool.</p> : null}

          {choice !== SANDBOX ? (
            <fieldset className="space-y-3 rounded-md border border-border bg-surface-2/50 p-3">
              <legend className="inline-flex items-center gap-1 px-1 text-xs font-medium text-fg-muted">
                <KeyRound className="h-3.5 w-3.5" aria-hidden /> {spec?.label ?? titleCase(choice)}
              </legend>
              {fields.map((f) => {
                const keep = f.store === "credentials" && sameProvider && integration?.has_credentials;
                const id = `conn-${f.key}`;
                return (
                  <Field key={f.key} label={f.label} htmlFor={id} required={f.required && !keep} hint={keep ? `${f.help ? `${f.help} ` : ""}Saved; leave blank to keep it.` : f.help || undefined}>
                    {f.options ? (
                      <NativeSelect id={id} value={values[f.key] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}>
                        <option value="">Default{f.placeholder ? ` (${f.placeholder})` : ""}</option>
                        {f.options.map((o) => (
                          <option key={o} value={o}>
                            {o}
                          </option>
                        ))}
                      </NativeSelect>
                    ) : (
                      <Input id={id} type={f.secret ? "password" : "text"} autoComplete={f.secret ? "new-password" : "off"} value={values[f.key] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))} placeholder={keep ? "••••••••" : f.placeholder} />
                    )}
                  </Field>
                );
              })}
              {spec?.help_url ? (
                <a href={spec.help_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
                  Where do I find these? <ExternalLink className="h-3 w-3" aria-hidden />
                </a>
              ) : null}
            </fieldset>
          ) : null}

          {result && !result.ok ? (
            <div role="alert" className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
              <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              <span>
                <span className="block font-medium">Connection test failed</span>
                <span className="block text-xs">{result.message}</span>
              </span>
            </div>
          ) : result?.ok ? (
            <p className="flex items-center gap-1.5 text-sm text-success">
              <CheckCircle2 className="h-4 w-4" aria-hidden /> {result.message}
            </p>
          ) : null}

          <Collapsible title={<span className="text-xs text-fg-muted">Advanced</span>} className="bg-transparent">
            <div className="space-y-3 pt-2">
              <Field label="Display name" htmlFor="int-name">
                <Input id="int-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
              </Field>
              <Field label="Webhook signing secret" htmlFor="int-webhook" hint={integration?.has_webhook_secret ? "Saved; leave blank to keep it." : "Verifies events the system sends to OpsPilot."}>
                <Input id="int-webhook" type="password" autoComplete="new-password" value={webhookSecret} onChange={(e) => setWebhookSecret(e.target.value)} placeholder="••••••••" />
              </Field>
              <Field label="Scopes" htmlFor="int-scopes" hint="Comma separated, e.g. crm:read, crm:write">
                <Input id="int-scopes" value={scopes} onChange={(e) => setScopes(e.target.value)} />
              </Field>
              <JsonEditor label="Extra settings (JSON)" value={extraConfig} onChange={setExtraConfig} onValidChange={setExtraValid} rows={4} />
            </div>
          </Collapsible>
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!ready} leftIcon={<Plug className="h-4 w-4" aria-hidden />}>
            {choice === SANDBOX ? "Use sample data" : "Save and test connection"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
