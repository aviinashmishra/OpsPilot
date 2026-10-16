"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, ShieldCheck } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { ChipList } from "@/components/ui/key-value";
import { Collapsible } from "@/components/ui/misc";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { api, errorMessage } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import { usePermissionCatalog, useRoles } from "@/lib/queries";
import type { RoleIn, RoleOut } from "@/lib/types";

export function groupPermissions(permissions: string[]): Array<{ scope: string; items: string[] }> {
  const groups = new Map<string, string[]>();
  for (const p of permissions) {
    const scope = p.split(":")[0];
    groups.set(scope, [...(groups.get(scope) ?? []), p]);
  }
  return Array.from(groups.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([scope, items]) => ({ scope, items }));
}

export function PermissionPicker({ permissions, selected, onChange, disabled }: { permissions: string[]; selected: string[]; onChange: (next: string[]) => void; disabled?: boolean }) {
  const groups = useMemo(() => groupPermissions(permissions), [permissions]);
  const toggle = (p: string, checked: boolean) => onChange(checked ? [...selected, p] : selected.filter((s) => s !== p));
  return (
    <div className="max-h-72 space-y-3 overflow-y-auto rounded-md border border-border bg-surface-2/40 p-3">
      {groups.map((group) => (
        <fieldset key={group.scope}>
          <legend className="mb-1 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-fg-muted">
            {group.scope}
            <button type="button" className="text-[11px] font-normal normal-case text-accent hover:underline" disabled={disabled} onClick={() => onChange(Array.from(new Set([...selected, ...group.items])))}>
              all
            </button>
          </legend>
          <div className="flex flex-wrap gap-1.5">
            {group.items.map((p) => {
              const checked = selected.includes(p);
              return (
                <label key={p} className={`inline-flex cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 font-mono text-[11px] ${checked ? "border-accent/50 bg-accent/12 text-accent" : "border-border bg-surface text-fg-muted"}`}>
                  <input type="checkbox" className="sr-only" checked={checked} disabled={disabled} onChange={(e) => toggle(p, e.target.checked)} />
                  {p}
                </label>
              );
            })}
          </div>
        </fieldset>
      ))}
    </div>
  );
}

export function RolesTab() {
  const roles = useRoles();
  const catalog = usePermissionCatalog();
  const canAdmin = usePermission("roles:admin");
  const [createOpen, setCreateOpen] = useState(false);

  if (roles.isError) return <ErrorState error={roles.error} onRetry={() => roles.refetch()} />;
  if (roles.isLoading) return <SkeletonRows rows={6} />;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-fg-muted">Custom roles can only grant permissions you hold.</p>
        <Button variant="primary" size="sm" onClick={() => setCreateOpen(true)} disabled={!canAdmin} leftIcon={<Plus className="h-4 w-4" aria-hidden />}>
          Create role
        </Button>
      </div>
      {roles.data && roles.data.length === 0 ? (
        <EmptyState icon={ShieldCheck} title="No roles" />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {(roles.data ?? []).map((role) => (
            <Collapsible
              key={role.id}
              title={
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-medium text-fg">{role.name}</span>
                  {role.is_system ? <Badge size="sm">system</Badge> : <Badge size="sm" tone="accent">custom</Badge>}
                  <Badge size="sm">{role.user_count} user{role.user_count === 1 ? "" : "s"}</Badge>
                  {role.description ? <span className="block w-full text-xs text-fg-muted">{role.description}</span> : null}
                </span>
              }
              summary={<span className="text-xs text-fg-muted">{role.permissions.includes("*") ? "all permissions" : `${role.permissions.length} permissions`}</span>}
            >
              <ChipList items={role.permissions} tone="accent" />
            </Collapsible>
          ))}
        </div>
      )}
      <CreateRoleDialog open={createOpen} onOpenChange={setCreateOpen} permissions={catalog.data?.permissions ?? []} />
    </div>
  );
}

function CreateRoleDialog({ open, onOpenChange, permissions }: { open: boolean; onOpenChange: (open: boolean) => void; permissions: string[] }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const validName = /^[a-z0-9_]{2,64}$/.test(name);

  const create = useMutation({
    mutationFn: () => {
      const body: RoleIn = { name, description: description.trim() || null, permissions: selected };
      return api<RoleOut>("/admin/roles", { method: "POST", body });
    },
    onSuccess: (role) => {
      toast.success("Role created", { description: role.name });
      void queryClient.invalidateQueries({ queryKey: ["roles"] });
      onOpenChange(false);
      setName("");
      setDescription("");
      setSelected([]);
    },
    onError: (error) => toast.error("Could not create role", { description: errorMessage(error) }),
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
            <DialogTitle>Create a custom role</DialogTitle>
            <DialogDescription>Pick permissions from the catalog. Least privilege by default.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Name" htmlFor="role-name" required hint="lowercase letters, digits and underscores (2–64)" error={name && !validName ? "Invalid role name" : undefined}>
                <Input id="role-name" value={name} onChange={(e) => setName(e.target.value)} required aria-invalid={Boolean(name) && !validName} />
              </Field>
              <Field label="Description" htmlFor="role-desc">
                <Input id="role-desc" value={description} onChange={(e) => setDescription(e.target.value)} />
              </Field>
            </div>
            <PermissionPicker permissions={permissions} selected={selected} onChange={setSelected} />
            <p className="text-xs text-fg-muted">{selected.length} permission{selected.length === 1 ? "" : "s"} selected</p>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" loading={create.isPending} disabled={!validName || selected.length === 0}>
              Create role
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
