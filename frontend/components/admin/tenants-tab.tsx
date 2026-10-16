"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Building2, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Badge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { api, errorMessage } from "@/lib/api";
import { useTenants } from "@/lib/queries";
import type { TenantIn, TenantOut } from "@/lib/types";

export function TenantsTab() {
  const tenants = useTenants();
  const [createOpen, setCreateOpen] = useState(false);
  if (tenants.isError) return <ErrorState error={tenants.error} onRetry={() => tenants.refetch()} />;
  if (tenants.isLoading) return <SkeletonRows rows={4} />;
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-fg-muted">Platform administration: every tenant on this deployment.</p>
        <Button variant="primary" size="sm" onClick={() => setCreateOpen(true)} leftIcon={<Plus className="h-4 w-4" aria-hidden />}>
          Onboard tenant
        </Button>
      </div>
      {tenants.data && tenants.data.length === 0 ? (
        <EmptyState icon={Building2} title="No tenants" />
      ) : (
        <TableWrap>
          <Table className="min-w-[720px]">
            <THead>
              <TR>
                <TH>Tenant</TH>
                <TH>Plan</TH>
                <TH>Status</TH>
                <TH>Emergency</TH>
                <TH align="right">Retention</TH>
                <TH>Quotas</TH>
              </TR>
            </THead>
            <TBody>
              {(tenants.data ?? []).map((t) => (
                <TR key={t.id}>
                  <TD>
                    <span className="font-medium text-fg">{t.name}</span>
                    <code className="block font-mono text-[11px] text-fg-subtle">{t.slug}</code>
                  </TD>
                  <TD>
                    <Badge size="sm">{t.plan}</Badge>
                  </TD>
                  <TD>
                    <StatusPill status={t.status} size="sm" />
                  </TD>
                  <TD>{t.emergency_disabled ? <StatusPill status="disabled" size="sm" label="Emergency disabled" /> : <span className="text-xs text-fg-subtle">off</span>}</TD>
                  <TD align="right">{t.retention_days} d</TD>
                  <TD className="text-xs text-fg-muted">
                    {typeof t.quotas.monthly_workflow_runs === "number" ? `${t.quotas.monthly_workflow_runs} runs` : "default runs"} · {typeof t.quotas.monthly_llm_tokens === "number" ? `${t.quotas.monthly_llm_tokens} tokens` : "default tokens"}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </TableWrap>
      )}
      <CreateTenantDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  );
}

function CreateTenantDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [plan, setPlan] = useState("starter");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminName, setAdminName] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const validSlug = /^[a-z0-9-]{3,64}$/.test(slug);

  const create = useMutation({
    mutationFn: () => {
      const body: TenantIn = { slug, name: name.trim(), plan, admin_email: adminEmail.trim(), admin_name: adminName.trim(), admin_password: adminPassword || null };
      return api<TenantOut>("/admin/tenants", { method: "POST", body });
    },
    onSuccess: (tenant) => {
      toast.success("Tenant onboarded", { description: `${tenant.name} (${tenant.slug})` });
      void queryClient.invalidateQueries({ queryKey: ["tenants"] });
      onOpenChange(false);
      setSlug("");
      setName("");
      setAdminEmail("");
      setAdminName("");
      setAdminPassword("");
    },
    onError: (error) => toast.error("Could not create tenant", { description: errorMessage(error) }),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <form onSubmit={submit} className="flex min-h-0 flex-col">
          <DialogHeader>
            <DialogTitle>Onboard a tenant</DialogTitle>
            <DialogDescription>Creates the tenant with system roles, default policies and its first admin user.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Slug" htmlFor="t-slug" required hint="lowercase letters, digits, hyphens (3–64)" error={slug && !validSlug ? "Invalid slug" : undefined}>
                <Input id="t-slug" value={slug} onChange={(e) => setSlug(e.target.value)} required />
              </Field>
              <Field label="Name" htmlFor="t-name" required>
                <Input id="t-name" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} />
              </Field>
              <Field label="Plan" htmlFor="t-plan">
                <NativeSelect id="t-plan" value={plan} onChange={(e) => setPlan(e.target.value)}>
                  {["starter", "growth", "enterprise"].map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
              <Field label="Admin password" htmlFor="t-pass" hint="Optional (min 12). Empty = SSO only.">
                <Input id="t-pass" type="password" autoComplete="new-password" value={adminPassword} onChange={(e) => setAdminPassword(e.target.value)} minLength={12} />
              </Field>
              <Field label="Admin email" htmlFor="t-email" required>
                <Input id="t-email" type="email" value={adminEmail} onChange={(e) => setAdminEmail(e.target.value)} required />
              </Field>
              <Field label="Admin name" htmlFor="t-admin" required>
                <Input id="t-admin" value={adminName} onChange={(e) => setAdminName(e.target.value)} required />
              </Field>
            </div>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" loading={create.isPending} disabled={!validSlug || !name.trim() || !adminEmail.trim() || !adminName.trim() || (adminPassword.length > 0 && adminPassword.length < 12)}>
              Create tenant
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
