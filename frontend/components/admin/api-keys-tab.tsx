"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, ShieldAlert } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { PermissionPicker } from "@/components/admin/roles-tab";
import { Badge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CodeBlock } from "@/components/ui/json-viewer";
import { ConfirmDialog, Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { ChipList } from "@/components/ui/key-value";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { Tip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { useApiKeys, usePermissionCatalog } from "@/lib/queries";
import type { ApiKeyIn, ApiKeyOut } from "@/lib/types";
import { fmtDateTime, fmtRelative } from "@/lib/utils";

export function ApiKeysTab() {
  const keys = useApiKeys();
  const catalog = usePermissionCatalog();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [created, setCreated] = useState<ApiKeyOut | null>(null);
  const [revoking, setRevoking] = useState<ApiKeyOut | null>(null);

  const revoke = useMutation({
    mutationFn: (key: ApiKeyOut) => api<void>(`/admin/api-keys/${key.id}`, { method: "DELETE" }),
    onSuccess: (_, key) => {
      toast.success("API key revoked", { description: `${key.name} (${key.prefix}…)` });
      void queryClient.invalidateQueries({ queryKey: ["api-keys"] });
      setRevoking(null);
    },
    onError: (error) => toast.error("Could not revoke key", { description: errorMessage(error) }),
  });

  if (keys.isError) return <ErrorState error={keys.error} onRetry={() => keys.refetch()} />;
  if (keys.isLoading) return <SkeletonRows rows={4} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-fg-muted">Keys let external systems call OpsPilot. Each key is shown only once.</p>
        <Button variant="primary" size="sm" onClick={() => setCreateOpen(true)} leftIcon={<Plus className="h-4 w-4" aria-hidden />}>
          Create key
        </Button>
      </div>
      {keys.data && keys.data.length === 0 ? (
        <EmptyState icon={KeyRound} title="No API keys" description="Create a key to let external systems post events." />
      ) : (
        <TableWrap>
          <Table className="min-w-[860px]">
            <THead>
              <TR>
                <TH>Key</TH>
                <TH>Scopes</TH>
                <TH>Status</TH>
                <TH>Created</TH>
                <TH>Expires</TH>
                <TH>Last used</TH>
                <TH align="right">
                  <span className="sr-only">Actions</span>
                </TH>
              </TR>
            </THead>
            <TBody>
              {(keys.data ?? []).map((key) => {
                const expired = key.expires_at ? new Date(key.expires_at).getTime() < Date.now() : false;
                return (
                  <TR key={key.id}>
                    <TD>
                      <span className="font-medium text-fg">{key.name}</span>
                      <code className="block font-mono text-[11px] text-fg-subtle">{key.prefix}…</code>
                    </TD>
                    <TD>
                      <ChipList items={key.scopes.slice(0, 4)} />
                      {key.scopes.length > 4 ? <span className="text-xs text-fg-subtle">+{key.scopes.length - 4} more</span> : null}
                    </TD>
                    <TD>{key.revoked_at ? <StatusPill status="disabled" size="sm" label="Revoked" /> : expired ? <StatusPill status="expired" size="sm" /> : <StatusPill status="active" size="sm" />}</TD>
                    <TD>
                      <Tip content={fmtDateTime(key.created_at)}>
                        <span className="text-fg-muted">{fmtRelative(key.created_at)}</span>
                      </Tip>
                    </TD>
                    <TD className="text-fg-muted">{key.expires_at ? fmtDateTime(key.expires_at) : "never"}</TD>
                    <TD className="text-fg-muted">{key.last_used_at ? fmtRelative(key.last_used_at) : "never"}</TD>
                    <TD align="right">
                      {!key.revoked_at ? (
                        <Button size="xs" variant="danger" onClick={() => setRevoking(key)}>
                          Revoke
                        </Button>
                      ) : null}
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        </TableWrap>
      )}
      <CreateKeyDialog open={createOpen} onOpenChange={setCreateOpen} permissions={catalog.data?.permissions ?? []} onCreated={setCreated} />
      <Dialog open={created !== null} onOpenChange={(open) => !open && setCreated(null)}>
        <DialogContent size="md" hideClose>
          <DialogHeader>
            <DialogTitle>Copy your new API key</DialogTitle>
            <DialogDescription>This is the only time the plaintext is shown. Store it in your secret manager now.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-3">
            {created ? (
              <>
                <p className="text-sm text-fg">
                  <span className="font-medium">{created.name}</span> · prefix <code className="font-mono text-xs">{created.prefix}</code>
                </p>
                <CodeBlock code={created.plaintext ?? ""} />
                <p className="flex items-start gap-1.5 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
                  <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> Send it as the X-API-Key header. Anyone with this key can act with its scopes until it is revoked.
                </p>
                <div className="flex flex-wrap gap-1">
                  {created.scopes.map((s) => (
                    <Badge key={s} size="sm">
                      {s}
                    </Badge>
                  ))}
                </div>
              </>
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button variant="primary" onClick={() => setCreated(null)}>
              I have stored the key
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={revoking !== null} onOpenChange={(open) => !open && setRevoking(null)} title="Revoke this API key?" description={revoking ? `${revoking.name} (${revoking.prefix}…) stops working immediately. This cannot be undone.` : undefined} confirmLabel="Revoke" tone="danger" loading={revoke.isPending} onConfirm={() => revoking && revoke.mutate(revoking)} />
    </div>
  );
}

function CreateKeyDialog({ open, onOpenChange, permissions, onCreated }: { open: boolean; onOpenChange: (open: boolean) => void; permissions: string[]; onCreated: (key: ApiKeyOut) => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["events:write"]);
  const [expires, setExpires] = useState("");

  const create = useMutation({
    mutationFn: () => {
      const body: ApiKeyIn = { name: name.trim(), scopes, expires_in_days: expires ? Number(expires) : null };
      return api<ApiKeyOut>("/admin/api-keys", { method: "POST", body });
    },
    onSuccess: (key) => {
      void queryClient.invalidateQueries({ queryKey: ["api-keys"] });
      onOpenChange(false);
      onCreated(key);
      setName("");
      setScopes(["events:write"]);
      setExpires("");
    },
    onError: (error) => toast.error("Could not create key", { description: errorMessage(error) }),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="flex min-h-0 flex-col">
          <DialogHeader>
            <DialogTitle>Create an API key</DialogTitle>
            <DialogDescription>Scopes are capped by your own permissions.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Name" htmlFor="key-name" required>
                <Input id="key-name" value={name} onChange={(e) => setName(e.target.value)} required placeholder="e.g. CRM webhook producer" />
              </Field>
              <Field label="Expires in (days)" htmlFor="key-expires" hint="Leave empty for no expiry (1–3650).">
                <Input id="key-expires" type="number" min={1} max={3650} value={expires} onChange={(e) => setExpires(e.target.value)} />
              </Field>
            </div>
            <PermissionPicker permissions={permissions} selected={scopes} onChange={setScopes} />
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" loading={create.isPending} disabled={!name.trim() || scopes.length === 0}>
              Create key
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
