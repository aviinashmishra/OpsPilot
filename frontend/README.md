# OpsPilot AI — administrative dashboard

Next.js 14 (App Router) frontend for the OpsPilot AI multi-tenant AI workforce platform. Everything on screen comes from the FastAPI backend (`/api/v1`); there is no mock data in the UI.

## Requirements

- Node.js 20+ (Node 24 works) and npm 10+
- The OpsPilot backend running, by default at `http://127.0.0.1:8000`

## Setup & run (Windows PowerShell shown; macOS/Linux is the same without the full paths)

```powershell
cd C:\Users\Inno\OpsPilot\frontend
Copy-Item .env.local.example .env.local     # NEXT_PUBLIC_API_URL=http://127.0.0.1:8000/api/v1
& "C:\Program Files\nodejs\npm.cmd" install
& "C:\Program Files\nodejs\npm.cmd" run dev   # http://localhost:3000
```

Production build:

```powershell
& "C:\Program Files\nodejs\npm.cmd" run build
& "C:\Program Files\nodejs\npm.cmd" start     # serves on port 3000
```

Quality gates: `npm run lint` (ESLint, next/core-web-vitals) and `npm run typecheck` (tsc, strict).

Start the backend (in another terminal):

```powershell
cd C:\Users\Inno\OpsPilot\backend
$env:DATABASE_URL='sqlite:///./opspilot.db'
.\.venv\Scripts\python.exe -m app.cli serve --port 8000
```

Sign in with a seeded demo account (tenant `acme-demo`, password `OpsPilot-Demo-2026!`): `admin@`, `ops@`, `approver@`, `finance@`, `auditor@`, `viewer@` `acme-demo.test`. The login page lists them as one-click fill buttons (from `GET /auth/demo-accounts`).

### Docker

```bash
docker build -t opspilot-frontend --build-arg NEXT_PUBLIC_API_URL=http://api.example.com/api/v1 .
docker run -p 3000:3000 opspilot-frontend
```

`NEXT_PUBLIC_API_URL` is inlined at build time, so pass it as a build arg. The backend's `CORS_ORIGINS` must include the dashboard origin (defaults allow `http://localhost:3000` and `http://127.0.0.1:3000`).

## How it is wired

- `lib/api.ts` — typed `fetch` wrapper: base URL, bearer token, JSON errors thrown as `ApiError { status, code, message, details, correlationId }`, 401 → session cleared and redirect to `/login`.
- `lib/types.ts` — TypeScript mirrors of `backend/app/api/schemas.py` and the dict responses of reports/usage/admin.
- `lib/session.ts` — zustand store (token, user, tenant, expiry) persisted to `localStorage`; `lib/permissions.ts` — `hasPermission()` / `useCan()` matching the backend's `Principal.has()` (`*` and `scope:*` wildcards).
- `lib/queries.ts` — TanStack Query hooks for every endpoint (30 s stale time; mutations invalidate the affected keys; live workflow runs poll every 4 s).
- `lib/schema-defaults.ts` — builds a playground payload from an agent's JSON input schema (required fields only).
- Theme: dark by default, light toggle in the top bar, persisted under `opspilot.theme`, honours `prefers-color-scheme` when nothing is stored. Tokens live in `app/globals.css`; Tailwind reads them via `tailwind.config.ts`.

## Pages

| Route | What it shows |
| --- | --- |
| `/login` | Tenant + email + password, demo account quick-fill |
| `/overview` | Stat tiles, runs/cost per day, department activity, integration modes, recent runs & incidents, period selector |
| `/agents`, `/agents/[key]` | Catalog with department chips & search, enable/disable (confirmed); detail with contract, tools, policies, config editor, runs, evaluation and a **Playground** (`POST /agents/{key}/run`, mode `workflow`) |
| `/workflows`, `/workflows/[id]`, `/workflows/definitions` | Run history with filters/pagination and "Start workflow" (sends `Idempotency-Key`); run detail with React Flow graph coloured from `state.nodes`, checkpoints timeline, agent-run accordion, cancel/retry; templates with graph previews |
| `/approvals` | Pending / Decided / All, drawer with exact payload, payload hash, policy, evidence, context; approve/reject (note required to reject) sending `payload_hash`; shows execution result |
| `/tasks` | Table with status filter, overdue toggle, inline status change, create dialog |
| `/integrations` | One card per provider family (Sandbox vs Live clearly labelled), configure (write-only credentials), test connection, sync |
| `/analytics` | KPI tiles, ROI panel (estimated vs realized), sortable per-agent and per-workflow tables, usage/quota meters |
| `/audit` | Searchable audit trail (q, action prefix, severity, correlation id), expandable details, hash-chain verification |
| `/incidents` | Open/resolved incidents with resolve action |
| `/documents` | Knowledge base list, add text document, BM25 search, delete |
| `/evaluations` | Latest evaluation per agent, run one / run all, case drill-down |
| `/admin` | Tabs: Tenant (policies, ROI assumptions, retention, **emergency disable**), Users, Roles, API keys (plaintext shown once), Usage & quotas, Tenants (platform admins) |

Global: collapsible sidebar with department grouping (drawer on mobile), top bar with tenant, ⌘K command palette (pages, agents, start workflow, toggle theme), theme toggle, user menu with sign-out. Every page has loading skeletons, empty and error states with retry, confirmation dialogs for consequential actions and toast feedback.

## Component map

`components/ui/` — Button, Card, Badge/StatusPill/RiskBadge/ModeBadge, Input/Textarea/NativeSelect/Field, Select (Radix), Switch, Tabs, Dialog/ConfirmDialog, Sheet, DropdownMenu, Tooltip, Table (+SortableTH), Skeleton, EmptyState/ErrorState, Pagination, StatTile, PageHeader, JsonViewer/CodeBlock, JsonEditor, KeyValueList/ChipList, Timeline, Segmented/Chip/Meter/Collapsible/Kbd.

`components/layout/` — AppShell, Sidebar (+MobileSidebar), Topbar (ThemeToggle, UserMenu), CommandPalette, AuthGuard, Brand. `components/charts/` — DailyRunsChart, DepartmentBars. `components/workflows/` — WorkflowGraphView (React Flow), StartWorkflowDialog, RunListItem. `components/agents/` — AgentCard, AgentRunResultView, AgentRunDetails. `components/approvals/` — ApprovalDrawer. `components/integrations/` — ConfigureIntegrationDialog. `components/admin/` — Tenant/Users/Roles/ApiKeys/Tenants tabs. `components/analytics/` — UsageQuotas.
