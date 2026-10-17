# OpsPilot AI User Guide

This guide is for the people who use the OpsPilot dashboard every day: operations managers, operators, approvers, finance approvers, auditors and administrators. It explains what each part of the dashboard is for, when to use it, and exactly how to use it.

It was written from the application's source code. Every agent, tool, workflow, role and permission named here exists in the product. Where the code behaves in a surprising way, the guide says so plainly (look for **Known issue** notes).

Related documents (more technical): [README](../README.md) · [API reference](API.md) · [Architecture](ARCHITECTURE.md) · [Deployment](DEPLOYMENT.md) · [KPI and ROI definitions](KPI_AND_ROI.md) · [Known limitations](LIMITATIONS.md) · [Threat model](THREAT_MODEL.md)

---

## Contents

1. [What OpsPilot is](#1-what-opspilot-is)
   - [1.1 Core concepts](#11-core-concepts)
2. [Getting started](#2-getting-started)
   - [2.1 Starting and stopping the app (Windows)](#21-starting-and-stopping-the-app-windows)
   - [2.2 Signing in](#22-signing-in)
   - [2.3 Demo data you can use](#23-demo-data-you-can-use)
   - [2.4 The screen layout](#24-the-screen-layout)
3. [Roles and permissions](#3-roles-and-permissions)
4. [Page-by-page guide](#4-page-by-page-guide)
   - [4.1 Copilot](#41-copilot) · [4.2 Overview](#42-overview) · [4.3 Agents](#43-agents) · [4.4 Workflows](#44-workflows) · [4.5 Approvals](#45-approvals) · [4.6 Tasks](#46-tasks)
   - [4.7 Analytics](#47-analytics) · [4.8 Audit trail](#48-audit-trail) · [4.9 Incidents](#49-incidents) · [4.10 Evaluations](#410-evaluations) · [4.11 Scale and workers](#411-scale-and-workers)
   - [4.12 Integrations](#412-integrations) · [4.13 Documents](#413-documents) · [4.14 Admin](#414-admin)
5. [Agent reference (all 25 agents)](#5-agent-reference)
6. [Tool reference (all 98 built-in tools)](#6-tool-reference)
7. [Workflow reference (all 10 workflow templates)](#7-workflow-reference)
8. [Copilot guide](#8-copilot-guide)
9. [Common tasks (recipes)](#9-common-tasks-recipes)
10. [Troubleshooting and FAQ](#10-troubleshooting-and-faq)
11. [Glossary](#11-glossary)
- [Appendix: For technical admins](#appendix-for-technical-admins)

---

## 1. What OpsPilot is

OpsPilot is an "AI workforce" for business operations. It has **25 specialist agents** (sales, customer support, e-commerce, operations, finance, technology) that read your business data, analyse it and **propose** actions such as creating a CRM lead, opening a ticket, emailing a customer, staging an invoice for payment or issuing a purchase order.

OpsPilot never lets an AI model act on its own judgement for anything consequential. Every proposed action is checked against fixed rules. Anything risky waits for a person with the right permission to approve it. Everything that happens is written to a tamper-evident audit trail.

You can work with OpsPilot in four ways:

| Way | Where | Best for |
|---|---|---|
| Ask in plain language | **Copilot** page | Quick questions and one-off jobs ("Which tasks are overdue?") |
| Run one agent directly | **Agents** → an agent → **Playground** or **Bulk run** | Testing an agent, or running it over many records |
| Run a multi-step process | **Workflows** → **Start workflow** | Repeatable processes such as "new lead → CRM → outreach" |
| Automatically, from other systems | Business events and webhooks (set up by a technical admin) | Running workflows when something happens elsewhere |

### 1.1 Core concepts

**Agent.** A specialist that does one job (for example the *Invoice Processing Agent*). Each agent has a fixed contract: what input it accepts, what it returns, which tools it may use, how risky it is and which of its actions need approval. Agents return a result with a summary, structured data, **evidence** (pointers to where each fact came from), **missing information** (what it could not determine) and **proposed actions**.

**Tool.** A single, named capability that touches a system, such as `crm.find_lead` (look something up) or `email.send` (do something). Tools are either:
- **Read-only**: they only look things up. Agents and the Copilot can call them directly, provided the person running them has the matching permission.
- **Side effect**: they change something (create, update, send, pay, order). Agents can only *propose* these. OpsPilot's rule checker (the "policy engine") then decides: run now, wait for approval, or block.

**Workflow.** A fixed, step-by-step process that chains agents together, with decision points ("is the lead qualified?") and **approval gates** where the run pauses until people decide on pending actions. Each step is saved as it completes, so a run can be inspected step by step and, if something fails, retried from where it stopped.

**Approval.** A request for a human to approve or reject one exact action (for example "send this email with this text to this address"). Approvals exist because AI can be wrong, and some actions cannot be undone: emails and WhatsApp messages to customers, payables, purchase orders. Key rules:
- An approval is tied to the exact action. If anything in the action changed after it was requested, the decision is refused.
- Only someone holding the permission named on the approval can decide it.
- By default you cannot approve a request you caused yourself (separation of duties).
- Approvals expire (48 hours by default). An expired approval can no longer be executed; it counts as "not approved", and a workflow waiting on it carries on without that action.
- An approved action runs exactly once.

**Sandbox vs live integrations.** OpsPilot connects to 13 kinds of business system (CRM, email, helpdesk, commerce, accounting and so on). Each starts in **Sandbox** mode, which uses a built-in simulator filled with synthetic demo data. In sandbox mode nothing ever leaves OpsPilot: "sent" emails land in a sandbox outbox, purchase orders are simulated, and so on. **Live** mode calls the real provider (for example HubSpot or Zendesk), but only after an administrator has stored credentials and a **Test connection** has passed. Results are always labelled with the mode used ("tools: sandbox" or "tools: live").

**Audit trail.** Every consequential event (workflows starting and finishing, agent runs, actions executed or denied, approvals requested and decided, configuration changes) is recorded. Each record contains a fingerprint of the previous one, forming a chain. **Verify hash chain** on the Audit trail page proves nobody has altered or removed records.

**Estimates vs verified savings.** OpsPilot shows three different money/time numbers and never mixes them up:
1. **Estimated time saved**: each agent has a baseline "minutes saved per successful run". These are estimates, not measurements of your team.
2. **Estimated labour value**: estimated time saved × your loaded hourly cost. Still an estimate, not cash.
3. **Realized savings**: estimated labour value × a *realization rate* that your finance team sets after verifying real savings. It is **0 by default**, so the dashboard claims no real savings until finance says so.

See [KPI_AND_ROI.md](KPI_AND_ROI.md) for the formulas.

---

## 2. Getting started

### 2.1 Starting and stopping the app (Windows)

**To start:**
1. Open the OpsPilot project folder (for example `C:\Users\<you>\OpsPilot`).
2. Double-click **`start.cmd`** (or run it from a terminal).
3. Wait. The first start takes several minutes because it installs dependencies and builds the dashboard; later starts are quicker. The window prints `[ok]` lines as each step succeeds.
4. When you see "OpsPilot is running", your browser opens the dashboard automatically.

What `start.cmd` does for you: finds Python 3.10+ and Node.js 20+, installs what is missing, creates a `.env` settings file with fresh random secrets on first run, frees ports used by an old OpsPilot run, prepares the database and demo data, starts the API, then builds and starts the dashboard.

| Address | What it is |
|---|---|
| http://localhost:3000 | The dashboard (this guide) |
| http://127.0.0.1:8000/docs | Interactive API documentation (for technical users) |
| http://127.0.0.1:8000/mcp | Endpoint for connecting AI clients such as Claude Desktop (see the appendix) |

If port 3000 or 8000 is used by another program, the launcher picks the next free port and prints it. Always use the addresses it prints.

**Useful options** (run from a terminal in the project folder):

| Command | Effect |
|---|---|
| `start.cmd` | Normal start |
| `start.cmd -Workers 2` | Also start 2 separate background worker processes (more throughput; see [Scale and workers](#411-scale-and-workers)) |
| `start.cmd -Dev` | Dashboard in development mode (for developers) |
| `start.cmd -ApiPort 8100 -WebPort 3100` | Use other ports |
| `start.cmd -NoBrowser` | Do not open the browser |
| `start.cmd -Reinstall` | Reinstall all dependencies from scratch |

**To stop:** double-click **`stop.cmd`**. It stops everything `start.cmd` started.

**If it does not start:** run `powershell -ExecutionPolicy Bypass -File scripts\doctor.ps1`. It checks every piece and prints the exact fix for each problem. Log files are in the `.run\logs` folder. See [Troubleshooting](#10-troubleshooting-and-faq).

### 2.2 Signing in

1. Go to http://localhost:3000. You are sent to the **Sign in** page.
2. If something is wrong with the API, a warning appears under the heading: a red box when the API cannot be reached (it tells you to run `start.cmd` or `scripts\doctor.ps1`), or a notice when it reports a degraded state. When everything is fine, no status is shown.
3. Enter your **Email** and **Password**, then click **Sign in**. OpsPilot finds your workspace from your email. Only if the same email and password belong to several workspaces does it ask for the **Workspace** (its id, for the demo `acme-demo`); you can also open that field yourself with **Sign in to a specific workspace**.

**New company? Create a workspace.** Click **Create a workspace** under the sign-in form, enter your company name, your name, work email and a password (10+ characters with letters and numbers), and click **Create workspace**. You are signed in as the workspace admin straight away. Leave **Start with sample data** on (recommended): every system starts in sandbox mode filled with sample customers, orders, invoices and documents, so all 25 agents, every workflow and the Copilot work immediately. Connect your real systems later in **Integrations**. (Technical admins can turn self-serve sign-up off with `ALLOW_SIGNUP=false`.)

On a development installation, a **Demo accounts** panel appears below the form. Click any account card to fill in the form, then click **Sign in**. All demo accounts use the password `OpsPilot-Demo-2026!` (local development only; deployments set their own `DEMO_PASSWORD`).

| Demo account | Name | Role | In short, this person can... |
|---|---|---|---|
| admin@acme-demo.test | Avery Admin | admin | Do everything in the tenant, including settings, users, emergency stop |
| ops@acme-demo.test | Olive Operator | operator | Use the Copilot, run agents and workflows, manage tasks and documents |
| approver@acme-demo.test | Ravi Reviewer | approver | Approve or reject any pending action, including customer emails and WhatsApp messages |
| finance@acme-demo.test | Fiona Finance | finance_approver | Approve payables, purchase orders and other general approvals |
| auditor@acme-demo.test | Ana Auditor | auditor | Read the audit trail, reports and admin settings (read-only) |
| viewer@acme-demo.test | Vic Viewer | viewer | Look at dashboards (read-only) |

Full details are in [Roles and permissions](#3-roles-and-permissions).

Your session lasts 120 minutes by default. When it expires you are returned to the sign-in page with a "session expired" message; just sign in again. To sign out, open the account menu (top right) and choose **Sign out**.

### 2.3 Demo data you can use

The demo tenant (`acme-demo`, "Acme Demo Co.") is filled with synthetic records. Use these ids when trying agents, workflows and the Copilot:

| Area | Ids and notes |
|---|---|
| Leads | `L-1001` Priya Natarajan (Northwind Logistics), `L-1002` Tom Becker (Becker Bakes, unsubscribed), `L-1003` Mei Chen (Finova) |
| Sales teams | Enterprise, Mid-Market, SMB (routing by company size) |
| Price list | `SKU-001` to `SKU-005` (platform seats, implementation, support, custom integration); proposal template `TPL-STD` |
| Customers | `C-2001` Jordan Rivera (VIP, WhatsApp opt-in, phone +15550100123), `C-2002` Lena Hoffmann, `C-2003` Kwame Mensah, `C-2004` Sofia Marin, `C-2005` Ibrahim Khan |
| Orders | `ORD-5001` to `ORD-5007` (`ORD-5002` has a shipment exception, `ORD-5005` failed payment, `ORD-5007` cancelled) |
| Products | `P-100` to `P-105` (headphones, earbuds, backpack, 4K monitor, keyboard, bottle) |
| Inventory SKUs | `SKU-AUR-HP`, `SKU-AUR-EB`, `SKU-NIM-BP`, `SKU-SUM-MON`, `SKU-BR-KB`, `SKU-TR-WB` |
| Purchase orders / receipts | `PO-7001` (fully received), `PO-7002` (half received) |
| Invoices (receivables) | `INV-9001` to `INV-9006` (`INV-9004` disputed, `INV-9005` paid) |
| Expense claims | `EXP-1` to `EXP-7` (include a duplicate, a missing receipt, a prohibited category, a late submission) |
| Suppliers / RFQ | `SUP-1` to `SUP-4` (`SUP-4` not approved); RFQ `RFQ-42` with quotes `Q-1`, `Q-2`, `Q-3` |
| Meetings | `MTG-1` "Q4 launch planning" (transcript included) |
| SOPs | processes `customer_onboarding` and `refund` |
| Metrics | `orders_total`, `revenue_usd`, `support_tickets`, `site_conversion`, `ad_spend_usd` |
| Releases | service `checkout-api`, deployment `DEP-301` (error rate and latency rose after it); `search-api` / `DEP-290` |
| Issues | `ENG-1` to `ENG-4` in project `ENG` |
| Test environments | `staging`, `qa-sandbox` (authorised), `production` (never authorised for tests) |
| Knowledge base | "Shipping & Returns FAQ", "Payment & Billing FAQ" (collection `kb`), a Northwind case study (`sales`), an MSA summary (`policy`) |
| Sample invoice file | `docs\samples\invoice_ok.txt` (matches `PO-7001`) |

### 2.4 The screen layout

**Sidebar (left).** Pages are grouped into four sections. You only see pages your role allows (everyone sees the Help center).

| Section | Pages |
|---|---|
| Operate | Copilot, Overview, Agents, Workflows, Approvals, Tasks |
| Observe | Analytics, Audit trail, Incidents, Evaluations, Scale & workers |
| Configure | Integrations, Documents, Admin |
| Learn | Help center |

- Next to **Agents** there is a small arrow. Click it to expand a list of departments (Sales, Support, E-Commerce, Operations, Finance, Technology); each opens the Agents page filtered to that department.
- At the bottom: a **Collapse** button that shrinks the sidebar to icons.
- On a narrow screen the sidebar is hidden; use the menu button at the top left.

**Top bar.**
- Your tenant's name and plan badge (this is where you see which tenant you are working in). A red **Emergency disable active** badge appears when an administrator has stopped all agents.
- **Search or jump to…** box: opens the command palette (below).
- **Help** (question-mark icon): opens the help article for the page you are on, or the Help center.
- **Theme toggle** (sun/moon icon): switch between light and dark mode.
- **Account menu** (your initials): shows your name, email and role badges, a **Workspace settings** link (opens Admin) and **Sign out**.

**Command palette (Ctrl+K).** Press **Ctrl+K** anywhere (the search box shows the shortcut: Ctrl K on Windows, ⌘ K on Apple computers) or click the search box. Then type to filter:
- **Actions**: **Ask Copilot…** (needs permission to run agents), **Start workflow** (needs permission to start workflows), **Toggle theme**, **Sign out**.
- **Pages**: every page you can open, plus **Workflow definitions**.
- **Agents**: every agent by name or department; select one to open its page.
- **Help** (once you type something): matching help articles, plus **Search the help for "…"**.

**Help center.** This guide and the technical documents, inside the dashboard. Open it from the sidebar (**Learn → Help center**), the question-mark icon or the command palette.
- **Start with your role** offers a reading path for each audience: **Everyday users**, **Workspace admins**, **Developers & IT** and **Executives**. The path that matches your role is marked **Your role**; each path is a numbered sequence of articles with Previous / Next links.
- The search box searches every article (try a task, a page name or a setting such as `GEMINI_API_KEY`). Results show where the words appear; the address bar keeps your search, so you can share the link.
- **Configuration reference** lists every setting in `.env`, generated from `.env.example`, with common setups (Neon, Gemini, Claude, offline).
- Articles about a dashboard page have an **Open <page>** button (shown only if your role can open that page).

If you type a question, an **Ask Copilot: "…"** row appears at the bottom. Click it or press **Ctrl+Enter** to open the Copilot with your question already typed in. Press **Esc** to close the palette.

**Common controls.** Most lists have search boxes and filters, pagination at the bottom, and copy buttons next to long ids. Times are shown as "5 minutes ago"; hover to see the exact date and time. JSON panels can be expanded and collapsed. Green, amber and red badges mean good, needs attention and problem respectively.

---

## 3. Roles and permissions

Every user has one or more **roles**. A role is a named bundle of **permissions** (written `area:action`, for example `approvals:decide`). The dashboard hides pages and disables buttons you lack permission for; buttons usually show a hint such as "Requires agents:run".

There are seven built-in (system) roles. Administrators can also create custom roles (see [Admin → Roles](#414-admin)).

### What each role can open

| Page | admin | operator | approver | finance_approver | auditor | viewer |
|---|---|---|---|---|---|---|
| Copilot | Yes | Yes | – | – | – | – |
| Overview | Yes | Yes | Yes | Yes | Yes | Yes |
| Agents | Yes | Yes | Yes | Yes | Yes | Yes |
| Workflows | Yes | Yes | Yes | Yes | Yes | Yes |
| Approvals | Yes | Yes (view) | Yes | Yes | Yes (view) | Yes (view) |
| Tasks | Yes | Yes | Yes | – | – | Yes |
| Analytics | Yes | Yes | Yes | Yes | Yes | Yes |
| Audit trail | Yes | – | – | – | Yes | – |
| Incidents | Yes | Yes | Yes | Yes | Yes | Yes |
| Evaluations | Yes | Yes | Yes | Yes | Yes | Yes |
| Scale & workers | Yes | Yes | Yes | Yes | Yes | Yes |
| Integrations | Yes | Yes (view) | – | – | Yes (view) | Yes (view) |
| Documents | Yes | Yes | Yes (search only) | – | – | – |
| Admin | Yes | Usage & quotas tab only | – | – | Tenant, Users, Roles, Usage (read-only) | – |

### What each role can do

| Action | Permission needed | admin | operator | approver | finance_approver | auditor | viewer |
|---|---|---|---|---|---|---|---|
| Use the Copilot, run agents (Playground, Bulk run) | `agents:run` | Yes | Yes | – | – | – | – |
| Start, cancel and retry workflow runs | `workflows:write` | Yes | Yes | Yes | – | – | – |
| Approve or reject actions | `approvals:decide` (plus the permission named on the approval) | Yes | – | Yes, all kinds | Yes, general approvals plus payables and purchase orders | – | – |
| Create tasks and change task status | `tasks:write` | Yes | Yes | Yes | – | – | – |
| Resolve incidents | `incidents:write` | Yes | Yes | Yes | – | – | – |
| Add and delete documents | `documents:write` | Yes | Yes | – | – | – | – |
| Search the knowledge base | `documents:read` | Yes | Yes | Yes | – | – | – |
| Enable/disable/configure agents, run evaluations | `agents:admin` | Yes | – | – | – | – | – |
| Configure, test and sync integrations; manage custom tools | `integrations:admin` | Yes | – | – | – | – | – |
| See full long texts (transcripts, documents) in runs | `data:sensitive` | Yes | – | Yes | Yes | – | – |
| Read the audit trail | `audit:read` | Yes | – | – | – | Yes | – |
| Change tenant settings, emergency stop, retry dead jobs | `tenant:admin` | Yes | – | – | – | – | – |
| Manage users / create roles / manage API keys | `users:admin` / `roles:admin` / `apikeys:admin` | Yes | – | – | – | – | – |
| See usage and quotas | `usage:read` | Yes | Yes | – | – | Yes | – |
| Onboard new tenants | `platform:admin` | Only the `platform_admin` role | – | – | – | – | – |

Notes:
- **Who can decide a given approval?** Each approval shows "requires &lt;permission&gt;". The reviewer must hold `approvals:decide` *and* that permission. The `approver` role holds every tool permission (including `email:send`, `whatsapp:send`, `accounting:write`, `procurement:commit`), so it can decide everything. The `finance_approver` role can decide approvals that require `approvals:decide`, `accounting:write` or `procurement:commit`, but not customer emails or WhatsApp messages.
- **Separation of duties:** whoever caused a request (for example the operator who started the workflow, or the user whose Copilot chat produced it) cannot approve it, even an admin. Ask a colleague.
- **Permissions also limit what agents may do on your behalf.** When you run an agent, it can only read data you are allowed to read. If it proposes an action you lack permission for, the action is not blocked: it becomes an approval that someone with that permission must decide. (Exception: workflows started by an admin run with full tool permissions.)
- The **admin** role has every permission except `platform:admin` (onboarding tenants and changing plans/quotas). That belongs to the separate **platform_admin** role, which is for whoever operates the OpsPilot installation.
- API keys (used by external systems and AI clients) have their own list of permissions, called scopes. They can never decide approvals; only signed-in people can.

<details>
<summary>Full permission list of each system role (from the code)</summary>

- **admin**: `*` (everything except `platform:admin`).
- **platform_admin**: `*` and `platform:admin`.
- **operator**: `events:read`, `events:write`, `workflows:read`, `workflows:write`, `agents:read`, `agents:run`, `approvals:read`, `integrations:read`, `reports:read`, `usage:read`, `documents:write`, all tool read permissions (`crm:read`, `email:read`, `chat:read`, `issues:read`, `helpdesk:read`, `commerce:read`, `accounting:read`, `whatsapp:read`, `workspace:read`, `monitoring:read`, `procurement:read`, `feedback:read`, `metrics:read`, `documents:read`, `tasks:read`) and low-risk write permissions (`tools:custom`, `crm:write`, `chat:write`, `issues:write`, `helpdesk:write`, `commerce:write`, `workspace:write`, `monitoring:write`, `tasks:write`, `incidents:write`, `workflows:write`).
- **approver**: `approvals:read`, `approvals:decide`, `workflows:read`, `agents:read`, `reports:read`, `tasks:read`, `data:sensitive`, `email:send`, `whatsapp:send`, `accounting:write`, `procurement:commit`, plus all tool read permissions and low-risk write permissions listed for operator.
- **finance_approver**: `approvals:read`, `approvals:decide`, `workflows:read`, `agents:read`, `reports:read`, `accounting:read`, `accounting:write`, `procurement:read`, `procurement:commit`, `data:sensitive`.
- **auditor**: `audit:read`, `reports:read`, `usage:read`, `workflows:read`, `agents:read`, `approvals:read`, `integrations:read`, `tenant:read`, `users:read`, `roles:read`.
- **viewer**: `workflows:read`, `agents:read`, `reports:read`, `tasks:read`, `approvals:read`, `integrations:read`.

</details>

---

## 4. Page-by-page guide

### 4.1 Copilot

**What it is for:** asking questions and getting work done in plain language. The Copilot decides which agents and tools to call, calls them (several at once where possible), shows every call as it happens, and writes an answer based only on the results.

**Who uses it:** operators and admins (requires `agents:run`). Other roles see a message asking for a role that includes `agents:run`.

**Layout:**
- **Left panel:** **New chat** button and your **Recent** chats. Chats are private to you. A spinning icon and "working…" mark a chat that is still answering. Hover a chat and click the bin icon to delete it.
- **Header:** the chat title, a count of what the Copilot can use (for example "25 agents · 27 tools · 0 custom tools"), and a mode badge:
  - **Gemini** or **Claude** with a model name: a live AI model plans the calls and writes the answer.
  - **Offline planner**: no AI provider is configured; a fixed rule set picks tools by keywords (see [Copilot guide](#8-copilot-guide)).
- **Empty chat:** suggested questions you can click, and a **Browse tools** link listing everything the Copilot may call, grouped into agents, tools, custom tools and platform helpers, with a filter box.
- **Message box (bottom):** **Enter** sends, **Shift+Enter** starts a new line. Up to 8,000 characters.

**How to use it:**
1. Click **New chat** (or a suggestion).
2. Type your request, for example `Where is order ORD-5002 and is anything wrong with it?`, and press Enter.
3. Watch the **Live tool-call trace**: each step shows which agent or tool was called, whether it is running, done, failed or **Needs approval**, how long it took, and links to the related approval, agent run or workflow run.
4. Read the answer. Below it you see the mode, number of tool calls, time taken, and (for live models) tokens and cost. Use the copy icon to copy the answer.
5. If anything needs approval, the answer says so and the step shows **Review approval**. The Copilot cannot approve anything itself.
6. Ask a follow-up in the same chat. You can type your next message while the Copilot is still working, but you can only send it once the current answer is finished.

If an answer fails, a red box shows the error and a **Retry** button that resends your previous message.

More detail, good questions and limits: [Copilot guide](#8-copilot-guide).

### 4.2 Overview

**What it is for:** a one-screen health check of the tenant. **Who:** everyone with `reports:read`.

**Getting started** (admins, new workspaces): a checklist of six first steps: ask the Copilot a question, run an agent on sample data, start a workflow, review an approval, connect a real system, invite a teammate. Each step ticks itself when it has actually happened in the workspace; click a step to go there. Hide it with **×**; it also disappears once all six are done. A note says when agents are on sample data or when no AI model is available.

At the top right, choose the period: **7d, 14d** (default), **30d** or **90d**.

| Tile | Meaning |
|---|---|
| Active agents | Agents enabled for your tenant / total agents. Shows how many are disabled. 0 during an emergency stop. |
| Workflows executed | Workflow runs started in the period. |
| Succeeded | Runs that completed, and their share of all runs. |
| Failed | Runs that failed or timed out. |
| Running / waiting | Runs currently pending, running or waiting for approval. |
| Estimated time saved | Sum of agents' baseline minutes for completed runs and runs waiting for approval. Marked "not verified". |
| AI cost | Model cost of runs in the period, plus an estimated infrastructure cost per run. |
| Realized savings | Finance-verified savings (zero until finance sets a realization rate in Admin → Tenant). |

Below the tiles:
- **Pending approvals** (click to open Approvals) and **Open incidents** (click to open Incidents).
- **Integration modes**: how many integrations are Sandbox, Live · connected, or Live · error / untested.
- **Runs and cost per day** chart and **Department activity** (agent runs per department; **View agents**).
- **Recent runs** (click one to open it; **All runs**) and **Recent incidents** (severity, title, source, status; **All incidents**).

### 4.3 Agents

**What it is for:** browsing the 25 agents, checking their contracts and performance, configuring them, and running them directly. **Who:** everyone with `agents:read` can browse; running needs `agents:run`; enabling/disabling, configuring and evaluating need `agents:admin`.

#### The agent list

- The header shows how many agents there are and how many are enabled.
- **Department chips** (All, Sales, Support, E-Commerce, Operations, Finance, Technology) with counts, and a **Search agents** box (searches names, descriptions, keys and use cases).
- **Grid / list** toggle at the top right.
- Each card shows the agent's name (click to open), department and version, a short description, **Enabled/Disabled**, its **risk** badge, its success rate, number of runs and total cost. A **globally disabled** badge means the agent was switched off for the whole installation and cannot be enabled per tenant. If an admin disabled it, the reason is shown in red.
- The switch on each card enables or disables the agent for your tenant (admins only). When disabling, you are asked for a reason that operators will see. Workflows that reach a disabled agent fail with `agent_disabled` until it is re-enabled.

Risk levels: **Low risk** (only low-impact actions), **Medium risk**, **High risk** (sends customer messages or stages payables), **Critical risk** (commits money, such as purchase orders).

#### Agent detail page

Open an agent to see its name, status, risk and version, and an **Enabled for tenant** switch (admins). The page has seven tabs.

**Overview tab**
- **Use cases**: what the agent is meant for.
- **Allowed tools**: every tool the agent may use, with provider, whether it is **read-only** or has a **side effect**, risk and required permission. Side-effect tools are only ever proposed; the rules decide whether a person must approve.
- **Approval rules**: the agent's own approval requirements (for example "email.send: all outbound prospect emails, requires email:send"). Tenant policies apply on top.
- **Budgets**: timeout, token budget, baseline minutes saved per run (used for estimates), department, agent key.
- **Permission scopes** and **Policies**: the agent's declared permission areas and the behavioural policies it follows (for example `no_protected_characteristics`, `never_release_payment`).
- **Tenant stats**: runs, success rate, how many needed approval, failures, average latency, cost.

**Contract tab**
Tables of every **input** field (name, type, required or optional, description) and **output** field, plus the full schema. Use this to know exactly what to put in the Playground or a CSV file.

**Configuration tab** (editing needs `agents:admin`)
- **agent_config**: a JSON object of tenant-specific settings passed to the agent. Keys the agents actually read:

  | Agent | Key | Effect |
  |---|---|---|
  | Lead Qualification | `criteria` | Scoring settings: `qualify_threshold` (default 60), `weights` (budget 25, authority 20, timeline 20, company_size 15, need 15, industry_fit 5), `min_budget` (10000), `target_industries`, `decision_titles`, `min_company_size` (20) |
  | AI Sales Development | `max_contacts_per_7_days` (2), `require_marketing_opt_in` (false), `unsubscribe_footer`, `followup_days` ([3, 7]) | Contact limits and follow-up cadence |
  | Proposal Generator | `tax_rate`, `max_discount_pct` (20) | Pricing rules |
  | Customer Support | `min_confidence` (0.5) | Below this confidence the agent escalates |
  | Complaint Resolution | `sla_hours` | SLA hours per urgency (defaults critical 4, high 8, medium 24, low 72) |
  | WhatsApp Business | `max_messages_per_hour` (5) | Outbound rate limit per number |
  | Customer Retention | `high_value_ltv` (10000) | Lifetime value above which a customer counts as high value |
  | Procurement | `weights` | Scoring weights (defaults price 0.45, lead_time 0.2, quality 0.2, terms 0.15) |
  | QA Testing | `qa_project` ("ENG") | Issue-tracker project for test-run requests |
  | Bug Triage | `critical_user_threshold` (1000) | Affected-user count that raises severity to critical |
  | Release Monitoring | `thresholds`, `oncall_channel` ("#incidents") | Alert thresholds (defaults error_rate 0.02, p95_latency_ms 800, cpu 0.85) and chat channel |

- **Model override**: leave empty to use the default model. If you set it, it must be a model id supported by the configured AI provider.
- **Save changes** / **Reset**. The **Effective settings** box shows whether the agent is enabled for the tenant and globally, the model override and any disabled reason.

**Runs tab**
The agent's run history, newest first, 10 per page. Each row shows status, time, latency, tokens and cost; click to expand:
- Run id, version, **Model** (a model name; `mock-heuristic` when no AI provider is configured; `heuristic-fallback` when the AI provider failed and the agent's built-in deterministic logic was used instead), latency, tokens, cost, start/finish times, confidence.
- **tools: sandbox / live** badges: which integration mode the agent's tools used.
- Summary, error, **Missing information**, **Warnings**, input and output data, **Evidence** references, **Proposed actions**, **Action outcomes**.

Agent run statuses: **Completed**, **Needs approval** (it proposed something now waiting in Approvals), **Needs input** (it could not proceed without more information; see Missing information), **Escalated** (it handed the case to a human, for example a support escalation), **Failed**.

Action outcome labels:

| Outcome | Meaning |
|---|---|
| Executed | Allowed by policy and carried out. A badge shows sandbox or live. |
| Approval Pending | Waiting in Approvals. Click the approval link. |
| Denied | Blocked by policy (for example emergency stop, a tool the agent may not use, a tool on the tenant's blocked list, or you lack permission for a read-only lookup). |
| Failed | Attempted but failed; the error is shown. |
| Duplicate | The identical action had already been carried out, so it was not repeated. |
| Unknown | The system could not confirm whether it happened (for example the provider timed out). It is deliberately not retried automatically. |

**Evaluation tab**
The latest automated quality test for this agent (see [Evaluations](#410-evaluations)) and a **Run evaluation** button (admins).

**Playground tab** (needs `agents:run`; the agent must be enabled)
Run the agent once with an input you write.
1. The **Payload** box is pre-filled with a known-good example input for this agent, built from the demo data (it is the agent's first evaluation test case). You can run it as is, or edit it for your own case (see the Contract tab or the [Agent reference](#5-agent-reference) for the fields). The box must contain valid JSON.
2. Click **Run agent**. The run happens while you wait (it can take a while, especially with a remote database or a live AI model).
3. The **Result** panel shows the status, latency, tokens, cost, model, tool mode, the summary, any error, missing information and warnings, the output data, evidence, confidence, proposed actions and their outcomes.
4. Click **Open workflow run** to see it as a workflow run. Playground runs are wrapped in a small automatic workflow called "Run &lt;agent name&gt;" (key `single_agent__<agent_key>`), so they are saved step by step and pause at an approval gate if anything needs approval.
5. **Reset** restores the example input.

**Bulk run tab** (needs `agents:run`; the agent must be enabled)
Run the agent over many inputs at once (up to 5,000 items). Each item is an independent agent run processed in the background.

1. Choose the input format at the top right:
   - **JSON array**: a list of input objects, `[{...}, {...}]`. Three example items are pre-filled: copies of the agent's known-good example input (email addresses are varied so the items are distinct), so you can start a test batch straight away.
   - **CSV**: paste text with a header row. Numbers, `true`/`false` and JSON cells are converted automatically, empty cells are skipped, and dotted headers such as `lead.email` build nested fields. Comma, semicolon and tab separators are detected.
2. For CSV, check **Wrap each row as**. If the agent takes one required object (for example the Lead Qualification Agent takes `lead`), this is filled in automatically and each row becomes `{"lead": {...row...}}`. Clear it to use the columns as top-level input fields. A **Preview · first item** panel shows the result.
3. Watch the status line: "N items ready", a parsing error, or a message if you exceed 5,000 items.
4. In **Run settings**, optionally enter a **Name**, then choose:
   - **Execute actions ON**: proposed actions go through the policy rules exactly as normal. Safe ones run; consequential ones wait in Approvals.
   - **Execute actions OFF (dry run)**: actions are only proposed, nothing is executed and no approvals are created. Use this first to check the results.
5. Click **Start bulk run · N**. Every item is checked against the agent's input contract before anything runs. If any items do not match, nothing starts and a list shows the bad item numbers and why (up to 20).
6. **Live progress** shows a progress bar, **Succeeded**, **Needs review**, **Failed** and **Remaining** counts, elapsed time, throughput, estimated time left and cost. **Cancel** stops the remaining queued items (items already running finish; completed results are kept).
7. The **Items** table (25 per page, filter by status) shows each item's status, result summary or error, latency, **Review approval** and **Agent run** links, and its input (arrow button).

Item statuses: **Queued**, **Running**, **Completed**, **Needs review** (an approval was created, or the agent needed input or escalated), **Failed** (one bad item never stops the others), **Cancelled**.

**Recent bulk runs** lists earlier batches for this agent with progress and OK / review / failed counts; click a name to reopen its progress.

### 4.4 Workflows

**What it is for:** starting and following multi-step processes. **Who:** everyone with `workflows:read` can view; starting, cancelling and retrying need `workflows:write` (admin, operator, approver).

#### Workflow runs list

- **Definitions** button opens the workflow templates; **Start workflow** opens the start dialog.
- Search by run id, correlation id or workflow key; filter by status and by workflow. Links from other pages (for example a workflow name in Analytics) open this list already filtered.
- Columns: **Status**, **Workflow** (name and version; single-agent runs appear as "Agent: &lt;agent key&gt;"), **Run** id (copy button), current **Node** (step), **Steps** executed, **Cost**, **Time saved** (estimate), **Created**. Click a row to open it. 25 runs per page.

Run statuses:

| Status | Meaning |
|---|---|
| Pending | Queued, waiting for a worker to pick it up (also shown briefly after an approval decision or a retry). |
| Running | A worker is executing steps. |
| Waiting approval | Paused at an approval gate because at least one action is waiting in Approvals. It continues automatically once every pending approval for the run is decided or expires (an expired approval counts as not approved). The time spent waiting does not count against the run's deadline. |
| Waiting input | Defined in the product but not normally used by the built-in workflows. |
| Completed | Finished. |
| Failed | A step failed and the workflow had no alternative path, or temporary errors kept happening (3 attempts). An incident is opened. |
| Timed out | The run's own processing passed its deadline (see [Workflow reference](#7-workflow-reference)); waiting for approval is not counted. An incident is opened. |
| Cancelled | Someone cancelled it. |

#### Starting a workflow

1. Click **Start workflow** (or press Ctrl+K and choose **Start workflow**, or click **Start** on a definition card).
2. Choose the **Workflow**. A description and badges (number of nodes, timeout, platform/tenant) appear.
3. The **Input payload** box is pre-filled with a working example that uses the demo data (listed in the [Workflow reference](#7-workflow-reference)). Start it as is to try the workflow, or replace the values with your own. Tenant-specific workflows without a built-in example are pre-filled with their input fields and empty values. It must be valid JSON.
4. Click **Start run**. You are taken to the run page. Double-clicking cannot start the same run twice.

The input is checked against the first agent's input contract **before** any run is created. If it does not fit, nothing starts and the error ("Invalid input for agent '…'", a validation error) lists the bad or missing fields; correct them and click **Start run** again. The same check applies when the Copilot or an AI client (MCP) starts a workflow. Workflows started by inbound events from other systems are not checked this way; a bad event creates a run that fails at its first step.

#### Run detail page

- Header: workflow name, status, a **cancel requested** badge if applicable, version, **attempt N** if it was recovered or retried, the run id and correlation id (copy buttons). The correlation id links everything this run caused: agent runs, actions, approvals and audit records.
- Buttons: **Refresh**, **Retry** (only for Failed or Timed out runs), **Cancel run** (Pending, Running or Waiting approval runs).
- A red box shows the error code and message, if any.
- An amber box lists approvals blocking the run, each with a **Review** button.
- Key facts: created, started, finished, **Deadline**, current node, steps, AI cost, estimated time saved, actor (who started it) and, for delegated runs, the parent run.
- **Execution graph**: the workflow drawn as boxes and arrows. Colours: green Completed, red Failed, amber Waiting / needs approval, blue Needs input, grey Not reached; the current node is outlined. Arrow labels: **yes**/**no** (decision points), **branch**/**join** (parallel steps), **on failure**, **needs input**.
- **Checkpoints**: a timeline of every step attempt (most recent first): step number, node name and type, status, duration, which step comes next, and "waiting" when it paused for approval. A checkpoint is simply the saved record of a step.
- **Agent runs**: each agent invocation in the run (expand for the same details as on the agent's Runs tab).
- **Input**, **Output** (summaries, statuses, actions, missing information, warnings, time saved, cost) and **Raw state**.

The page refreshes itself every 4 seconds while the run is active.

**Cancel run:** the run stops at its next step. Actions already carried out are **not** undone. Approvals still pending for the run are marked "superseded" and can no longer be approved.

**Retry:** continues a Failed or Timed out run from the step where it stopped, with a fresh 10-minute deadline.

#### Definitions page

One card per workflow template: name, description, **Start** button, badges (key, version, platform or tenant scope, active/inactive, timeout, number of nodes), the **Trigger** (which business events start it automatically, a schedule, or manual), the agents it uses, a small graph and the **Graph JSON**.

A collapsible section lists **auto-generated single-agent wrappers** (one per agent that has been run from its Playground). Each has a **Playground** button that opens that agent's Playground tab, which is the place to run a single agent.

### 4.5 Approvals

**What it is for:** reviewing every consequential action an agent (or the Copilot) proposed, and approving or rejecting it. **Who:** everyone with `approvals:read` can view; deciding needs `approvals:decide` plus the specific permission the approval names. Without `approvals:decide` the page shows a "read-only" badge.

#### The approvals list

- Tabs: **Pending**, **Decided** (approved, executed, execution failed, rejected, expired) and **All**.
- Filters: risk level and agent.
- Columns: **Risk**, **Action** (action type and tool), **Agent**, **Status**, **Requested**, **Expires** (on Pending; red when less than 2 hours remain) or **Reviewer** (on other tabs), and a **Decide** / **View** button. Click any row to open the review panel. 25 per page.

Approval statuses:

| Status | Meaning |
|---|---|
| Pending | Waiting for a decision. |
| Executed | Approved, and the action ran successfully (exactly once). |
| Execution failed | Approved, but the action failed when it ran. See the execution result. |
| Approved | Momentary state between approval and execution. |
| Rejected | A reviewer rejected it. The action will not run. |
| Expired | Nobody decided in time. It counts as not approved: the action never runs, and a workflow waiting on it continues without it. Re-run the agent if the action is still needed. |
| Superseded | Cancelled because its workflow was cancelled, or invalidated because the action no longer matched what was requested. |

Risk levels on approvals: **Low / Medium** (internal changes), **High** (customer communications, payables, rollback recommendations, compensation), **Critical** (financial commitments such as purchase orders, or proposals with non-standard terms).

#### Why is this action waiting?

The **Policy** field in the review panel tells you which rule required approval:

| Policy | Reason |
|---|---|
| `platform.critical_risk` | The tool is critical-risk (purchase orders). Always needs approval. |
| `agent.explicit` | The agent itself asked for approval (for example proposal delivery, order status changes, rollback recommendations). |
| `agent.<agent_key>.approval_rule` | One of the agent's declared approval rules matched. |
| `tenant.amount_threshold` | The action involves an amount above the tenant's threshold (default $1,000). |
| `platform.external_comms` | Outgoing customer communication (email or WhatsApp). |
| `platform.high_risk` | A high-risk tool or action. |
| `tenant.strict_mode` | The tenant is in strict approval mode (every side-effect action needs approval). |
| `platform.permission_escalation` | The person who started the work lacks the permission for this action, so someone who has it must approve. |

#### How to review and decide

1. Open **Approvals**, stay on **Pending**, and click a row (or click **Review approval** from a workflow run, Copilot step or bulk run).
2. In the panel, check:
   - Status, risk, time left before expiry, and **requires &lt;permission&gt;** (you must hold it).
   - The agent's summary of the situation.
   - **Exact action payload**: precisely what will be sent or written. This is what you approve, nothing else. Its fingerprint (**payload hash**) is shown below it.
   - **Agent**, **Tool**, **Node**, **Policy**, **Reason** (why the policy requires approval), **Agent reason** (why the agent proposed it), **Requested by**, **Expires**.
   - **Evidence**: references to the records the agent relied on (for example `crm:lead:L-1003`, `document:<id>#chunk:2`).
   - **Input preview**: the input the agent worked from.
   - **Open workflow run** to see the whole context.
3. Optionally type a **Reviewer note** (it is saved with the decision and in the audit trail).
4. Click **Approve** and confirm. The action runs immediately, exactly once. A message tells you whether it **executed** or failed, and the execution result appears in the panel. Or click **Reject**: a note is **required** to reject. The action is discarded.
5. If the approval belonged to a workflow run, the run resumes automatically once all of its pending approvals are decided.

Things that can stop a decision:
- "Separation of duties: the requester cannot review their own request": ask a colleague.
- "Reviewer lacks '...'": you do not hold the permission named on the approval.
- "The action was modified after this approval was requested": the payload changed; a new approval is needed.
- "Approval has expired" or "Approval is already ...": it can no longer be decided. (An expired approval is then treated as not approved, and its workflow continues without the action.)
- "Agents are emergency-disabled for this tenant…": while the emergency stop is on, **Approve** is refused. **Reject** still works.

Tips:
- Approvals expire after 48 hours by default (Admin → Tenant → Approval TTL).
- Read the payload, not just the summary: for emails, check the recipient, subject and body.
- During an emergency stop you can still clean up the queue by rejecting requests you do not want (see [Emergency stop recipe](#recipe-9-emergency-stop)).

### 4.6 Tasks

**What it is for:** the to-do board for work created by agents (meeting action items, remediation tasks, review tasks, escalations) and by people. **Who:** `tasks:read` to view; `tasks:write` to create tasks and change status.

- **New task** opens a form: **Title** (required), **Description**, **Priority** (Low, Medium, High, Critical), **Due** date and time, **Owner name**, **Labels** (comma-separated). Click **Create task**.
- Filters: search by title, status, and an **Overdue only** switch (due date passed and not done or cancelled).
- Columns: **Task** (title, description, labels), **Status** (a drop-down you can change if you have `tasks:write`: Open, In Progress, Blocked, Done, Cancelled), **Priority**, **Owner** ("unassigned" if none), **Due** (red with "(overdue)" when late), **Escalation** level (L1, L2… set by the Workflow Coordinator when an escalation is approved), **Source** ("agent" or "manual", with a **run** link to the workflow that created it), **Evidence** (hover to see the references). Tasks are sorted by due date; 50 per page.

Labels agents add include `meeting`, `needs-clarification` (the agent could not resolve the owner or details; check them), `escalated`, `retention`, `sop`, `compliance`, `ap`, `exception`, `expenses`, `review`, `ar`, `collections`, `procurement`, `qa`, `research`.

### 4.7 Analytics

**What it is for:** operational KPIs, return on investment and per-agent performance. **Who:** `reports:read`. Choose the period at the top right (7, 14, 30 (default) or 90 days).

**KPI tiles**

| KPI | In plain terms |
|---|---|
| Workflow runs | How many workflow runs started in the period. |
| Completion rate | Of runs that have finished (completed, failed, timed out or cancelled), the share that completed. |
| Failure rate | Of finished runs, the share that failed or timed out. Turns red above 10%. |
| Cost per successful workflow | Total AI spend divided by completed runs. |
| Median latency (and p95) | Typical time from start to finish of completed runs; p95 is the time 95% of runs finish within. |
| Tokens consumed | Amount of AI model text processed (input plus output), a driver of AI cost. |
| Tool failure rate | Share of tool calls that failed. The hint shows total tool calls and how many changed something. |
| Duplicate actions suppressed | How many repeated actions were recognised and not executed twice. |
| Approval rate | Of decided approvals, the share approved. The hint shows how many were requested. |
| Approval latency | Average time from request to decision. |
| Human intervention rate | Share of agent runs that needed approval or more input. |
| Validation failures | Agent runs that failed because the input or the AI output did not match the required format. |

**ROI card:** **Estimated time saved** (estimate from agent baselines), **Estimated labor value** (time × loaded hourly cost; an estimate, not cash), **Realized savings** (labour value × the finance-verified realization rate), **Net estimated value** (labour value minus AI cost minus infrastructure cost). The **Assumptions** box shows the loaded hourly cost, infrastructure cost per run, realization rate and monthly platform fee; change them in Admin → Tenant.

**Agent performance** table (click a column heading to sort): runs (with ok / failed / approvals / needs-input breakdown), success rate, intervention rate, p50 and p95 latency, cost per success, cost, tokens, warnings.

**Workflow performance** table: runs, completed, failed, waiting, cost, time saved per workflow.

Click a workflow name to open the Workflows list filtered to that workflow.

**Usage & quotas** (bottom): this month's workflow runs and AI tokens against your plan's quotas (amber above 80%, red above 95%), the maximum concurrent runs, and metered usage by kind with cost.

> **Known issues:** the "duplicate external action rate" in the Duplicate actions suppressed hint is currently always reported as 0%. **Net estimated value** subtracts AI and infrastructure cost but not the monthly platform fee, whereas [KPI_AND_ROI.md](KPI_AND_ROI.md) also subtracts the fee.

### 4.8 Audit trail

**What it is for:** a tamper-evident record of everything consequential. **Who:** `audit:read` (admin, auditor).

- **Verify hash chain**: checks that every record still links correctly to the previous one. A green banner ("Chain intact — N events verified") means nothing was altered or removed. A red banner shows where the chain breaks; report this to your security team immediately.
- Filters: free-text search (action, resource id or actor id), **action prefix** (for example `approval.`), **severity** (Info, Warning, Critical) and **correlation id** (paste one from a workflow run to see everything it caused).
- Columns: time, severity, action, actor (type such as user, agent, system, api_key, and id), resource (type and id), correlation id. Click a row to see the full ids, the record's hash and the previous record's hash, and the details. 50 per page.

Common actions you will see: `workflow.started`, `workflow.completed`, `workflow.failed`, `workflow.timed_out`, `workflow.cancelled`, `workflow.cancel_requested`, `workflow.retry`, `workflow.recovered`, `agent.run`, `action.executed`, `action.denied`, `approval.requested`, `approval.approved`, `approval.rejected`, `approval.expired`, `approval.tampered`, `copilot.turn`, `batch.created`, `task.created`, `task.updated`, `incident.resolved`, `document.uploaded`, `document.deleted`, `agent.configured`, `integration.configured`, `integration.tested`, `custom_tool.created` / `updated` / `deleted` / `tested`, `tenant.updated`, `tenant.emergency_disabled`, `tenant.emergency_enabled`, `user.created`, `user.updated`, `role.created`, `apikey.created`, `apikey.revoked`, `event.received`, `webhook.signature_invalid`, `job.retried`, `workflow_definition.created`.

### 4.9 Incidents

**What it is for:** problems that need a person's attention. **Who:** `reports:read` to view; `incidents:write` to resolve.

Incidents are opened automatically when a workflow fails, times out or exceeds its quota, and by agents that find something significant (SOP violations, cost anomalies, budget breaches).

- Choose **Open** (default), **Resolved** or **All**.
- Columns: severity, incident title and kind, source (`orchestrator` for workflow problems, `agent` for agent findings), status, created, and actions: **Run** (opens the related workflow run) and **Resolve**.
- Click a row to see the details (for example the workflow, node and error).

Kinds: `workflow_failed`, `workflow_timeout`, `quota_exceeded`, `policy_violation` (SOP Compliance), `cost_anomaly` (Finance-Aware Business Analyst), `agent_finding`.

**To resolve:** investigate (open the run, fix the cause, retry if needed), then click **Resolve** and confirm. Resolving is recorded in the audit trail.

### 4.10 Evaluations

**What it is for:** measuring each agent's quality with a fixed set of test cases ("synthetic dataset") before trusting it, after changing its configuration or model, or after a provider change. **Who:** everyone with `agents:read` can view; running needs `agents:admin`.

- A badge shows how many agents pass all their cases.
- **Run all** evaluates every agent (confirm first; it runs while you wait and can take a long time). Each row also has a **Run** button.
- Columns: agent (with version and model used), **Result** (Passed / Failing / not evaluated), **Accuracy** (share of cases that passed every check), **Cases** passed, **Unsupported claims** (cases where the agent warned that something was unsupported or discarded), **Intervention** (share of cases that needed approval, input or escalation), **p50 / p95** latency, **Cost / case**, **Last run**.
- Click a row to see each case and each check: ✓ or ✗, what was expected and what the agent produced.
- The agent detail page's **Evaluation** tab also shows extraction precision and recall where the dataset measures them.

> **Known issue:** evaluation results are not separated by tenant. On an installation with several tenants, the page shows the most recent evaluation of each agent, whichever tenant ran it.

Evaluations only propose actions; they never execute anything. They do call the configured AI model, so they consume tokens and quota. If the AI provider is unavailable or out of quota, agents fall back to their built-in logic and the model column shows `heuristic-fallback`; those results tell you nothing about the AI model's quality.

### 4.11 Scale and workers

(Sidebar: **Scale & workers**.) **What it is for:** watching the background job queue that runs workflow steps, Copilot answers and bulk-run items, and the worker processes that do the work. **Who:** `reports:read`; retrying dead jobs needs `tenant:admin`.

The page refreshes every 3 seconds; **Pause** / **Resume** stops and restarts this.

| Tile | Meaning |
|---|---|
| Queued | Jobs waiting to run. |
| Running | Jobs being worked on, out of the available slots. |
| Done · last hour | Jobs finished in the last hour. |
| Dead | Jobs that failed every allowed attempt. The hint shows jobs that failed but will be retried. |
| Oldest ready lag | How long the oldest waiting job has waited (amber above 30 seconds: workers cannot keep up). |
| Alive workers | Worker processes that reported in within the last 30 seconds. "no live workers" in red means nothing is processing jobs. |
| Total concurrency | Jobs that can run at the same time on live workers. |
| Worker mode | **Thread**: jobs run inside the API process (default). **Db**: separate worker processes do the work. |

- **Workers** table: name, host, process id, slots, status (**Alive**, **Lost**: stopped reporting, its jobs are handed to others; **Stopped**), active jobs, processed, failed, last seen.
- **Jobs by kind**: bars per job type (`workflow.execute`, `copilot.turn`, `batch.item`, `maintenance`) coloured by status.
- **Recent jobs**: kind, id, last error (hover for the full text), status, attempts, worker, created, finished. Dead jobs have a **Retry** button (admins): fix the cause first, then retry.
- **How to scale** card: start more workers with `start.cmd -Workers 4`, or start workers on other machines that share the same database.

### 4.12 Integrations

**What it is for:** connecting OpsPilot to your business systems, browsing every tool, adding your own HTTP tools and connecting AI clients. **Who:** `integrations:read` to view; configuring, testing, syncing and managing custom tools need `integrations:admin` (admin).

The header shows how many integrations are sandbox and live, and a **Connect an AI client (MCP)** button. There are three tabs.

#### Providers tab

One card per system family (13): CRM, Email, Team chat, Issue tracker, Helpdesk, Commerce, Accounting, WhatsApp Business, Google Workspace, Monitoring, Procurement, Feedback sources, Metrics warehouse.

Each card shows:
- A mode badge: **Sandbox**, **Live · connected**, **Live · untested** or **Live · error**.
- For sandbox: which live providers are available for this family (or "no live adapter yet"). For live: the live provider in use.
- **Status** (Sandbox, Pending test, Connected, Error), **Last test** (ok/failed and when), **Last sync**, **Secrets** (whether credentials and a webhook secret are stored), the last error, **Capabilities**, **Scopes**, and the number of tools (hover to list them).
- Buttons: **Configure**, **Test connection**, **Sync**.

Real systems you can connect in this version:

| Family | Connector | What the form asks for | Live operations |
|---|---|---|---|
| Team chat | **Chat webhook** (Slack, Microsoft Teams, Google Chat, Discord) | The channel's incoming-webhook URL | Post messages (one channel per webhook) |
| Team chat | Slack (bot) | Bot token (`xoxb-…`) | Post to any channel the bot is in, list channels |
| Email | **SMTP** (Gmail, Outlook / Microsoft 365, any mail server) | Server, port, username, password (an app password for Gmail/Outlook), From address | Send email |
| Email | SendGrid | API key, From address (verified sender) | Send email, list templates |
| CRM | HubSpot | Private app access token | Find, read, list, create and update contacts; customers; log notes; activity history |
| Helpdesk | Zendesk | Subdomain, agent email, API token | Create, read, list and update tickets (status, priority, tags, internal note); customer case history |
| Issue tracker | Jira Cloud | Site URL, account email, API token | Search, read, create, comment, update fields, change status through the workflow; list projects |
| Commerce | Shopify | Shop domain, Admin API token | Products, search, price and stock, inventory, orders, shipments, sales history; update order notes/tags and listings |
| WhatsApp Business | Meta Cloud API | Phone number ID, access token | Send template and text messages |

Each form has a **Where do I find these?** link to the provider's own instructions.

Accounting, Google Workspace, Monitoring, Procurement, Feedback sources and Metrics warehouse have no live connector yet: agents use the workspace's records for them. To call your own systems, add a [custom tool](#custom-tools-tab).

**What happens to operations a connected system does not cover.** Some data only exists in OpsPilot: price lists, sales teams, support and delivery policies, brand guidelines, supplier lead times, marketing consent, and OpsPilot's own email/WhatsApp templates and outbox. These keep coming from the workspace's records (marked `source: workspace`) when the system is live. Everything else a connected system does not support is refused with a clear message. OpsPilot never answers with sample data, and never pretends to have performed an action in a live system.

**To connect a real system:**
1. On the system's card click **Configure**.
2. Choose the connector (for example **SMTP** or **HubSpot**) instead of **Sample data (sandbox)**.
3. Fill in the fields. Secrets are stored encrypted and never shown again; when editing, leave a secret blank to keep the saved one.
4. Click **Save and test connection**. On success the dialog closes and the status becomes **Connected**: from now on agents use the real system. On failure the dialog stays open and shows the provider's error so you can fix the values.
5. Optional, under **Advanced**: display name, webhook signing secret (verifies events the system sends to OpsPilot), scopes, extra settings.

To go back to the simulator, open **Configure**, choose **Sample data (sandbox)** and click **Use sample data**. Until a live connection has passed its test, tools keep using the sandbox; the "tools: sandbox / live" badge on agent results shows which was used.

**Test connection** on a sandbox integration just checks the simulator. **Sync** only records a sync time stamp; it does not import data.

#### Custom tools tab

Lets administrators register their own REST endpoints (for example an internal order system) as tools the **Copilot** can call. The table shows each tool's name and description, method and URL, whether an auth secret is set, behaviour (**read-only** or **side effect · approval**), risk, number of calls, last call, an **Enabled** switch, and **Test**, edit (pencil) and delete (bin) buttons. Custom tools are **Copilot-only**: agents, workflows and AI clients connected over MCP cannot call them. Users need the `tools:custom` permission (admin, operator, approver) for the Copilot to offer these tools to them.

Safety rules applied to every custom tool:
- Only **https** addresses on the public internet. Addresses that resolve to local, private or link-local networks are refused; redirects are not followed; responses are capped at 256 KB.
- Inputs are checked against the tool's input schema before any request is sent.
- Secrets are write-only and stored encrypted.
- Read-only tools run directly when the Copilot calls them. Tools marked **Has side effects** always create an approval first (the approval requires `approvals:decide`).
- Every call and test is recorded in the audit trail.

How to create one: see [Recipe 7](#recipe-7-add-a-custom-http-tool).

#### Tool catalog tab

A searchable list of every tool: the 98 built-in tools plus your custom tools.
- Search (key, name, description or agent), **All / Built-in / Custom**, and filters for provider, effect (read-only or side effect) and risk.
- Columns: tool key (custom tools show their HTTP method and a **custom** badge), provider, side effect, risk, required permission, **Used by** (how many agents may use it, hover for the list; custom tools show "Copilot"), and calls in the last 30 days.

The full list with explanations is in the [Tool reference](#6-tool-reference).

#### Connect an AI client (MCP)

Shows the MCP endpoint address, a configuration snippet for Claude Desktop, Claude Code, Cursor or another MCP client, the list of tools offered, and a **Create an API key** link (admins). See [Recipe 6](#recipe-6-connect-claude-desktop-or-claude-code-via-mcp).

### 4.13 Documents

**What it is for:** the knowledge base agents use to answer questions (FAQs, policies, case studies, SOPs). Agents such as Customer Support, WhatsApp Business and AI Sales Development search it and cite the passages they used. **Who:** `documents:read` to view and search (admin, operator, approver); `documents:write` to add and delete (admin, operator).

**Search the knowledge base** (top card): type at least 2 characters. Results show exactly what agents would find: document name, collection, section heading, a relevance score, the passage text and its reference (`document:<id>#chunk:<n>`, the same reference agents cite as evidence).

**Document list:** filter by collection. Columns: document name (with type and fingerprint), **Collection**, **Classification**, **Scan** status (**Clean** or **Flagged**, with the number of findings), **Chunks** (passages it was split into), size, added, and a delete button.

**To add a text document:**
1. Click **Add text document**.
2. Enter a **Name**.
3. Choose a **Collection** (default `kb`; existing collections are suggested). Collections group documents, for example `kb`, `sales`, `policy`.
4. Choose a **Classification** (Public, Internal, Confidential, Restricted).
5. Paste the **Text**. Use headings (lines starting with `#`) to divide it into sections; each section becomes one or more searchable passages, and the heading is shown with search results.
6. Click **Add document**.

On saving, the text is scanned for things that should not be in a knowledge base: credentials and API keys, possible card numbers, and text that tries to give instructions to an AI ("ignore previous instructions…"). If a serious finding is detected, the document is saved but marked **Flagged** and is **excluded from search**, so agents cannot use it. Remove the offending content and add the document again.

Notes:
- Classification is currently a label for people; it does not restrict which agents or users can retrieve the document.
- Deleting a document removes its passages; agents can no longer cite it.
- Uploading files (txt, md, csv, json, pdf, up to 25 MB) is available through the API, not the dashboard (see [API.md](API.md)). PDF text extraction is basic.

### 4.14 Admin

**What it is for:** tenant settings, people, roles, API keys and usage. You only see the tabs your permissions allow (open it from the sidebar or the account menu's **Workspace settings**).

#### Tenant tab (view: `tenant:read`; change: `tenant:admin`)

**Emergency disable.** A red panel with a switch. Turning it on stops all agents for the tenant immediately (see [Recipe 9](#recipe-9-emergency-stop)). You must type `DISABLE` to confirm. It is recorded as a critical audit event. While active, a red badge shows in the top bar.

**Tenant card.** Shows the slug, plan, status and tenant id. You can change the **Display name** and **Retention (days)** (7–3650), then click **Save**. Retention: business events older than this are deleted by the background maintenance job (it runs about once a minute); audit records are kept longer: at least twice the retention period, minimum 730 days.

**ROI assumptions.** **Loaded hourly cost (USD)**, **Infra cost per run (USD)**, **Realization rate (0–1)** (the share of estimated savings finance has verified; leave 0 until verified), **Monthly platform fee (USD)**. Click **Save assumptions**. These drive the Overview and Analytics savings figures.

**Approval policies.**

| Setting | Effect |
|---|---|
| Approval mode | **Standard**: only risky actions need approval. **Strict**: every action that changes something needs approval. |
| Amount threshold (USD) | Any action whose amount (or total) is above this needs approval. Default 1000. |
| Approval TTL (hours) | How long a pending approval stays valid. Default 48. |
| Separation of duties | When on (default), nobody can approve a request they caused. |
| External communications require approval | When on (default), outgoing customer messages need approval. Emails and WhatsApp template messages are high-risk and still need approval even when this is off; the switch mainly affects free-text WhatsApp replies. |
| Auto-approve rules | A JSON list of narrow exceptions that let specific external messages or high-risk actions run without approval (never critical-risk actions, never actions an agent's own rule requires approval for). Format: `[{"name": "...", "tool": "whatsapp.send_template", "conditions": {"template_id_in": ["order_update"], "channel_in": [...], "max_amount": 100}}]`. |

Click **Save policies**. Saving only changes the settings shown in the form; other policy settings stored for the tenant (for example a list of blocked tools set through the API) are kept.

#### Users tab (view: `users:read`; manage: `users:admin`)

- The table lists every user with their roles, status (Active / Deactivated) and an **Active** switch (you cannot deactivate yourself). Deactivated users cannot sign in.
- **Invite user**: Email, Full name, optional Password (minimum 12 characters; leave empty for single-sign-on-only users) and roles (viewer is preselected). Click **Create user**.
- **Edit roles**: change the full name and roles, then **Save**.
- You can only grant roles whose permissions you hold yourself, and you cannot remove your own admin role.

#### Roles tab (view: `roles:read`; create: `roles:admin`)

- Lists every role with a **system** or **custom** badge, the number of users, and its permissions (expand to see them). System roles are maintained by the platform.
- **Create role**: a name (lowercase letters, digits and underscores, 2–64 characters), a description, and permissions picked from the catalogue grouped by area (each group has an **all** link). You cannot grant permissions you do not hold.

#### API keys tab (`apikeys:admin`)

API keys let external systems (event producers, MCP clients) call OpsPilot without a user login.
- **Create key**: Name, optional **Expires in (days)** (1–3650; empty means never) and scopes (permissions; `events:write` is preselected). Scopes are limited to permissions you hold.
- The full key is shown **once**. Copy it into your password manager or secret store, then click **I have stored the key**. Afterwards only its prefix is visible.
- The table shows name, prefix, scopes, status (Active, Expired, Revoked), created, expires and last used. **Revoke** stops a key immediately; this cannot be undone.

#### Usage & quotas tab (`usage:read`)

The same quota and metered-usage cards as at the bottom of Analytics.

#### Tenants tab (`platform:admin`)

Shown only to people whose role explicitly includes `platform:admin` (the `platform_admin` role); ordinary tenant admins do not see it. Lists every tenant on the installation (plan, status, emergency state, retention, quotas). **Onboard tenant** creates a new tenant: slug (3–64 lowercase letters, digits, hyphens), name, plan (starter, growth, enterprise), first admin's email, name and optional password. The new tenant gets the system roles and default policies.

---

## 5. Agent reference

All 25 agents, grouped by department. "Typical input" shows a working example for the demo tenant (paste it into the Playground). "Approval" describes what happens to the agent's proposed actions under the default tenant policy (standard mode, $1,000 threshold, external communications require approval). Any action can additionally need approval if the tenant uses strict mode, if an amount exceeds the threshold, or if the person running the agent lacks the tool's permission.

### Sales & Revenue

| Agent | Key | What it does | Typical input | Tools it may use | Risk | Actions and approval |
|---|---|---|---|---|---|---|
| Lead Qualification Agent | `lead_qualification` | Cleans up an inbound lead, checks the CRM for duplicates, scores it 0–100 on budget, authority, timeline, company size, stated need and industry fit (ignores protected attributes such as age or gender), assigns tier A–D, routes qualified leads to a sales team, and lists missing information with follow-up questions. | `{"lead": {"name": "Ana Silva", "email": "ana@globex.test", "company": "Globex", "title": "VP Operations", "industry": "logistics", "company_size": 900, "budget": 80000, "timeline": "this quarter", "message": "We need to automate warehouse exception handling."}, "source": "webform"}` | `crm.find_lead`, `crm.get_sales_teams`, `crm.upsert_lead`, `crm.update_lead`, `crm.log_activity` | Low | Creates or updates the CRM lead and logs the scoring rationale. Low risk: runs automatically. |
| AI Sales Development Agent | `sales_development` | Researches a prospect from the CRM and knowledge base, checks consent and contact limits, drafts personalised outreach using only verified facts, and plans follow-ups. | `{"lead_id": "L-1003"}` (or a `lead` object; optional `goal`, `sender_name`) | `crm.get_lead`, `crm.get_activity`, `crm.check_consent`, `platform.search_knowledge`, `email.send`, `crm.log_activity`, `crm.schedule_followup` | High | The outreach email **always needs approval** (requires `email:send`). CRM note and follow-up reminder run automatically. |
| Sales Call Intelligence Agent | `sales_call_intelligence` | Extracts requirements, objections, decisions, buying signals and next steps from a call transcript, each linked to transcript lines. Refuses to process unless recording consent is confirmed. | `{"transcript": "Rep: ...\nCustomer: ...", "consent_confirmed": true, "lead_id": "L-1001", "our_speakers": ["Dana Lee"]}` | `crm.log_activity` | Low | Logs the call summary on the lead automatically. Without consent: status Needs input. |
| Proposal Generator Agent | `proposal_generator` | Builds a proposal or quote from the approved price list and template with exact arithmetic, flags discounts above limits, non-standard terms and missing information. | `{"customer_name": "Finova", "contact_email": "mei.chen@finova.test", "lead_id": "L-1003", "lines": [{"sku": "SKU-002", "quantity": 25, "discount_pct": 10}, {"sku": "SKU-003", "quantity": 1}]}` (optional `payment_terms` "Net 30", `currency` "USD", `valid_days` 30, `special_terms`) | `crm.get_price_list`, `crm.get_proposal_templates`, `email.send`, `crm.log_activity` | High | Sending the proposal **always needs approval** (critical risk when it includes non-standard terms or discounts). CRM note runs automatically. |

### Customer Support

| Agent | Key | What it does | Typical input | Tools it may use | Risk | Actions and approval |
|---|---|---|---|---|---|---|
| Customer Support Agent | `customer_support` | Answers a customer question from the knowledge base and verified account, order and shipment data, with citations. Escalates anything unsupported, low-confidence or sensitive, and flags complaints. | `{"message": "How long does standard shipping take?", "customer_id": "C-2001", "channel": "email"}` (optional `order_id`) | `platform.search_knowledge`, `crm.get_customer`, `commerce.get_order`, `commerce.get_shipment`, `commerce.delivery_policy`, `helpdesk.create_ticket` | Medium | Escalation ticket runs automatically. Status Escalated when handed to a person. It does not send the answer anywhere itself. |
| Complaint Resolution Agent | `complaint_resolution` | Categorises a complaint, sets urgency and SLA by fixed rules, reviews case history and policy, opens a ticket and recommends a policy-bounded resolution. | `{"message": "My order ORD-5002 is two weeks late and nobody answers.", "customer_id": "C-2003", "order_id": "ORD-5002", "channel": "email"}` | `crm.get_customer`, `helpdesk.case_history`, `helpdesk.get_policies`, `commerce.get_order`, `helpdesk.create_ticket`, `helpdesk.update_ticket` | Medium | The complaint ticket runs automatically. Any refund, credit or compensation is only a recommendation (a compensation-review ticket) that **always needs approval**. |
| WhatsApp Business Agent | `whatsapp_business` | Handles an inbound WhatsApp message: records it, checks opt-in and the 24-hour service window, handles opt-outs, answers FAQ, product and order questions, captures sales leads and escalates to a person. | `{"phone": "+15550100123", "message": "Hi, where is my order ORD-5002?", "customer_id": "C-2001", "profile_name": "Jordan"}` | `platform.record_inbound_message`, `whatsapp.check_opt_in`, `whatsapp.list_templates`, `whatsapp.get_conversation`, `platform.search_knowledge`, `commerce.search_products`, `commerce.get_order`, `commerce.get_shipment`, `whatsapp.send_text`, `whatsapp.send_template`, `crm.upsert_lead`, `crm.update_consent`, `helpdesk.create_ticket` | Medium | Replies (free text inside the 24-hour window, approved templates outside it) **need approval** unless a tenant auto-approve rule matches. Recording the message, opt-outs, lead capture and tickets run automatically. |
| Customer Retention Agent | `customer_retention` | Finds inactive or at-risk customers with transparent signals (inactivity, falling orders or usage, complaints, NPS), respects consent, recommends interventions and drafts (never sends) a win-back campaign. | `{"inactivity_days": 60, "risk_threshold": 40}` (or `customer_ids`, `segment`, `max_customers`) | `crm.list_customers`, `crm.get_customer`, `crm.check_consent`, `helpdesk.case_history`, `platform.create_task` | Medium | Creates account-manager follow-up tasks automatically. Campaigns are never sent automatically. |

### E-Commerce

| Agent | Key | What it does | Typical input | Tools it may use | Risk | Actions and approval |
|---|---|---|---|---|---|---|
| AI Shopping Assistant | `shopping_assistant` | Finds and compares products from the verified catalogue against needs and budget, with live price, stock and delivery policy, and can prepare a draft cart. Never checks out. | `{"query": "wireless headphones with long battery life", "budget_max": 250}` (optional `category`, `must_have`, `customer_id`, `add_to_cart` [{"product_id": "P-100", "quantity": 1}]) | `commerce.search_products`, `commerce.get_product`, `commerce.price_and_stock`, `commerce.delivery_policy`, `commerce.create_cart` | Low | Draft cart (no purchase) is created automatically. |
| Order Management Agent | `order_management` | Monitors orders and shipments for delays, exceptions, failed payments and cancellations using verified tracking data, drafts factual customer updates, opens tickets and lists affected customers. | `{"scan_all": true}` or `{"order_ids": ["ORD-5002", "ORD-5005"]}` (optional `unfulfilled_after_days` 3, `notify_customers` true) | `commerce.list_orders`, `commerce.get_order`, `commerce.get_shipment`, `crm.get_customer`, `email.send`, `helpdesk.create_ticket`, `commerce.update_order` | Medium | Customer update emails and order status changes **always need approval**. Exception tickets run automatically. |
| Inventory Forecasting Agent | `inventory_forecasting` | Forecasts demand per SKU with stated uncertainty, computes reorder points and quantities, and proposes purchase orders grouped by supplier. | `{"horizon_days": 30}` (optional `skus` ["SKU-AUR-HP"], `service_level` 0.95, `propose_purchase_orders` true) | `commerce.list_inventory`, `commerce.get_inventory`, `commerce.sales_history`, `commerce.supplier_lead_time`, `commerce.create_purchase_order` | High | Purchase orders are critical-risk and **always need approval** (requires `procurement:commit`). |
| Product Listing Agent | `product_listing` | Writes product title, description, specs, FAQ and SEO text strictly from verified attributes, and checks it against brand rules and prohibited claims. | `{"product_id": "P-100"}` (optional `channel` "webstore", `include_faq`, `publish`) | `commerce.get_product`, `commerce.brand_guidelines`, `commerce.update_listing` | Medium | Publishing the listing **always needs approval**. |

### Operations & Management

| Agent | Key | What it does | Typical input | Tools it may use | Risk | Actions and approval |
|---|---|---|---|---|---|---|
| Workflow Coordinator Agent | `workflow_coordinator` | Reviews tasks, dependencies and blockers, flags overdue or at-risk work by fixed deadline rules, posts a digest and proposes escalations. | `{"scope": "overdue"}` (`all`, `overdue` or `recent`; optional `at_risk_hours` 24, `notify_channel` "#ops") | `platform.list_tasks`, `chat.post_message`, `platform.escalate_task`, `platform.create_task` | Low | Task escalations **always need approval**. The team-chat digest runs automatically. |
| Meeting-to-Execution Agent | `meeting_to_execution` | Turns a meeting transcript into decisions, action items (owners resolved through the employee directory, deadlines such as "by Friday" turned into dates) and open questions, all linked to transcript evidence. | `{"meeting_id": "MTG-1"}` or `{"transcript": "...", "title": "...", "attendees": ["..."]}` (optional `create_tasks` true) | `workspace.get_transcript`, `workspace.directory_lookup`, `platform.create_task` | Low | Creates tasks automatically; unclear owners or details are labelled `needs-clarification`. |
| SOP Compliance Agent | `sop_compliance` | Audits operational records against approved SOPs, cites the SOP section for every finding, separates confirmed violations from potential concerns, and flags outdated SOPs. | `{"process": "customer_onboarding"}` (or `refund`; optional `record_ids`, `sop_review_days` 365) | `metrics.list_sops`, `metrics.operational_records`, `platform.create_task`, `platform.open_incident` | Low | Remediation tasks and an incident for significant violations are created automatically. |
| Business Intelligence Agent | `business_intelligence` | Computes KPIs and period comparisons exactly from metric data, explains changes with evidence, separates correlation from causation and warns about data quality. | `{"period_days": 14}` (optional `metrics` ["orders_total", "revenue_usd"], `question`) | `metrics.list`, `metrics.query` | Low | Read-only: proposes no actions. |

### Finance & Administration

| Agent | Key | What it does | Typical input | Tools it may use | Risk | Actions and approval |
|---|---|---|---|---|---|---|
| Invoice Processing Agent | `invoice_processing` | Extracts invoice fields, re-checks the arithmetic, matches against the purchase order and goods receipts (3-way match), detects duplicates and stages a payable for approval. Never releases payment. | `{"document_text": "<invoice text, for example docs\\samples\\invoice_ok.txt>"}` (optional `document_id`, `vendor_hint`, `tolerance_pct` 2) | `accounting.find_invoices`, `accounting.get_purchase_order`, `accounting.list_receipts`, `accounting.create_payable`, `platform.create_task` | High | Staging the payable **always needs approval** (requires `accounting:write`; finance approvers can decide it). An AP review task for discrepancies runs automatically. |
| Expense Audit Agent | `expense_audit` | Checks expense claims against the expense policy (category limits, receipts, duplicates, prohibited categories, late submission) with evidence-backed, non-accusatory flags. | `{"status": "submitted"}` or `{"claim_ids": ["EXP-1", "EXP-2"]}` (optional `max_claims`) | `accounting.list_expense_claims`, `accounting.get_expense_claim`, `accounting.expense_policy`, `accounting.flag_expense`, `platform.create_task` | Medium | Flags on claims and a reviewer task are created automatically. |
| Payment Follow-up Agent | `payment_followup` | Drafts payment reminders (friendly, firm, final) from approved templates based on the invoice's real status, skips disputed invoices and respects consent and contact limits. Never claims payment was received and never moves money. | `{}` (all overdue) or `{"invoice_ids": ["INV-9002", "INV-9003"]}` (optional `min_days_between_contacts` 5, `max_invoices`) | `accounting.list_invoices`, `accounting.get_invoice`, `accounting.followup_history`, `email.list_templates`, `crm.check_consent`, `email.send`, `accounting.record_followup`, `platform.create_task` | High | Every reminder email **always needs approval** (requires `email:send`). Follow-up history and a collections-review task (final stage) run automatically. |
| Procurement Agent | `procurement` | Normalises and compares supplier quotes on approved criteria (price, lead time, quality, terms), explains trade-offs, flags policy conflicts (for example unapproved suppliers, missing fields) and recommends a supplier. | `{"rfq_id": "RFQ-42"}` (optional `weights`, `fx_rates` {"EUR": 1.08}) | `procurement.get_rfq`, `procurement.list_quotes`, `procurement.get_supplier`, `procurement.get_policy`, `procurement.create_purchase_order`, `platform.create_task` | Critical | The purchase order is critical-risk and **always needs approval** (requires `procurement:commit`). A buyer decision task runs automatically. |

### Technology & Product

| Agent | Key | What it does | Typical input | Tools it may use | Risk | Actions and approval |
|---|---|---|---|---|---|---|
| QA Testing Agent | `qa_testing` | Turns requirements or bug reports into structured test cases and Python test skeletons. Execution is only proposed against authorised test environments, never production. | `{"title": "Coupon checkout", "requirements": "Applying coupon SAVE10 must reduce the order total by 10%.", "target_environment": "staging", "request_execution": true}` (optional `kind` "requirement" or "bug_report", `api_base_path`) | `monitoring.test_environments`, `issues.create`, `platform.create_task` | Medium | A test-execution request (filed as an issue) **always needs approval**. A test-plan review task runs automatically. |
| Bug Triage Agent | `bug_triage` | Normalises a bug report, finds likely duplicates among existing issues, applies documented severity rules, drafts reproduction questions and defers uncertain cases to people. | `{"report": {"title": "Checkout fails with coupon", "description": "Applying SAVE10 then paying gives a 500 error.", "affected_users": 120}}` (optional `project` "ENG", `duplicate_threshold` 0.72) | `issues.search`, `issues.get`, `issues.create`, `issues.comment` | Low | A comment on a likely duplicate runs automatically. Filing the new issue **needs approval**. Known issue: the agent's approval rule is described as "critical severity or probable duplicate", but it currently applies to every new issue. |
| Product Research Agent | `product_research` | Groups customer feedback, reviews, tickets and feature requests into themes with honest counts and evidence, and keeps hypotheses and experiment ideas separate from evidence. | `{"since_days": 90, "min_theme_size": 2}` (optional `sources` ["review", "ticket", "feature_request"], `max_items`) | `feedback.list`, `platform.create_task` | Low | A research digest task is created automatically. |
| Release Monitoring Agent | `release_monitoring` | Compares telemetry after a deployment with thresholds and the pre-release baseline, summarises likely causes from logs, raises alerts and suggests mitigations. Never touches infrastructure. | `{"service": "checkout-api", "deployment_id": "DEP-301"}` (optional `window_minutes` 60) | `monitoring.get_deployments`, `monitoring.get_metrics`, `monitoring.get_logs`, `monitoring.create_alert`, `chat.post_message` | Medium | The incident alert and on-call chat message run automatically. A rollback recommendation **always needs approval** (the agent cannot roll back; an engineer must). |
| Finance-Aware Business Analyst Agent | `finance_analyst` | Computes cost per successful workflow and estimated vs realized value from cost, revenue and usage data, and flags cost anomalies and budget breaches. | `{"months": 3}` (optional `loaded_hourly_cost_usd`, `realization_rate`) | `accounting.cost_ledger`, `accounting.revenue`, `accounting.budgets`, `platform.workflow_usage`, `platform.open_incident` | Low | Read-only analysis; opens a finance incident automatically when it finds anomalies or breaches. |

---

## 6. Tool reference

All 98 built-in tools, grouped by provider. Columns:
- **Type**: Read-only (looks things up) or Side effect (changes something).
- **Permission**: what the person running the agent (or reviewing the approval) needs.
- **Approval (default policy)**:
  - **Never**: read-only.
  - **Always**: always waits for a person (critical-risk tools, external customer messages, high-risk tools; only a narrow tenant auto-approve rule can exempt external messages and high-risk tools).
  - **Auto\***: runs automatically unless the tenant is in strict mode, an amount in the action exceeds the threshold, the person running the agent lacks the permission, or the proposing agent has an approval rule for it (noted where it applies).
- **Copilot**: Yes if the Copilot can call the tool directly (read-only tools on its allow-list). Every other tool is still reachable through agents.

### CRM (`crm`)

| Tool | What it does | Type | Risk | Permission | Approval | Copilot |
|---|---|---|---|---|---|---|
| `crm.find_lead` | Look up CRM leads by email, phone or company | Read-only | Low | `crm:read` | Never | Yes |
| `crm.list_leads` | List CRM leads | Read-only | Low | `crm:read` | Never | Yes |
| `crm.get_lead` | Fetch one CRM lead | Read-only | Low | `crm:read` | Never | Yes |
| `crm.get_activity` | Activity history for a lead | Read-only | Low | `crm:read` | Never | – |
| `crm.list_customers` | Customers with usage and engagement data | Read-only | Low | `crm:read` | Never | Yes |
| `crm.get_customer` | Fetch a customer account | Read-only | Low | `crm:read` | Never | Yes |
| `crm.check_consent` | Marketing consent / unsubscribe status | Read-only | Low | `crm:read` | Never | – |
| `crm.get_sales_teams` | Sales teams and routing rules | Read-only | Low | `crm:read` | Never | – |
| `crm.get_price_list` | Approved pricing catalogue with discount limits | Read-only | Low | `crm:read` | Never | – |
| `crm.get_proposal_templates` | Approved proposal templates and standard terms | Read-only | Low | `crm:read` | Never | – |
| `crm.update_consent` | Record an opt-out or consent change | Side effect | Low | `crm:write` | Auto\* | – |
| `crm.upsert_lead` | Create or update a CRM lead | Side effect | Low | `crm:write` | Auto\* | – |
| `crm.update_lead` | Update fields on a CRM lead | Side effect | Low | `crm:write` | Auto\* | – |
| `crm.log_activity` | Record an activity note on a lead | Side effect | Low | `crm:write` | Auto\* | – |
| `crm.schedule_followup` | Schedule a follow-up reminder | Side effect | Low | `crm:write` | Auto\* | – |

### Email (`email`)

| Tool | What it does | Type | Risk | Permission | Approval | Copilot |
|---|---|---|---|---|---|---|
| `email.list_templates` | List approved email templates | Read-only | Low | `email:read` | Never | – |
| `email.list_outbox` | List sent messages (sandbox outbox) | Read-only | Low | `email:read` | Never | – |
| `email.send` | Send an external email | Side effect | High | `email:send` | Always | – |

### Team chat (`chat`)

| Tool | What it does | Type | Risk | Permission | Approval | Copilot |
|---|---|---|---|---|---|---|
| `chat.list_channels` | List team chat channels | Read-only | Low | `chat:read` | Never | – |
| `chat.post_message` | Post an internal chat notification | Side effect | Low | `chat:write` | Auto\* | – |

### Issue tracker (`issues`)

| Tool | What it does | Type | Risk | Permission | Approval | Copilot |
|---|---|---|---|---|---|---|
| `issues.search` | Search the issue tracker | Read-only | Low | `issues:read` | Never | Yes |
| `issues.get` | Fetch one issue | Read-only | Low | `issues:read` | Never | – |
| `issues.list_projects` | List issue tracker projects | Read-only | Low | `issues:read` | Never | – |
| `issues.create` | Create an issue or task in the tracker | Side effect | Medium | `issues:write` | Auto\* (Bug Triage and QA Testing: approval) | – |
| `issues.update` | Update an issue | Side effect | Low | `issues:write` | Auto\* | – |
| `issues.comment` | Add a comment to an issue | Side effect | Low | `issues:write` | Auto\* | – |

### Helpdesk (`helpdesk`)

| Tool | What it does | Type | Risk | Permission | Approval | Copilot |
|---|---|---|---|---|---|---|
| `helpdesk.list_tickets` | List support tickets | Read-only | Low | `helpdesk:read` | Never | Yes |
| `helpdesk.get_ticket` | Fetch a support ticket | Read-only | Low | `helpdesk:read` | Never | – |
| `helpdesk.case_history` | A customer's case history | Read-only | Low | `helpdesk:read` | Never | – |
| `helpdesk.get_policies` | Refund, compensation and escalation policies | Read-only | Low | `helpdesk:read` | Never | – |
| `helpdesk.create_ticket` | Create a support ticket | Side effect | Low | `helpdesk:write` | Auto\* (compensation recommendations from Complaint Resolution: approval) | – |
| `helpdesk.update_ticket` | Update a support ticket | Side effect | Low | `helpdesk:write` | Auto\* | – |

### Commerce (`commerce`)

| Tool | What it does | Type | Risk | Permission | Approval | Copilot |
|---|---|---|---|---|---|---|
| `commerce.search_products` | Search the verified product catalogue | Read-only | Low | `commerce:read` | Never | Yes |
| `commerce.get_product` | Product details | Read-only | Low | `commerce:read` | Never | – |
| `commerce.price_and_stock` | Current price and stock status | Read-only | Low | `commerce:read` | Never | Yes |
| `commerce.delivery_policy` | Shipping and returns policy | Read-only | Low | `commerce:read` | Never | – |
| `commerce.list_orders` | List orders | Read-only | Low | `commerce:read` | Never | Yes |
| `commerce.get_order` | Fetch an order | Read-only | Low | `commerce:read` | Never | Yes |
| `commerce.get_shipment` | Verified shipment and tracking for an order | Read-only | Low | `commerce:read` | Never | Yes |
| `commerce.get_inventory` | Inventory level for a SKU | Read-only | Low | `commerce:read` | Never | – |
| `commerce.list_inventory` | All inventory records | Read-only | Low | `commerce:read` | Never | Yes |
| `commerce.sales_history` | Daily unit sales for a SKU | Read-only | Low | `commerce:read` | Never | – |
| `commerce.supplier_lead_time` | Lead time for a SKU | Read-only | Low | `commerce:read` | Never | – |
| `commerce.brand_guidelines` | Brand voice and prohibited claims | Read-only | Low | `commerce:read` | Never | – |
| `commerce.create_cart` | Create a draft cart (no purchase) | Side effect | Low | `commerce:write` | Auto\* | – |
| `commerce.update_order` | Update order fields or notes | Side effect | Medium | `commerce:write` | Auto\* (Order Management: approval) | – |
| `commerce.update_listing` | Publish or update a product listing | Side effect | Medium | `commerce:write` | Auto\* (Product Listing: approval) | – |
| `commerce.create_purchase_order` | Issue a replenishment purchase order | Side effect | Critical | `procurement:commit` | Always | – |

### Accounting (`accounting`)

| Tool | What it does | Type | Risk | Permission | Approval | Copilot |
|---|---|---|---|---|---|---|
| `accounting.get_invoice` | Fetch an invoice | Read-only | Low | `accounting:read` | Never | Yes |
| `accounting.list_invoices` | List invoices (optionally overdue only) | Read-only | Low | `accounting:read` | Never | Yes |
| `accounting.find_invoices` | Find invoices by vendor, number or amount (duplicate detection) | Read-only | Low | `accounting:read` | Never | – |
| `accounting.get_purchase_order` | Fetch a purchase order | Read-only | Low | `accounting:read` | Never | – |
| `accounting.list_purchase_orders` | List purchase orders | Read-only | Low | `accounting:read` | Never | – |
| `accounting.list_receipts` | Goods receipts for a PO | Read-only | Low | `accounting:read` | Never | – |
| `accounting.list_expense_claims` | Expense claims | Read-only | Low | `accounting:read` | Never | Yes |
| `accounting.get_expense_claim` | One expense claim | Read-only | Low | `accounting:read` | Never | – |
| `accounting.expense_policy` | Company expense policy | Read-only | Low | `accounting:read` | Never | – |
| `accounting.followup_history` | Payment follow-up history | Read-only | Low | `accounting:read` | Never | – |
| `accounting.cost_ledger` | Operational cost ledger entries | Read-only | Low | `accounting:read` | Never | – |
| `accounting.revenue` | Revenue entries | Read-only | Low | `accounting:read` | Never | – |
| `accounting.budgets` | Budget thresholds by cost centre | Read-only | Low | `accounting:read` | Never | – |
| `accounting.create_payable` | Create an AP record pending human approval (never releases payment) | Side effect | High | `accounting:write` | Always | – |
| `accounting.flag_expense` | Mark an expense claim for reviewer attention | Side effect | Medium | `accounting:write` | Auto\* | – |
| `accounting.record_followup` | Record a payment follow-up in history | Side effect | Low | `accounting:write` | Auto\* | – |

### WhatsApp Business (`whatsapp`)

| Tool | What it does | Type | Risk | Permission | Approval | Copilot |
|---|---|---|---|---|---|---|
| `whatsapp.check_opt_in` | Consent and 24-hour window status | Read-only | Low | `whatsapp:read` | Never | – |
| `whatsapp.list_templates` | Approved message templates | Read-only | Low | `whatsapp:read` | Never | – |
| `whatsapp.get_conversation` | Recent conversation with a number | Read-only | Low | `whatsapp:read` | Never | – |
| `whatsapp.send_template` | Send an approved template message | Side effect | High | `whatsapp:send` | Always | – |
| `whatsapp.send_text` | Send a free-form reply within the 24-hour service window | Side effect | Medium | `whatsapp:send` | Always (unless an auto-approve rule matches or external-communication approval is switched off) | – |

### Google Workspace (`workspace`)

| Tool | What it does | Type | Risk | Permission | Approval | Copilot |
|---|---|---|---|---|---|---|
| `workspace.list_employees` | Authorised employee directory | Read-only | Low | `workspace:read` | Never | Yes |
| `workspace.directory_lookup` | Resolve a person reference via the directory | Read-only | Low | `workspace:read` | Never | Yes |
| `workspace.get_transcript` | Fetch an authorised meeting transcript | Read-only | Low | `workspace:read` | Never | – |
| `workspace.create_calendar_event` | Create a calendar event | Side effect | Low | `workspace:write` | Auto\* | – |

### Monitoring (`monitoring`)

| Tool | What it does | Type | Risk | Permission | Approval | Copilot |
|---|---|---|---|---|---|---|
| `monitoring.get_deployments` | Recent deployments | Read-only | Low | `monitoring:read` | Never | Yes |
| `monitoring.get_metrics` | Error rate and latency telemetry | Read-only | Low | `monitoring:read` | Never | Yes |
| `monitoring.get_logs` | Recent log entries | Read-only | Low | `monitoring:read` | Never | – |
| `monitoring.test_environments` | Authorised test environments | Read-only | Low | `monitoring:read` | Never | – |
| `monitoring.create_alert` | Open an incident alert | Side effect | Medium | `monitoring:write` | Auto\* (rollback recommendations from Release Monitoring: approval) | – |

### Procurement (`procurement`)

| Tool | What it does | Type | Risk | Permission | Approval | Copilot |
|---|---|---|---|---|---|---|
| `procurement.get_rfq` | Fetch a request for quotation | Read-only | Low | `procurement:read` | Never | – |
| `procurement.list_quotes` | Supplier quotations for an RFQ | Read-only | Low | `procurement:read` | Never | Yes |
| `procurement.get_supplier` | Supplier profile and approval status | Read-only | Low | `procurement:read` | Never | – |
| `procurement.list_suppliers` | All suppliers | Read-only | Low | `procurement:read` | Never | – |
| `procurement.get_policy` | Procurement policy | Read-only | Low | `procurement:read` | Never | – |
| `procurement.create_purchase_order` | Commit to a supplier purchase order | Side effect | Critical | `procurement:commit` | Always | – |

### Feedback sources (`feedback`) and Metrics warehouse (`metrics`)

| Tool | What it does | Type | Risk | Permission | Approval | Copilot |
|---|---|---|---|---|---|---|
| `feedback.list` | Customer feedback, reviews, tickets, feature requests | Read-only | Low | `feedback:read` | Never | Yes |
| `metrics.list` | Available business metrics | Read-only | Low | `metrics:read` | Never | Yes |
| `metrics.query` | Time series for a metric | Read-only | Low | `metrics:read` | Never | Yes |
| `metrics.list_sops` | Approved standard operating procedures | Read-only | Low | `metrics:read` | Never | – |
| `metrics.operational_records` | Records of executed process steps | Read-only | Low | `metrics:read` | Never | – |

### OpsPilot platform (`platform`, internal, no external system)

| Tool | What it does | Type | Risk | Permission | Approval | Copilot |
|---|---|---|---|---|---|---|
| `platform.list_tasks` | List OpsPilot tasks | Read-only | Low | `tasks:read` | Never | Yes |
| `platform.workflow_usage` | Workflow run counts, AI cost and estimated time saved by workflow | Read-only | Low | `tasks:read` | Never | Yes |
| `platform.search_knowledge` | Retrieve passages from the tenant's documents | Read-only | Low | `documents:read` | Never | Yes |
| `platform.list_documents` | List documents in a collection | Read-only | Low | `documents:read` | Never | – |
| `platform.create_task` | Create a task on the Tasks board | Side effect | Low | `tasks:write` | Auto\* | – |
| `platform.escalate_task` | Raise a task's escalation level and notify its owner | Side effect | Medium | `tasks:write` | Auto\* (Workflow Coordinator: approval) | – |
| `platform.record_inbound_message` | Save an inbound channel message (opens the WhatsApp 24-hour window) | Side effect | Low | `whatsapp:read` | Auto\* | – |
| `platform.open_incident` | Record an incident for operators | Side effect | Low | `incidents:write` | Auto\* | – |
| `platform.start_workflow` | Start another workflow (limited nesting depth) | Side effect | Medium | `workflows:write` | Auto\* | – |

### Other tools

- **Custom HTTP tools** (`custom.<name>`): your tenant's own tools (see [Integrations → Custom tools](#custom-tools-tab)). Permission `tools:custom`. Read-only ones run directly; ones marked as having side effects always need approval. Only the Copilot calls them.
- **Copilot platform helpers**: `ops__list_agents` (list the 25 agents; everyone), `ops__list_pending_approvals` (`approvals:read`), `ops__get_workflow_run` and `ops__list_workflows` (`workflows:read`), `ops__start_workflow` (`workflows:write`).
- **MCP tools** for external AI clients: `list_agents` and `describe_agent` (`agents:read`), `run_agent` (`agents:run`), `start_workflow` (`workflows:write`), `get_workflow_run` (`workflows:read`), `list_pending_approvals` (`approvals:read`), `search_knowledge` (`documents:read`). None of them can approve anything.

---

## 7. Workflow reference

There are 10 built-in workflow templates plus automatically created single-agent wrappers.

General rules:
- **Trigger**: the business event types that start the workflow automatically when another system posts them to OpsPilot (set up by a technical admin; see the appendix). You can always start any template manually with **Start workflow**.
- **Approval gate**: if any action proposed earlier in the run is waiting for approval, the run pauses here with status **Waiting approval**. If nothing is pending, it passes straight through.
- **Timeout**: the run's deadline, counted from when it started. Time spent waiting at an approval gate does **not** count: when the run resumes, its deadline is extended by the time it waited, so a late approval still lets the run complete. See the [timed out FAQ](#a-workflow-shows-timed-out).
- **Example input**: the **Start workflow** dialog pre-fills each built-in workflow with the working example shown in the last column (demo data). Input that does not fit the first agent is rejected before a run is created.

| # | Name | Key | Trigger | Timeout | Steps, in order | Waits for approval | Produces | Example input |
|---|---|---|---|---|---|---|---|---|
| 1 | New lead → qualified CRM record → outreach draft | `lead_to_crm` | Events `lead.created`, `form.submitted` | 600 s | 1. **qualify**: Lead Qualification (if it fails, the run ends). 2. **is_qualified?** decision: qualified → step 3; not qualified → end. 3. **outreach**: AI Sales Development. 4. **gate**. 5. end. | At the gate, for the outreach email (always). | CRM lead and activity notes, follow-up reminder, outreach email after approval. | `{"lead": {"name": "Ana Silva", "email": "ana@globex.test", "company": "Globex", "title": "VP Operations", "industry": "logistics", "company_size": 900, "budget": 80000, "timeline": "this quarter", "message": "We need to automate warehouse exception handling."}}` (optional `source`) |
| 2 | Meeting transcript → tasks → coordinator | `meeting_to_tasks` | Event `meeting.transcript_ready` | 600 s | 1. **extract**: Meeting-to-Execution (if it needs input, the run ends). 2. **coordinate**: Workflow Coordinator (scope "recent"). 3. **gate**. 4. end. | At the gate, if the coordinator proposed escalations. | Decisions, action-item tasks with owners and deadlines, a chat digest, escalations after approval. | Pre-filled: `{"title": "Q4 launch planning", "transcript": "Maya: We decided to move the launch to November 12.\nDana: Dana will send the updated pricing sheet to the sales team by Friday.\n..."}`. Also accepted: `{"meeting_id": "MTG-1"}` (optional `attendees`). |
| 3 | Customer question → verified, cited answer | `customer_query` | Event `support.message_received` | 300 s | 1. **answer**: Customer Support. 2. **is_complaint?** decision: complaint → step 3; otherwise end. 3. **complaint**: Complaint Resolution. 4. end. | No gate: the run finishes. Any compensation recommendation still waits in Approvals. | A cited answer (in the run output), escalation or complaint tickets. | `{"message": "Where is my order ORD-5002? It's late.", "customer_id": "C-2003", "order_id": "ORD-5002", "channel": "email"}` |
| 4 | WhatsApp message → intent → compliant reply | `whatsapp_inbound` | Event `whatsapp.message_received` (from the signed WhatsApp webhook) | 120 s | 1. **handle**: WhatsApp Business. 2. **gate**. 3. end. | At the gate, for the reply (unless a narrow auto-approve rule applies). | Recorded message, reply after approval, lead, opt-out or ticket as needed. | `{"phone": "+15550100123", "message": "Where is my order ORD-5001?", "profile_name": "Jordan"}` (optional `customer_id`, `message_id`) |
| 5 | Invoice → 3-way match → review request | `invoice_to_review` | Event `invoice.received` | 300 s | 1. **process**: Invoice Processing. 2. **gate**. 3. end. | At the gate, for staging the payable (always). | Extracted and validated invoice, match result, a staged payable after approval (never a payment), an AP review task if there are discrepancies. | `{"document_text": "Northwind Components\nInvoice No: NW-2026-201\n...PO Number: PO-7001\n...Total Due: 4,800.00"}` (the full sample invoice) |
| 6 | Overdue tasks → approved escalation | `overdue_escalation` | Declared as "schedule: hourly" (see note) | 300 s | 1. **coordinate**: Workflow Coordinator (scope "overdue"). 2. **gate**. 3. end. | At the gate, for escalations. | Chat digest of overdue work; escalated tasks after approval. | `{}` |
| 7 | KPI data → evidence-backed report | `kpi_report` | Declared as "schedule: weekly" (see note) | 600 s | 1. **fanout**: runs two branches at the same time: **bi** (Business Intelligence) and **finance** (Finance-Aware Business Analyst). 2. **gate**. 3. end. | Normally nothing to approve (both agents are read-only apart from incidents). | KPI report and finance analysis in the run output; finance incident on anomalies. | `{"period_days": 14, "months": 3}` (optional `metrics`, `question`) |
| 8 | Order exception → customer update → retention check | `order_exception` | Events `order.updated`, `shipment.delayed` | 300 s | 1. **orders**: Order Management. 2. **gate**. 3. **retention**: Customer Retention, for the customers affected (if none were identified, it uses its default scan). 4. end. | At the gate (in the middle), for customer update emails and order status changes. Retention runs only after they are decided. | Exception tickets, approved customer updates, retention follow-up tasks. | `{"scan_all": true}` (or `{"order_ids": ["ORD-5002"]}`) |
| 9 | Deployment → telemetry check → triage | `release_watch` | Event `deployment.completed` | 300 s | 1. **monitor**: Release Monitoring. 2. **anomaly?** decision: anomaly → step 3; otherwise end. 3. **triage**: Bug Triage (report built from the monitor's findings). 4. **gate**. 5. end. | At the gate, for the rollback recommendation and the new bug issue. | Incident alert, on-call chat message, triaged issue after approval. | `{"service": "checkout-api", "deployment_id": "DEP-301"}` |
| 10 | RFQ quotes → recommendation → approved PO | `quote_to_po` | Event `rfq.quotes_received` | 300 s | 1. **compare**: Procurement. 2. **gate**. 3. end. | At the gate, for the purchase order (always; critical risk). | Supplier comparison and recommendation, buyer task, purchase order after approval. | `{"rfq_id": "RFQ-42"}` |
| – | Run &lt;agent name&gt; (single-agent wrapper) | `single_agent__<agent_key>` | Created and used by the agent's Playground (its **Playground** button on the Definitions page opens it) | 300 s | 1. **run**: the agent. 2. **gate**. 3. end. | At the gate, for any action needing approval. | Whatever the agent produces. | The Playground's example input |

> **Note on schedules:** `overdue_escalation` and `kpi_report` are labelled with an hourly and a weekly schedule, but this version has no scheduler that starts workflows automatically. Start them manually (or ask a technical admin to start them from an external scheduler through the API).

Workflow administrators (`workflows:admin`, included in the admin role) can add tenant-specific workflow versions through the API; they appear on the Definitions page with scope "tenant".

---

## 8. Copilot guide

### What the Copilot can use

Everything runs with **your** permissions; you cannot reach anything through the Copilot that you could not reach yourself.

| Kind | Examples | Notes |
|---|---|---|
| Agents (up to 25) | `agent__inventory_forecasting` | Any enabled agent. Their actions go through the normal rules; consequential ones wait in Approvals. |
| Read-only tools (up to 27) | `commerce__get_order`, `metrics__query`, `platform__search_knowledge` | The tools marked "Copilot: Yes" in the [Tool reference](#6-tool-reference), limited to those you have permission for. |
| Custom tools | `custom__order_lookup` | Your tenant's enabled custom tools, if you have `tools:custom`. Side-effecting ones wait for approval. |
| Platform helpers | list agents, pending approvals, workflow templates, a workflow run's status, start a workflow | Depending on your permissions. |

Click **Browse tools** on an empty chat to see your exact list.

### Two modes

- **Live model (badge "Gemini" or "Claude" plus a model name).** The AI model reads your question, decides which tools to call (several in parallel when they are independent), reads the results, may call more tools, and writes the answer. It keeps the conversation's earlier turns as context, so follow-ups like "and the second one?" work. It is told to base every statement on tool results and to treat customer-written text in results as data, not instructions.
- **Offline planner (badge "Offline planner").** Used when no AI provider is configured. A fixed set of keyword rules picks up to 4 calls per message, and the answer lists each tool's result. It does not remember earlier messages. Keywords it recognises:

| If your message mentions… | It calls… |
|---|---|
| approval, approvals, pending | pending approvals list |
| a workflow run id (or "run"/"workflow" plus an id) | that run's status |
| order, orders, shipment, tracking, delayed, or an id like `ORD-5002` | the order (and then its shipment), or a full Order Management scan if no id |
| inventory, stock, reorder, replenish, forecast | Inventory Forecasting (30 days) |
| kpi, metrics, weekly report, business report | Business Intelligence (14 days) |
| overdue, blocked, task(s), deadline | Workflow Coordinator (overdue) |
| churn, at-risk, retention, inactive customers | Customer Retention |
| release, deploy, deployment, error rate, latency, incident | Release Monitoring (for a service named like `checkout-api`; defaults to checkout-api) |
| rfq, quote(s), supplier, purchase order, procure | Procurement (for an id like `RFQ-42`; defaults to RFQ-42) |
| expense(s), reimburse | Expense Audit |
| overdue invoices, payment reminder, dunning, unpaid, receivable | Payment Follow-up |
| feedback, reviews, themes, feature requests, voice of customer | Product Research |
| cost(s), budget, roi, spend, savings | Finance-Aware Business Analyst (3 months) |
| sop, compliance, onboarding process | SOP Compliance (customer onboarding) |
| lead(s), prospects, pipeline | lead lookup by the email in your message, or the lead list |
| bug(s), open issues | issue search |
| "customer asks…", "answer this customer" | Customer Support |
| policy, shipping, returns, warranty, refund, "how do/does/long" | knowledge base search |
| what can you do, which agents, help | the agent list |
| anything else | knowledge base search plus the agent list |

### Good questions

The suggested questions on an empty chat are a good start:
- What needs my approval right now?
- Check inventory and tell me what to reorder
- Which tasks are overdue, and who owns them?
- Where is order ORD-5002 and is anything wrong with it?
- Give me this fortnight's KPI report
- Which customers are at risk of churning?
- Did the latest checkout-api release cause problems?
- Compare the supplier quotes for RFQ-42

Tips:
- **Include ids** (order, invoice, lead, RFQ, run ids, email addresses). The Copilot then looks up exactly the right record.
- **Combine independent questions** ("check stock and list overdue tasks"): they run in parallel.
- **Say what you want done**, for example "draft reminders for overdue invoices". The agent will propose the emails; they then wait for approval.
- **Ask it to start a process**: "start the quote_to_po workflow for RFQ-42". It starts a durable workflow and gives you a link. If the input it builds does not fit the workflow, nothing is started and the step shows the validation error listing the bad fields; the Copilot can then correct the input.
- The Copilot reports what it found. If a tool failed or data was missing, it should say so; check the trace if something looks wrong.

### Reading the step trace

- Calls are grouped into **Step 1, Step 2…**. A step with several calls ("3 parallel calls") ran them at the same time.
- Each call shows an icon for its kind (agent, tool, custom tool, platform helper), a label, the technical tool name, a status (**Running** with a live timer, **Done**, **Error**, **Needs approval**) and its duration, plus a one-line summary.
- Links under a call: **Review approval** (opens the approval panel), **Agent run** (opens the agent's Runs tab), **Workflow run** (opens the run).
- **Input & output** expands the exact data sent to and returned by the call.
- When an answer is finished, the trace collapses to a one-line digest, for example "5 tool calls · 2 steps · 1 awaiting approval · 0 failed". Click it to expand. The latest answer's trace stays open.
- Under the answer: the mode, tool calls, model turns (live mode), elapsed time, tokens and cost (live mode), and a copy button.

### Approvals from chat

The Copilot never approves anything, and cannot. When an agent it called proposes something consequential, the step shows **Needs approval** and **Review approval**. Because the request came from your chat, separation of duties means **someone else** must approve it (for example an approver). Share the approval link or ask them to check the Approvals page.

### Follow-ups, retries and deleting chats

- Continue in the same chat for follow-ups. You can type while it is working, but sending waits until the current answer finishes ("The Copilot is still answering" otherwise).
- A failed answer shows the error and a **Retry** button.
- **New chat** starts fresh. Chats are titled with your first message.
- **Delete a chat:** hover it in the list, click the bin icon, confirm. The chat and its trace are removed; approvals, agent runs and audit records it created are kept.

### Limits

- Up to 8,000 characters per message.
- In live mode, at most 8 model steps and 24 tool calls per message (configurable by technical admins). Very large results are shortened before the model sees them.
- The offline planner makes at most 4 calls per message.
- Messages are refused when the tenant's monthly workflow-run quota is used up, and are rate-limited per tenant.
- The Copilot is for signed-in users only. External programs use the MCP endpoint instead.
- If the AI model is busy or out of quota, the Copilot switches to the next available model automatically. If no AI model is available at all, it answers with the built-in planner and adds a note saying so (see [Troubleshooting](#ai-provider-errors-quota-429-or-overloaded-503)).

---

## 9. Common tasks (recipes)

### Recipe 1: Qualify a lead and push it to CRM

*Roles: operator (starts), approver (approves the email).*

1. Sign in as `ops@acme-demo.test`.
2. Go to **Workflows** → **Start workflow**, choose **New lead → qualified CRM record → outreach draft**.
3. The input is pre-filled with the demo lead (Ana Silva, Globex). Keep it, or replace the values with a real lead in the same shape:
   ```json
   {"lead": {"name": "Ana Silva", "email": "ana@globex.test", "company": "Globex", "title": "VP Operations", "industry": "logistics", "company_size": 900, "budget": 80000, "timeline": "this quarter", "message": "We need to automate warehouse exception handling."}}
   ```
4. Click **Start run**. On the run page watch the graph: **qualify** → **is_qualified** (yes) → **outreach** → **gate**. The status becomes **Waiting approval**.
5. Open the **qualify** agent run to see the score, breakdown, tier, assigned team and the CRM write (outcome **Executed**, sandbox).
6. Sign out and sign in as `approver@acme-demo.test`. Open **Approvals**, click the `email.send` request, read the recipient, subject and body, add a note and click **Approve**.
7. The email is executed (in sandbox it lands in the sandbox outbox; nothing is sent) and the run continues to **Completed**, even if the approval came much later (waiting time does not count against the deadline). If the approval is rejected or expires, the run still completes, without the email.

Only want the scoring? Open **Agents → Lead Qualification Agent → Playground**; it is pre-filled with an example lead. No approval is needed.

### Recipe 2: Process an invoice

*Roles: operator (starts), finance approver (approves).*

1. **Workflows** → **Start workflow** → **Invoice → 3-way match → review request**.
2. The input is pre-filled with the sample invoice from `docs\samples\invoice_ok.txt` (Northwind Components, NW-2026-201, PO-7001).
3. For a real invoice, replace the text in `document_text`. In JSON, line breaks must be written as `\n`:
   ```json
   {"document_text": "Northwind Components\nInvoice No: NW-2026-201\nDate: 2026-10-01\nDue Date: 2026-10-31\nPO Number: PO-7001\nDriver units          400   12.00    4,800.00\nSubtotal: 4,800.00\nTax (0%): 0.00\nTotal Due: 4,800.00"}
   ```
   (Alternatively use the Invoice Processing Agent's Playground with the same input.)
4. Start the run and open the **process** agent run: check the extracted fields, the arithmetic check, the 3-way match against `PO-7001` and its goods receipt, the duplicate check and any discrepancies or warnings.
5. Sign in as `finance@acme-demo.test`, open **Approvals**, review the **Stage payable for approval** request (`accounting.create_payable`) and approve or reject it. Approving creates an accounts-payable record awaiting payment; OpsPilot never pays.

### Recipe 3: Approve a purchase order

*Roles: operator or admin (starts), finance approver or approver (decides).*

1. Start **RFQ quotes → recommendation → approved PO**; the input is pre-filled with `{"rfq_id": "RFQ-42"}` (or ask the Copilot "Compare the supplier quotes for RFQ-42").
2. Open the **compare** agent run: read the recommendation, the trade-offs and policy conflicts (in the demo, `SUP-4` QuickParts is not an approved supplier).
3. As `finance@acme-demo.test`, open **Approvals** → the critical-risk purchase-order request (requires `procurement:commit`).
4. Check the supplier, lines and total in the payload, and the evidence (the chosen quote and the procurement policy).
5. **Approve** (optionally with a note) or **Reject** (note required). The run then completes.

The same steps apply to purchase orders proposed by the Inventory Forecasting Agent.

### Recipe 4: Bulk-score leads from a CSV

*Role: operator or admin.*

1. **Agents → Lead Qualification Agent → Bulk run**.
2. Click **CSV** and paste your file with a header row, for example:
   ```
   name,email,company,title,industry,company_size,budget,timeline,message
   Ada Lovelace,ada@example.test,Analytical Engines,CTO,manufacturing,250,50000,this quarter,Automate supplier onboarding
   Grace Hopper,grace@example.test,Compilers Inc,Engineer,saas,40,8000,next year,Curious about AI
   ```
3. Check that **Wrap each row as** shows `lead`, and look at **Preview · first item**.
4. Turn **Execute actions** **off** for a dry run, name it, and click **Start bulk run**.
5. Watch the progress; filter the items, open inputs and agent runs to check scores.
6. When satisfied, run again with **Execute actions** **on** to write the leads to the CRM (low-risk, runs automatically).

If the run refuses to start, the message lists which rows do not match the agent's input (for example a missing required field).

### Recipe 5: Add a knowledge-base document and test retrieval

*Role: operator or admin.*

1. **Documents** → **Add text document**.
2. Name: `Gift card policy`. Collection: `kb`. Classification: Internal. Text:
   ```
   # Gift cards
   Gift cards never expire and can be used on all products except other gift cards.
   # Lost gift cards
   Lost gift cards can be replaced once with proof of purchase.
   ```
3. Click **Add document**. Check that **Scan** shows **Clean** and **Chunks** is at least 1.
4. In **Search the knowledge base**, type `gift card expire`. Your passage should appear with its section and reference.
5. Test it through an agent: **Agents → Customer Support Agent → Playground** with `{"message": "Do gift cards expire?", "customer_id": "C-2001"}`. The answer should cite `document:<id>#chunk:<n>` in its evidence. Or ask the Copilot "Do gift cards expire?".

If it is **Flagged**, the scanner found something unsafe (a credential, card number or instruction-like text); remove it and add the document again.

### Recipe 6: Connect Claude Desktop or Claude Code via MCP

*Role: admin (creates the key). For technical admins.*

1. **Admin → API keys → Create key**. Name it (for example "Claude Desktop – Avery"), set an expiry, and pick scopes. A useful set: `agents:read`, `agents:run`, `workflows:read`, `workflows:write`, `approvals:read`, `documents:read`. Grant only what is needed.
2. Copy the key (starts with `opk_`); it is shown once.
3. **Integrations → Connect an AI client (MCP)** shows the endpoint (by default `http://127.0.0.1:8000/mcp`) and a configuration snippet:
   ```json
   {"mcpServers": {"opspilot": {"type": "http", "url": "http://127.0.0.1:8000/mcp", "headers": {"X-API-Key": "opk_..."}}}}
   ```
   - **Claude Desktop / Cursor**: add this to the client's MCP configuration file and restart it.
   - **Claude Code**: `claude mcp add --transport http opspilot http://127.0.0.1:8000/mcp --header "X-API-Key: opk_..."`
4. In the client, ask "list the OpsPilot agents". Available tools: `list_agents`, `describe_agent`, `run_agent`, `start_workflow`, `get_workflow_run`, `list_pending_approvals`, `search_knowledge`.
5. Anything consequential an agent proposes still waits in **Approvals**; the client cannot approve. Its activity appears in the audit trail under `apikey:<prefix>`.

If the client reports "API key lacks scope '…'", add that scope by creating a new key. For a server reachable under another host name, its host must be added to the MCP allowed-hosts setting.

### Recipe 7: Add a custom HTTP tool

*Role: admin (`integrations:admin`). For technical admins.*

1. **Integrations → Custom tools → New tool**.
2. Fill in:
   - **Name**: lowercase slug, 2–48 characters, for example `order_lookup` (cannot be changed later).
   - **Timeout (seconds)**: 1–60 (default 15).
   - **Description**: what it does, at least 5 characters. The Copilot uses this to decide when to call it, so be specific.
   - **Method**: GET, POST, PUT, PATCH or DELETE.
   - **URL template**: an absolute https address, with `{placeholders}` for values taken from the input, for example `https://api.example.com/v1/orders/{order_id}`. Placeholders are not allowed in the host name. If you use a placeholder not yet in the input schema, click the **Add … to the input schema** link.
   - **Auth header name** (for example `Authorization` or `X-Api-Key`) and **Auth secret** (for example `Bearer sk_live_…`), stored encrypted and never shown again.
   - **Input schema (JSON Schema)**: the fields the Copilot must fill in. Inputs are validated before any request.
   - **Static headers**: non-secret headers sent with every call.
   - **Has side effects**: switch on if the tool changes anything. Copilot calls then wait for approval, and the risk is at least medium.
   - **Risk level** and **Enabled**.
3. Click **Create tool**.
4. Click **Test**, adjust the sample input and click **Send test request**. This sends one real request and shows the response (or the error and its time). For side-effecting tools you must tick the box acknowledging that the test sends a real request.
5. Ask the Copilot something the tool answers; the trace shows `custom__order_lookup`.

Placeholder values go into the URL; the remaining fields are sent as query parameters (GET, DELETE) or a JSON body (POST, PUT, PATCH).

### Recipe 8: Run evaluations

*Role: admin.*

1. Open **Evaluations**.
2. Click **Run** on one agent, or **Run all** (confirm; this takes a while).
3. Check **Result** and **Accuracy**; click a row to see failing checks.
4. Compare after changes (agent configuration, model override, provider). If the **Model** shows `heuristic-fallback`, the AI provider was unavailable and the run measured the built-in logic, not the AI model; rerun when the provider is available.

Evaluations never execute actions, but they do use AI tokens.

### Recipe 9: Emergency stop

*Role: admin.* Use this when agents are doing something wrong and you need everything to stop now.

1. **Admin → Tenant**. In the red **Emergency disable** panel, turn the switch on.
2. Type `DISABLE` and click **Disable all agents**.
3. Effects: every agent stops for the tenant; new workflow runs cannot start; running workflows fail at their next agent step; any new action is blocked by policy; the Copilot has no agents to call; a red badge shows in the top bar; a critical audit event is recorded.
4. Pending approvals stay pending, and **Approve** is refused while the stop is on ("Agents are emergency-disabled…"), so nothing already queued can run. You can still **Reject** (with a note) anything you are sure you do not want. Remember that pending approvals keep their expiry time.
5. Investigate (Audit trail, Incidents, Workflows).
6. To resume, turn the switch off and confirm. Agents return to their individual enabled/disabled settings. Retry or restart the runs you need.

To stop just one agent, disable it on the Agents page instead.

### Recipe 10: Deal with a failed or timed-out run

1. Open the run from **Workflows** (filter by Failed or Timed out) or from the incident's **Run** link.
2. Read the error banner and the failed node's checkpoint and agent run (error, warnings, missing information).
3. Fix the cause: for example re-enable a disabled agent, correct the input (start a new run), fix an integration, wait for the AI provider.
4. Click **Retry** to continue from where it stopped (with a fresh 10-minute deadline), then resolve the incident.

---

## 10. Troubleshooting and FAQ

### The app won't start

- Read the `start.cmd` window: lines marked `[xx]` say what failed and how to fix it. Common ones:
  - "Python 3.10+ not found": install it with `winget install Python.Python.3.12`, then open a **new** terminal.
  - "Node.js 20+ not found": `winget install OpenJS.NodeJS.LTS`, then a new terminal.
  - "database migration failed" or "database seed failed": the database settings in `.env` are wrong or the database is unreachable.
  - "API did not become healthy" / "dashboard did not start": see the log lines printed below the message.
- Run the doctor: `powershell -ExecutionPolicy Bypass -File scripts\doctor.ps1`. It checks the project folder, Python environment, dependencies, Node.js, ports 8000 and 3000, API health, the dashboard's connection to the API and a demo login, and prints the fix for each failed check plus recent errors from the logs.
- Logs: `.run\logs\api.log.err` (API), `web.log` / `web.log.err` (dashboard), `build.log`, `seed.log`, `migrate.log`.
- A red box on the sign-in page ("The OpsPilot API is not reachable") means the dashboard runs but the API does not; run `start.cmd` again.
- If the doctor says demo login fails, re-seed: `cd backend` then `.venv\Scripts\python -m app.cli seed`.

### AI provider errors (quota 429 or overloaded 503)

OpsPilot keeps a chain of AI models: your main model, then the other Gemini models (each has its own free daily allowance), then Claude and OpenAI if their keys are configured. When a model is out of quota (HTTP 429) or overloaded (HTTP 503):
- **The next model takes over immediately.** A model out of quota rests until its quota resets (the provider tells OpsPilot when); an overloaded one rests for 30 seconds. Nothing waits on a model that is known to be down.
- **If every model is resting, agents keep working** with their built-in deterministic logic. The run's **Model** shows `heuristic-fallback` and a warning says so. Results are still valid and evidence-based, just less nuanced. Workflows and bulk runs continue.
- **The Copilot keeps answering** with its built-in planner. The header badge shows **AI paused · back HH:MM**, and the answer ends with a note that the AI model was unavailable.
- **Evaluations** run during that time measure the built-in logic, not the model (see Recipe 8).

**Gemini free tier.** Each Gemini model allows about 20 requests per day, and one Copilot answer or agent run can use several. With the default chain of three Gemini models you get roughly three times that. For steady use, enable billing on the Google AI Studio project or add an `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` as automatic backup (see the appendix).

### Pages are slow

When the database is hosted remotely, each page load or action can take a few seconds (often 2–6 s per request), and pages that make several requests take longer. Grey placeholder bars mean data is loading.
- Wait for a button's spinner to finish rather than clicking again.
- **Run agent** in the Playground and **Run evaluation** wait for the whole run; this can take tens of seconds or more.
- The Scale & workers page refreshes every 3 seconds; **Pause** it if you do not need live data.
- Workflow run pages refresh every 4 seconds while active, and the Copilot polls while it answers.

### "Why didn't the email (WhatsApp message, ticket, PO) arrive?"

Check the mode. In **Sandbox** mode nothing leaves OpsPilot: emails go to the sandbox outbox, tickets and orders are simulated. The action outcome shows a "sandbox" badge. A live integration that is **Pending test** or **Error** also falls back to the sandbox until **Test connection** passes. See [Integrations → Providers](#providers-tab).

### A workflow shows "Timed out"

- Every run has a deadline counted from its start (120–600 seconds depending on the workflow; see the [Workflow reference](#7-workflow-reference)). Time spent waiting for approval is not counted: the deadline is extended by the waiting time when the run resumes. So a timeout means the run's own processing took too long.
- Common causes: slow AI provider responses (many retries), a slow remote database, or workers that are busy or stopped (check [Scale and workers](#411-scale-and-workers) for "no live workers" or a long ready lag).
- Fix: open the run and click **Retry**. It continues from the step where it stopped, with a fresh 10-minute deadline.

### A run is "Waiting approval" for a long time

It waits until every pending approval for the run is decided. Ask someone with the right permission to decide it (Approvals page). If nobody decides before the approval expires (48 hours by default), the approval counts as not approved and the run continues without that action; the change is picked up by the background maintenance job within about a minute. You can also **Cancel run** if the run is no longer needed.

### "Needs permission" and other access messages

| Message | Meaning and fix |
|---|---|
| "Missing permission '…'" | Your role lacks this permission. Ask an admin for a role that has it (see [Roles](#3-roles-and-permissions)). |
| "Requires agents:run" / "Requires agents:admin" / "Requires tenant:admin" (button hints) | The button is disabled for your role. |
| "read-only · requires approvals:decide" on Approvals | You can view but not decide. |
| "Reviewer lacks '…'" | You cannot decide this approval; it needs someone with the named permission. |
| "Separation of duties: the requester cannot review their own request" | Ask a colleague to decide it. |
| "You cannot grant role '…' because you lack '…'" / "You cannot grant '…'" | Admins can only hand out permissions they have themselves. |
| "Agent '…' cannot run: agent is disabled for this tenant" / `agent_disabled` | Re-enable the agent (Agents page) or lift the emergency stop. |
| "Tenant is not active or is emergency-disabled" | Emergency stop is on. |
| "Agents are emergency-disabled for this tenant; approved actions cannot run…" | Emergency stop is on, so approving is refused. You can still reject; approve after the stop is lifted. |
| "Invalid input for agent '…'" (validation failed) when starting a workflow | The input does not fit the workflow's first agent. The message lists the bad or missing fields; fix them and start again. Nothing was created. |
| "Only platform administrators can change quotas/plans" | Needs the `platform_admin` role (which is also the only role that sees Admin → Tenants). |
| "The Copilot needs permission to run agents" | The Copilot requires `agents:run` (operator or admin). |

### Other common questions

- **Bulk run won't start.** At least one item does not match the agent's input. The red box lists the item numbers and reasons. Fix the CSV/JSON and try again.
- **"The Copilot is still answering".** Wait for the current answer to finish, then send.
- **Session expired.** Sign in again (sessions last 120 minutes by default).
- **Workflow failed with `quota_exceeded`.** The monthly workflow-run quota is used up (see Usage & quotas). A platform administrator can raise it.
- **Knowledge search finds nothing.** Use at least 2 characters and distinctive words (very common words are ignored); flagged documents are excluded; weak matches are not shown.
- **Custom tool test fails.** "resolves to a non-public address … blocked": the host is on a private network. "must use https": change the URL. "returned a redirect": use the final URL. "returned HTTP 4xx/5xx": check the endpoint and secret. "timed out": increase the timeout or check the endpoint. "This tool has side effects…": tick the confirmation box.
- **Can the Copilot (or an MCP client) approve things?** No. Only signed-in people with the right permission.
- **Does OpsPilot pay invoices or move money?** No. It stages payables for approval and never releases payment; payment reminders never claim payment or transfer funds.
- **Why is Realized savings $0?** The realization rate is 0 until finance sets it in Admin → Tenant → ROI assumptions.
- **Why don't the hourly/weekly workflows run on their own?** There is no built-in scheduler for them in this version; start them manually.
- **Why do I see "Live · untested"?** The integration was configured as live but has not passed **Test connection** yet; tools still use the sandbox.

---

## 11. Glossary

| Term | Meaning |
|---|---|
| Action / proposed action | Something an agent wants done through a side-effect tool (send, create, update, order, pay). |
| Action outcome | What happened to a proposed action: Executed, Approval Pending, Denied, Failed, Duplicate, Unknown. |
| Agent | A specialist AI worker with a fixed contract (inputs, outputs, tools, risk, approval rules). |
| Agent key | The technical id of an agent, for example `invoice_processing`. |
| API key | A secret (starts with `opk_`) that lets an external system use OpsPilot with limited scopes. |
| Approval | A request for a person to approve or reject one exact action. |
| Approval gate | A step in a workflow where the run pauses until all its pending approvals are decided. |
| Approval TTL | How long a pending approval stays valid before it expires (default 48 hours). |
| Audit trail | The tamper-evident log of everything consequential. |
| Bulk run (batch) | Running one agent over many inputs at once. |
| Checkpoint | The saved record of one workflow step; lets a run be inspected and resumed. |
| Collection | A group of documents in the knowledge base, for example `kb`. |
| Copilot | The chat assistant that calls agents and tools for you. |
| Correlation id | An id that ties together everything one request or run caused, across runs, approvals and audit records. |
| Dry run | A bulk run with "Execute actions" off: actions are proposed but nothing is executed. |
| Emergency disable | A tenant-wide switch that stops all agents immediately. |
| Evaluation | An automated quality test of an agent against fixed test cases. |
| Evidence (reference) | A pointer to the source of a fact, for example `crm:lead:L-1001` or `document:<id>#chunk:3`. |
| Heuristic fallback | The deterministic built-in logic an agent uses when the AI provider fails. |
| Incident | A recorded problem needing attention (failed run, policy violation, cost anomaly). |
| Integration | A connection to an external system family (CRM, email, helpdesk…), in sandbox or live mode. |
| Knowledge base | The searchable documents agents use and cite. |
| Live mode | Integration mode that calls the real external provider after a successful connection test. |
| MCP | Model Context Protocol: a standard that lets AI clients such as Claude Desktop use OpsPilot's tools. |
| Offline planner | The rule-based Copilot used when no AI provider is configured. |
| Payload / payload hash | The exact data of an action, and its fingerprint used to make sure the approved action is the one that runs. |
| Permission / scope | An `area:action` right such as `approvals:decide`; scopes are the permissions of an API key. |
| Playground | The agent page tab for running an agent once with your own input. |
| Policy engine | The fixed rule set that decides whether an action runs, needs approval or is blocked. |
| Realization rate | The finance-verified share of estimated savings that counts as real savings. |
| Risk level | Low, medium, high or critical: how consequential an agent, tool or action is. |
| Role | A named bundle of permissions assigned to users. |
| Sandbox mode | Integration mode using a built-in simulator; nothing leaves OpsPilot. |
| Separation of duties | The rule that you cannot approve a request you caused. |
| Side effect | A change to data or the outside world (as opposed to read-only). |
| Strict mode | Tenant policy where every side-effect action needs approval. |
| Tenant | Your company's isolated workspace in OpsPilot (demo: `acme-demo`). |
| Tool | A named capability agents use to read or change data in a system. |
| Worker | A process that runs background jobs (workflow steps, Copilot answers, bulk items). |
| Workflow / run | A fixed multi-step process, and one execution of it. |

---

## Appendix: For technical admins

This appendix is for the people who install and configure OpsPilot. Everyday users can skip it.

### LLM provider settings

Configured in the `.env` file in the project folder (restart with `stop.cmd` then `start.cmd` after changes):
- `LLM_PROVIDER`: `auto` (default: the first key found, in the order Gemini, Anthropic, OpenAI), `gemini`, `anthropic`, `openai`, or `mock` (no AI; agents use their deterministic logic and the Copilot its built-in planner). Keys: `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`. With no key at all, everything still works on built-in logic.
- **Automatic failover.** Every other provider that has a key becomes a backup (`LLM_FALLBACK_PROVIDERS=auto`; set `none` to disable, or a list such as `anthropic,openai`). For Gemini, `GEMINI_FALLBACK_MODELS` (default `gemini-3.8-flash,gemini-3.5-flash-lite`) adds more models with their own free quotas.
- `LLM_DEFAULT_MODEL` and `LLM_FAST_MODEL` set the main provider's models. Backup providers use `GEMINI_MODEL`, `ANTHROPIC_MODEL` / `ANTHROPIC_FAST_MODEL` and `OPENAI_MODEL` / `OPENAI_FAST_MODEL`.
- `COPILOT_MAX_ITERATIONS` (default 8) and `COPILOT_MAX_TOOL_CALLS` (default 24) bound each Copilot answer. The Copilot needs a provider with tool calling (Gemini or Claude); OpenAI is used for agents only.

`GET /api/v1/health` shows whether any AI model is available (`ai_available`, `ai_next_available_at`), and the Copilot status (`GET /api/v1/copilot/status` → `ai`) lists every route with its state. See [LIMITATIONS.md](LIMITATIONS.md) for what has and has not been verified against real providers.

### API keys, events and webhooks

- Create keys in **Admin → API keys** with the minimum scopes. Send them as `X-API-Key: opk_…`.
- External systems start workflows by posting business events: `POST /api/v1/events` with `{"source", "event_type", "external_id", "payload"}` (scope `events:write`). The event type selects the workflow (see the Trigger column in the [Workflow reference](#7-workflow-reference)); duplicates (same source, type and external id) are ignored. Unknown event types are stored as "unrouted".
- Provider webhooks go to `POST /api/v1/webhooks/{tenant_slug}/{provider}` and must be signed with the **Webhook secret** stored on the integration (or the global `WEBHOOK_SIGNING_SECRET`). Invalid signatures are rejected and audited. WhatsApp's verification handshake uses `verify_token` in the WhatsApp integration's config.
- Full details: [API.md](API.md).

### MCP

- Endpoint: `/mcp` on the API port (default `http://127.0.0.1:8000/mcp`), Streamable HTTP. Authenticate with `X-API-Key: opk_…` or `Authorization: Bearer opk_…`. Each MCP tool checks the key's scope.
- For non-local host names add them to `MCP_ALLOWED_HOSTS`.

### Custom tools

- Destinations must be public https hosts. For local http testing only, `CUSTOM_TOOLS_ALLOW_PRIVATE_NETWORK=true` lifts the restriction; never use it in production.
- See [LIMITATIONS.md](LIMITATIONS.md) for the residual DNS-rebinding caveat.

### Tenant policy keys only available through the API

`PATCH /api/v1/admin/tenant` with `settings.policies` also accepts `denied_tools` (a list of tool keys that are always blocked). Settings are merged one level deep, so saving **Approval policies** in the dashboard keeps `denied_tools` and any other keys the form does not show.

### Workflow input validation

`POST /api/v1/workflows`, the MCP `start_workflow` tool and the Copilot's start-workflow helper check the input against the workflow's first agent before creating a run, and reject bad input with HTTP 422 `validation_failed` and the list of failing fields. Workflows started from inbound business events and webhooks are not pre-checked; a bad event creates a run that fails at its first step (and opens an incident).

### Example inputs

`GET /api/v1/agents/{key}` returns `example_input` (the agent's first evaluation case). The dashboard uses it to pre-fill the Playground and Bulk run tabs, and it is a reliable starting payload for `POST /agents/{key}/run`, the MCP `run_agent` tool or batches.

### Command-line tools

From the `backend` folder with the virtual environment's Python (`.venv\Scripts\python`):

| Command | Effect |
|---|---|
| `python -m app.cli seed` | Create/update the catalogue and demo tenant; prints demo accounts |
| `python -m app.cli run-workflow <key> --input '<json>'` | Start a workflow for the demo tenant and wait for the result |
| `python -m app.cli evaluate [--agent <key>]` | Run evaluations (uses the configured LLM) |
| `python -m app.cli maintenance` | Run the maintenance job once (expire approvals, recover stalled runs, reconcile, daily metrics, retention, audit sealing) |
| `python -m app.cli serve` | Run the API for development |
| `python -m app.workers.runner --concurrency 4` | Start an extra worker process (use with `WORKER_MODE=db`) |

Deployment, scaling and hardening: [DEPLOYMENT.md](DEPLOYMENT.md) and [ARCHITECTURE.md](ARCHITECTURE.md).
