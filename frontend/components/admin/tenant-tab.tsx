"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertOctagon, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardToolbar } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Field, Input, NativeSelect } from "@/components/ui/input";
import { JsonEditor } from "@/components/ui/json-editor";
import { KeyValueList } from "@/components/ui/key-value";
import { SkeletonRows } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";
import { Switch } from "@/components/ui/switch";
import { api, errorMessage } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import { useTenant } from "@/lib/queries";
import { useSession } from "@/lib/session";
import type { JsonObject, TenantOut, TenantUpdateIn } from "@/lib/types";
import { isPlainObject, prettyJson, safeJsonParse } from "@/lib/utils";

interface PoliciesForm {
  approval_mode: "standard" | "strict";
  amount_threshold: string;
  separation_of_duties: boolean;
  external_comms_require_approval: boolean;
  approval_ttl_hours: string;
  auto_approve: string;
}

interface RoiForm {
  loaded_hourly_cost_usd: string;
  infra_cost_per_run_usd: string;
  realization_rate: string;
  monthly_platform_fee_usd: string;
}

function readPolicies(settings: JsonObject): PoliciesForm {
  const p = isPlainObject(settings.policies) ? settings.policies : {};
  return {
    approval_mode: p.approval_mode === "strict" ? "strict" : "standard",
    amount_threshold: p.amount_threshold !== undefined ? String(p.amount_threshold) : "1000",
    separation_of_duties: p.separation_of_duties !== false,
    external_comms_require_approval: p.external_comms_require_approval !== false,
    approval_ttl_hours: p.approval_ttl_hours !== undefined ? String(p.approval_ttl_hours) : "48",
    auto_approve: prettyJson(Array.isArray(p.auto_approve) ? p.auto_approve : []),
  };
}

function readRoi(settings: JsonObject): RoiForm {
  const r = isPlainObject(settings.roi) ? settings.roi : {};
  return {
    loaded_hourly_cost_usd: String(r.loaded_hourly_cost_usd ?? 45),
    infra_cost_per_run_usd: String(r.infra_cost_per_run_usd ?? 0.002),
    realization_rate: String(r.realization_rate ?? 0),
    monthly_platform_fee_usd: String(r.monthly_platform_fee_usd ?? 0),
  };
}

