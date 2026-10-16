import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BarChart3,
  Bot,
  CheckSquare,
  ClipboardCheck,
  FileText,
  FlaskConical,
  LayoutDashboard,
  Plug,
  ScrollText,
  Server,
  Settings,
  ShieldAlert,
  Sparkles,
  Workflow,
} from "lucide-react";

export const DEPARTMENTS: Array<{ key: string; label: string; short: string }> = [
  { key: "sales_revenue", label: "Sales & Revenue", short: "Sales" },
  { key: "customer_support", label: "Customer Support", short: "Support" },
  { key: "ecommerce", label: "E-Commerce", short: "E-Commerce" },
  { key: "operations", label: "Operations & Management", short: "Operations" },
  { key: "finance_admin", label: "Finance & Administration", short: "Finance" },
  { key: "technology_product", label: "Technology & Product", short: "Technology" },
];

export const DEPARTMENT_LABELS: Record<string, string> = Object.fromEntries(DEPARTMENTS.map((d) => [d.key, d.label]));

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Permission needed to see the page (any of). */
  permissions?: string[];
  /** Matches nested routes too. */
  match?: (pathname: string) => boolean;
}

export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Operate",
    items: [
      { href: "/copilot", label: "Copilot", icon: Sparkles, permissions: ["agents:run"] },
      { href: "/overview", label: "Overview", icon: LayoutDashboard, permissions: ["reports:read"] },
      { href: "/agents", label: "Agents", icon: Bot, permissions: ["agents:read"] },
      { href: "/workflows", label: "Workflows", icon: Workflow, permissions: ["workflows:read"], match: (p) => p.startsWith("/workflows") },
      { href: "/approvals", label: "Approvals", icon: ClipboardCheck, permissions: ["approvals:read"] },
      { href: "/tasks", label: "Tasks", icon: CheckSquare, permissions: ["tasks:read"] },
    ],
  },
  {
    label: "Observe",
    items: [
      { href: "/analytics", label: "Analytics", icon: BarChart3, permissions: ["reports:read"] },
      { href: "/audit", label: "Audit trail", icon: ScrollText, permissions: ["audit:read"] },
      { href: "/incidents", label: "Incidents", icon: ShieldAlert, permissions: ["reports:read"] },
      { href: "/evaluations", label: "Evaluations", icon: FlaskConical, permissions: ["agents:read"] },
      { href: "/system", label: "Scale & workers", icon: Server, permissions: ["reports:read"] },
    ],
  },
  {
    label: "Configure",
    items: [
      { href: "/integrations", label: "Integrations", icon: Plug, permissions: ["integrations:read"] },
      { href: "/documents", label: "Documents", icon: FileText, permissions: ["documents:read"] },
      { href: "/admin", label: "Admin", icon: Settings, permissions: ["tenant:read", "users:read", "roles:read", "apikeys:admin", "usage:read"] },
    ],
  },
];

export const ALL_NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);

export const ActivityIcon = Activity;

export const RUN_STATUSES = ["pending", "running", "waiting_approval", "waiting_input", "completed", "failed", "timed_out", "cancelled"] as const;
export const TASK_STATUSES = ["open", "in_progress", "blocked", "done", "cancelled"] as const;
export const TASK_PRIORITIES = ["low", "medium", "high", "critical"] as const;
export const APPROVAL_DECIDED_STATUSES = "approved,rejected,executed,execution_failed,expired";
export const AUDIT_SEVERITIES = ["info", "warning", "critical"] as const;
export const PERIOD_OPTIONS = [7, 14, 30, 90] as const;
