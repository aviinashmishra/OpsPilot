"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { ApiKeysTab } from "@/components/admin/api-keys-tab";
import { RolesTab } from "@/components/admin/roles-tab";
import { TenantTab } from "@/components/admin/tenant-tab";
import { TenantsTab } from "@/components/admin/tenants-tab";
import { UsersTab } from "@/components/admin/users-tab";
import { UsageQuotas } from "@/components/analytics/usage-quotas";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonRows } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCan } from "@/lib/permissions";

const TABS = ["tenant", "users", "roles", "apikeys", "usage", "tenants"] as const;
type Tab = (typeof TABS)[number];

function AdminContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const can = useCan();
  const requested = searchParams.get("tab");
  const available: Tab[] = TABS.filter((t) => {
    switch (t) {
      case "tenant":
        return can("tenant:read");
      case "users":
        return can("users:read");
      case "roles":
        return can("roles:read");
      case "apikeys":
        return can("apikeys:admin");
      case "usage":
        return can("usage:read");
      case "tenants":
        return can("platform:admin");
      default:
        return false;
    }
  });
  const tab: Tab = (TABS as readonly string[]).includes(requested ?? "") && available.includes(requested as Tab) ? (requested as Tab) : available[0] ?? "tenant";

  const setTab = (next: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", next);
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  };

  return (
    <div className="space-y-5">
      <PageHeader title="Administration" />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="w-full justify-start sm:w-auto">
          {available.includes("tenant") ? <TabsTrigger value="tenant">Tenant</TabsTrigger> : null}
          {available.includes("users") ? <TabsTrigger value="users">Users</TabsTrigger> : null}
          {available.includes("roles") ? <TabsTrigger value="roles">Roles</TabsTrigger> : null}
          {available.includes("apikeys") ? <TabsTrigger value="apikeys">API keys</TabsTrigger> : null}
          {available.includes("usage") ? <TabsTrigger value="usage">Usage &amp; quotas</TabsTrigger> : null}
          {available.includes("tenants") ? <TabsTrigger value="tenants">Tenants</TabsTrigger> : null}
        </TabsList>
        <TabsContent value="tenant">
          <TenantTab />
        </TabsContent>
        <TabsContent value="users">
          <UsersTab />
        </TabsContent>
        <TabsContent value="roles">
          <RolesTab />
        </TabsContent>
        <TabsContent value="apikeys">
          <ApiKeysTab />
        </TabsContent>
        <TabsContent value="usage">
          <UsageQuotas />
        </TabsContent>
        <TabsContent value="tenants">
          <TenantsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function AdminPage() {
  return (
    <Suspense fallback={<SkeletonRows rows={8} />}>
      <AdminContent />
    </Suspense>
  );
}