export function TenantTab() {
  const tenant = useTenant();
  const canAdmin = usePermission("tenant:admin");
  const queryClient = useQueryClient();
  const updateSessionTenant = useSession((s) => s.updateTenant);
  const [name, setName] = useState("");
  const [retention, setRetention] = useState("365");
  const [policies, setPolicies] = useState<PoliciesForm | null>(null);
  const [roi, setRoi] = useState<RoiForm | null>(null);
  const [autoApproveValid, setAutoApproveValid] = useState(true);
  const [emergencyConfirm, setEmergencyConfirm] = useState<boolean | null>(null);

  useEffect(() => {
    if (!tenant.data) return;
    setName(tenant.data.name);
    setRetention(String(tenant.data.retention_days));
    setPolicies(readPolicies(tenant.data.settings));
    setRoi(readRoi(tenant.data.settings));
  }, [tenant.data]);

  const patch = useMutation({
    mutationFn: (body: TenantUpdateIn) => api<TenantOut>("/admin/tenant", { method: "PATCH", body }),
    onSuccess: (updated, body) => {
      queryClient.setQueryData(["tenant"], updated);
      updateSessionTenant(updated);
      void queryClient.invalidateQueries({ queryKey: ["tenant"] });
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["overview"] });
      void queryClient.invalidateQueries({ queryKey: ["reports"] });
      if (body.emergency_disabled !== undefined) {
        toast[body.emergency_disabled ? "warning" : "success"](body.emergency_disabled ? "Emergency disable is ACTIVE" : "Emergency disable lifted", { description: body.emergency_disabled ? "All agents are stopped for this tenant." : "Agents resume according to their individual settings." });
        setEmergencyConfirm(null);
      } else {
        toast.success("Tenant settings saved");
      }
    },
    onError: (error) => toast.error("Could not update tenant", { description: errorMessage(error) }),
  });

  if (tenant.isError) return <ErrorState error={tenant.error} onRetry={() => tenant.refetch()} />;
  if (tenant.isLoading || !tenant.data || !policies || !roi) return <SkeletonRows rows={8} />;
  const t = tenant.data;

  const saveGeneral = () => {
    const days = Number(retention);
    if (!Number.isFinite(days) || days < 7 || days > 3650) {
      toast.error("Retention must be between 7 and 3650 days");
      return;
    }
    patch.mutate({ name: name.trim() || t.name, retention_days: days });
  };

  const savePolicies = () => {
    const parsed = safeJsonParse(policies.auto_approve || "[]");
    if (!parsed.ok || !Array.isArray(parsed.value)) {
      toast.error("Auto-approve rules must be a JSON array");
      return;
    }
    patch.mutate({
      settings: {
        policies: {
          approval_mode: policies.approval_mode,
          amount_threshold: Number(policies.amount_threshold) || 0,
          separation_of_duties: policies.separation_of_duties,
          external_comms_require_approval: policies.external_comms_require_approval,
          approval_ttl_hours: Number(policies.approval_ttl_hours) || 48,
          auto_approve: parsed.value,
        },
      },
    });
  };

  const saveRoi = () => {
    patch.mutate({
      settings: {
        roi: {
          loaded_hourly_cost_usd: Number(roi.loaded_hourly_cost_usd) || 0,
          infra_cost_per_run_usd: Number(roi.infra_cost_per_run_usd) || 0,
          realization_rate: Math.min(1, Math.max(0, Number(roi.realization_rate) || 0)),
          monthly_platform_fee_usd: Number(roi.monthly_platform_fee_usd) || 0,
        },
      },
    });
  };

  return (
    <div className="space-y-4">
      <div className={`rounded-lg border p-4 ${t.emergency_disabled ? "border-danger bg-danger/10" : "border-danger/40 bg-danger/5"}`}>
        <div className="flex flex-wrap items-center gap-4">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-danger/20 text-danger">
            <AlertOctagon className="h-5 w-5" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-fg">Emergency disable</p>
            <p className="text-xs text-fg-muted">{t.emergency_disabled ? "ACTIVE — every agent is stopped." : "Immediately stops all agents for this tenant."}</p>
          </div>
          <label className="flex items-center gap-2 text-sm font-medium text-danger">
            {t.emergency_disabled ? "Active" : "Off"}
            <Switch tone="danger" checked={t.emergency_disabled} disabled={!canAdmin} onCheckedChange={(checked) => setEmergencyConfirm(checked)} aria-label="Emergency disable all agents" />
          </label>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardToolbar title="Tenant" />
          <CardContent className="space-y-4">
            <KeyValueList
              dense
              items={[
                { label: "Slug", value: t.slug, mono: true },
                { label: "Plan", value: t.plan },
                { label: "Status", value: <StatusPill status={t.status} size="sm" /> },
                { label: "Tenant id", value: t.id, mono: true },
              ]}
            />
            <Field label="Display name" htmlFor="tenant-name">
              <Input id="tenant-name" value={name} onChange={(e) => setName(e.target.value)} disabled={!canAdmin} />
            </Field>
            <Field label="Retention (days)" htmlFor="tenant-retention" hint="Business events older than this are deleted; audit records are kept longer (7–3650).">
              <Input id="tenant-retention" type="number" min={7} max={3650} value={retention} onChange={(e) => setRetention(e.target.value)} disabled={!canAdmin} />
            </Field>
            <Button variant="primary" onClick={saveGeneral} disabled={!canAdmin} loading={patch.isPending} leftIcon={<Save className="h-4 w-4" aria-hidden />}>
              Save
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardToolbar title="ROI assumptions" description="Used by Analytics." />
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Loaded hourly cost (USD)" htmlFor="roi-hourly">
                <Input id="roi-hourly" type="number" min={0} step="0.01" value={roi.loaded_hourly_cost_usd} onChange={(e) => setRoi({ ...roi, loaded_hourly_cost_usd: e.target.value })} disabled={!canAdmin} />
              </Field>
              <Field label="Infra cost per run (USD)" htmlFor="roi-infra">
                <Input id="roi-infra" type="number" min={0} step="0.0001" value={roi.infra_cost_per_run_usd} onChange={(e) => setRoi({ ...roi, infra_cost_per_run_usd: e.target.value })} disabled={!canAdmin} />
              </Field>
              <Field label="Realization rate (0–1)" htmlFor="roi-rate" hint="Share of savings verified by finance.">
                <Input id="roi-rate" type="number" min={0} max={1} step="0.05" value={roi.realization_rate} onChange={(e) => setRoi({ ...roi, realization_rate: e.target.value })} disabled={!canAdmin} />
              </Field>
              <Field label="Monthly platform fee (USD)" htmlFor="roi-fee">
                <Input id="roi-fee" type="number" min={0} step="1" value={roi.monthly_platform_fee_usd} onChange={(e) => setRoi({ ...roi, monthly_platform_fee_usd: e.target.value })} disabled={!canAdmin} />
              </Field>
            </div>
            <Button variant="primary" onClick={saveRoi} disabled={!canAdmin} loading={patch.isPending} leftIcon={<Save className="h-4 w-4" aria-hidden />}>
              Save assumptions
            </Button>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardToolbar title="Approval policies" description="Agent-level rules still apply." />
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Approval mode" htmlFor="pol-mode" hint="Strict requires approval for every side-effecting action.">
              <NativeSelect id="pol-mode" value={policies.approval_mode} onChange={(e) => setPolicies({ ...policies, approval_mode: e.target.value as "standard" | "strict" })} disabled={!canAdmin}>
                <option value="standard">Standard</option>
                <option value="strict">Strict</option>
              </NativeSelect>
            </Field>
            <Field label="Amount threshold (USD)" htmlFor="pol-amount" hint="Financial actions above this always need approval.">
              <Input id="pol-amount" type="number" min={0} value={policies.amount_threshold} onChange={(e) => setPolicies({ ...policies, amount_threshold: e.target.value })} disabled={!canAdmin} />
            </Field>
            <Field label="Approval TTL (hours)" htmlFor="pol-ttl" hint="Pending approvals expire after this.">
              <Input id="pol-ttl" type="number" min={1} value={policies.approval_ttl_hours} onChange={(e) => setPolicies({ ...policies, approval_ttl_hours: e.target.value })} disabled={!canAdmin} />
            </Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface-2/60 px-3 py-2 text-sm">
              <span>
                <span className="block font-medium text-fg">Separation of duties</span>
                <span className="block text-xs text-fg-muted">The requester of an action can never approve it.</span>
              </span>
              <Switch checked={policies.separation_of_duties} onCheckedChange={(c) => setPolicies({ ...policies, separation_of_duties: c })} disabled={!canAdmin} aria-label="Separation of duties" />
            </label>
            <label className="flex items-center justify-between gap-3 rounded-md border border-border bg-surface-2/60 px-3 py-2 text-sm">
              <span>
                <span className="block font-medium text-fg">External communications require approval</span>
                <span className="block text-xs text-fg-muted">Emails, WhatsApp and customer replies always wait for a human.</span>
              </span>
              <Switch checked={policies.external_comms_require_approval} onCheckedChange={(c) => setPolicies({ ...policies, external_comms_require_approval: c })} disabled={!canAdmin} aria-label="External communications require approval" />
            </label>
          </div>
          <JsonEditor label="Auto-approve rules (JSON array)" value={policies.auto_approve} onChange={(v) => setPolicies({ ...policies, auto_approve: v })} onValidChange={setAutoApproveValid} rows={8} disabled={!canAdmin} />
          <Button variant="primary" onClick={savePolicies} disabled={!canAdmin || !autoApproveValid} loading={patch.isPending} leftIcon={<Save className="h-4 w-4" aria-hidden />}>
            Save policies
          </Button>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={emergencyConfirm !== null}
        onOpenChange={(open) => !open && setEmergencyConfirm(null)}
        title={emergencyConfirm ? "Activate emergency disable?" : "Lift emergency disable?"}
        description={emergencyConfirm ? "Every agent stops immediately for this tenant. Workflows in flight fail at their next agent node. This is logged as a critical audit event." : "Agents resume according to their individual enable/disable settings."}
        confirmLabel={emergencyConfirm ? "Disable all agents" : "Re-enable"}
        tone={emergencyConfirm ? "danger" : "primary"}
        loading={patch.isPending}
        requireText={emergencyConfirm ? "DISABLE" : undefined}
        onConfirm={() => emergencyConfirm !== null && patch.mutate({ emergency_disabled: emergencyConfirm })}
      />
    </div>
  );
}
