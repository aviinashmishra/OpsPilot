"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { JsonEditor } from "@/components/ui/json-editor";
import { api, errorMessage } from "@/lib/api";
import type { IntegrationFamily, IntegrationIn, IntegrationOut, JsonObject } from "@/lib/types";
import { prettyJson, safeJsonParse, titleCase } from "@/lib/utils";

export function ConfigureIntegrationDialog({ integration, family, open, onOpenChange }: { integration: IntegrationOut | null; family: IntegrationFamily | null; open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"mock" | "live">("mock");
  const [liveProvider, setLiveProvider] = useState("");
  const [config, setConfig] = useState("{}");
  const [configValid, setConfigValid] = useState(true);
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [webhookSecret, setWebhookSecret] = useState("");
  const [scopes, setScopes] = useState("");

  const liveSupported = useMemo(() => family?.live_supported ?? [], [family]);
  const requiredCredentials = useMemo(() => (family && liveProvider ? family.required_credentials[liveProvider] ?? [] : []), [family, liveProvider]);

  useEffect(() => {
    if (!open || !integration) return;
    setName(integration.name);
    setMode(integration.mode === "live" ? "live" : "mock");
    setLiveProvider(integration.live_provider ?? liveSupported[0] ?? "");
    setConfig(prettyJson(integration.config ?? {}));
    setCredentials({});
    setWebhookSecret("");
    setScopes(integration.scopes.join(", "));
  }, [open, integration, liveSupported]);

  const save = useMutation({
    mutationFn: () => {
      if (!integration) throw new Error("No integration selected");
      const parsed = safeJsonParse(config || "{}");
      if (!parsed.ok) throw new Error(parsed.error);
      const creds = Object.fromEntries(Object.entries(credentials).filter(([, v]) => v.trim() !== ""));
      const body: IntegrationIn = {
        provider: integration.provider,
        name: name.trim() || integration.name,
        mode,
        live_provider: mode === "live" ? liveProvider || null : null,
        config: (parsed.value ?? {}) as JsonObject,
        credentials: Object.keys(creds).length > 0 ? creds : null,
        webhook_secret: webhookSecret.trim() || null,
        scopes: scopes
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      };
      return api<IntegrationOut>("/integrations", { method: "POST", body });
    },
    onSuccess: (updated) => {
      toast.success(`${updated.provider_label} saved`, { description: updated.mode === "live" ? "Run a connection test to mark it connected." : "Sandbox mode — no external system is connected." });
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
      onOpenChange(false);
    },
    onError: (error) => toast.error("Could not save integration", { description: errorMessage(error) }),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Configure {integration?.provider_label ?? "integration"}</DialogTitle>
          <DialogDescription>Credentials are stored encrypted. Leave blank to keep the saved value.</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <Field label="Display name" htmlFor="int-name">
            <Input id="int-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Mode" htmlFor="int-mode" hint={mode === "mock" ? "Sandbox: tools run against the built-in simulator." : "Live: tools call the real provider after a successful connection test."}>
              <NativeSelect id="int-mode" value={mode} onChange={(e) => setMode(e.target.value as "mock" | "live")}>
                <option value="mock">Sandbox (no external system)</option>
                <option value="live" disabled={liveSupported.length === 0}>
                  Live{liveSupported.length === 0 ? " (no live provider available)" : ""}
                </option>
              </NativeSelect>
            </Field>
            <Field label="Live provider" htmlFor="int-provider">
              <NativeSelect id="int-provider" value={liveProvider} onChange={(e) => setLiveProvider(e.target.value)} disabled={mode !== "live" || liveSupported.length === 0}>
                {liveSupported.length === 0 ? <option value="">None supported</option> : null}
                {liveSupported.map((p) => (
                  <option key={p} value={p}>
                    {titleCase(p)}
                  </option>
                ))}
              </NativeSelect>
            </Field>
          </div>
          {mode === "live" && requiredCredentials.length > 0 ? (
            <fieldset className="space-y-3 rounded-md border border-border bg-surface-2/50 p-3">
              <legend className="inline-flex items-center gap-1 px-1 text-xs font-medium text-fg-muted">
                <KeyRound className="h-3.5 w-3.5" aria-hidden /> Credentials (write-only)
              </legend>
              {requiredCredentials.map((key) => (
                <Field key={key} label={titleCase(key)} htmlFor={`cred-${key}`} hint={integration?.has_credentials ? "Stored value exists; leave blank to keep it." : undefined}>
                  <Input id={`cred-${key}`} type="password" autoComplete="new-password" value={credentials[key] ?? ""} onChange={(e) => setCredentials((c) => ({ ...c, [key]: e.target.value }))} placeholder="••••••••" />
                </Field>
              ))}
            </fieldset>
          ) : null}
          <Field label="Webhook secret" htmlFor="int-webhook" hint={integration?.has_webhook_secret ? "A secret is stored; leave blank to keep it." : "Used to verify signed provider webhooks."}>
            <Input id="int-webhook" type="password" autoComplete="new-password" value={webhookSecret} onChange={(e) => setWebhookSecret(e.target.value)} placeholder="••••••••" />
          </Field>
          <Field label="Scopes" htmlFor="int-scopes" hint="Comma separated, e.g. crm:read, crm:write">
            <Input id="int-scopes" value={scopes} onChange={(e) => setScopes(e.target.value)} />
          </Field>
          <JsonEditor label="Config (non-secret settings)" value={config} onChange={setConfig} onValidChange={setConfigValid} rows={6} />
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!configValid || (mode === "live" && !liveProvider)} leftIcon={<Save className="h-4 w-4" aria-hidden />}>
            Save integration
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
