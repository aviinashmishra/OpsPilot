# OpsPilot AI

**A multi-tenant AI workforce platform: 25 specialist business agents on one shared, policy-gated, auditable orchestration engine.**

OpsPilot receives business events, picks the right workflow and specialist agent, executes
authorised actions through typed tools, pauses for human approval on anything consequential,
recovers from failures without duplicating side effects, and records everything.

| | |
|---|---|
| Backend | Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 · Alembic · PostgreSQL (SQLite for local dev) · Celery/Redis (thread pool for local dev) |
| AI | Provider-agnostic LLM gateway (Anthropic, OpenAI, deterministic mock) · structured outputs · token budgets · cost tracking · optional pgvector RAG |
| Frontend | Next.js 14 · React 18 · TypeScript · Tailwind · TanStack Query · Recharts · React Flow |
| Ops | Docker + Compose · GitHub Actions CI · OpenTelemetry + Prometheus · hash-chained audit log |

> **Honesty note.** Out of the box every integration runs in **sandbox mode** against synthetic
> tenant data, and the LLM provider is a **deterministic mock** (each agent ships a heuristic
> implementation of its model calls). Everything is end-to-end functional without credentials;
> nothing is ever reported as "connected" or "sent" unless a real provider was configured,
> its connection test passed, and the call succeeded. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#what-is-mock-vs-live).

## Quick start (local, no Docker)

Prerequisites: Python 3.10+ (3.12 recommended), Node.js 20+.

**Windows: double-click `start.cmd`** (or run it from a terminal). It:

- finds a real Python (skipping the Microsoft Store stub) and Node;
- creates the venv, installs pinned dependencies (only when requirements change) and writes `.env` with freshly generated `SECRET_KEY` / `ENCRYPTION_KEY`;
- frees ports held by a previous OpsPilot run (or picks the next free port), seeds the demo tenant;
- starts the API, waits for `/api/v1/health`, builds and starts the dashboard, and opens http://localhost:3000.

```powershell
start.cmd                                   # API :8000 + dashboard :3000 (production build)
scripts\start.ps1 -Dev                      # hot-reload dashboard (next dev)
scripts\start.ps1 -Workers 4                # + 4 separate worker processes (WORKER_MODE=db)
scripts\start.ps1 -ApiPort 8100 -WebPort 3100 -NoBrowser
stop.cmd                                    # stop everything it started
powershell -ExecutionPolicy Bypass -File scripts\doctor.ps1   # "it doesn't work": diagnoses ports, venv, .env, API, proxy
```

Logs are in `.run/logs/`. The dashboard calls the API through its own same-origin proxy
(`/api/v1/*` → `OPSPILOT_API_ORIGIN`), so there are no CORS or `localhost` vs `127.0.0.1`
mismatches; the login page shows a red banner with the fix if the API is not reachable.

```bash
# macOS / Linux
cp .env.example .env
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
python -m app.cli seed            # creates SQLite schema, syncs the agent catalog, seeds the demo tenant
python -m app.cli serve           # API on http://127.0.0.1:8000  (OpenAPI docs at /docs)
# optional, for real horizontal scale: WORKER_MODE=db python -m app.workers.runner --concurrency 4
# in a second terminal
cd frontend && cp .env.local.example .env.local && npm install && npm run dev   # http://localhost:3000
```

Demo accounts (tenant slug `acme-demo`, password `OpsPilot-Demo-2026!`, **local development only**):

| Email | Role | Can |
|---|---|---|
| admin@acme-demo.test | admin | everything in the tenant (not plans/quotas) |
| ops@acme-demo.test | operator | run agents/workflows, manage tasks |
| approver@acme-demo.test | approver | decide approvals incl. external sends |
| finance@acme-demo.test | finance_approver | approve payables / purchase orders |
| auditor@acme-demo.test | auditor | read audit trail and reports |
| viewer@acme-demo.test | viewer | read-only dashboards |

## Quick start (Docker Compose: PostgreSQL + Redis + Celery)

```bash
cp .env.example .env            # set SECRET_KEY and ENCRYPTION_KEY
docker compose up --build       # api :8000, web :3000, worker, beat, db, redis
```

The `migrate` service runs `alembic upgrade head` and seeds the demo tenant before the API starts.

## Deploy (Render / Vercel)

API on Render via the [`render.yaml`](render.yaml) Blueprint (Render → New → Blueprint), database on
Neon, dashboard on Render or Vercel (root directory `frontend`, env `OPSPILOT_API_ORIGIN` = API URL).
Always set `DEMO_PASSWORD` on a public deployment. Step by step:
[docs/DEPLOYMENT.md → Render / Vercel](docs/DEPLOYMENT.md#render--vercel-hosted-demo).

## Try the demo in 60 seconds

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"tenant":"acme-demo","email":"ops@acme-demo.test","password":"OpsPilot-Demo-2026!"}' | jq -r .access_token)

# 1. A new lead arrives → qualified → CRM record → outreach drafted → waits for approval
curl -s -X POST localhost:8000/api/v1/events -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"source":"webform","event_type":"lead.created","external_id":"demo-1","payload":{"lead":{"name":"Ana Silva","email":"ana@globex.test","company":"Globex","title":"VP Operations","industry":"logistics","company_size":900,"budget":80000,"timeline":"this quarter","message":"We need to automate warehouse exception handling."}}}'

# 2. See the run, its checkpoints, agent outputs and the pending approval
curl -s localhost:8000/api/v1/workflows?limit=1 -H "authorization: Bearer $TOKEN" | jq '.items[0] | {id,status,current_node}'
curl -s "localhost:8000/api/v1/approvals?status=pending" -H "authorization: Bearer $TOKEN" | jq '.items[0] | {id,tool_key,risk_level,reason,payload_hash}'
```

Approve it from the dashboard (Approval Center) as `approver@acme-demo.test`, or via
`POST /api/v1/approvals/{id}/decision`. The run resumes and completes; the "email" lands in the
sandbox outbox (never sent anywhere).

Other end-to-end demos (also run by the CLI and the test-suite):

```bash
cd backend
python -m app.cli run-workflow meeting_to_tasks  --input '{"meeting_id":"MTG-1"}'
python -m app.cli run-workflow customer_query    --input '{"message":"How long does standard shipping take?","customer_id":"C-2001"}'
python -m app.cli run-workflow invoice_to_review --input "{\"document_text\":\"$(cat docs/samples/invoice_ok.txt)\"}"
python -m app.cli run-workflow release_watch     --input '{"service":"checkout-api","deployment_id":"DEP-301"}'
python -m app.cli run-workflow kpi_report        --input '{"period_days":14,"months":3}'
python -m app.cli evaluate                        # runs all 25 synthetic evaluation datasets
```

## Ops Copilot: agents and tools driven by the model

The **Copilot** page (`/copilot`, API `POST /api/v1/copilot/sessions`) is a chat front-end over
the whole platform. Each turn runs a bounded tool-use loop in which the model can call:

| Tool family | What it does | Gate |
|---|---|---|
| `agent__<key>` (25) | runs a specialist agent; its proposed actions go through the policy engine as usual | approvals created → step shows `needs_approval` |
| `<family>__<op>` (27) | read-only registry tools: orders, shipments, inventory, KPIs, tasks, SOPs, invoices… | read-only by allow-list |
| `ops__*` | list agents / approvals / workflows, get a run, start a workflow | caller's RBAC |
| `custom__<name>` | your tenant's own HTTP tools (below) | side-effecting ones always require approval |

Several tool calls in one model turn run together and their results go back in one message;
failures return as `is_error` results the model can recover from; iterations and tool calls are
capped (`COPILOT_MAX_ITERATIONS`, `COPILOT_MAX_TOOL_CALLS`). Every step is persisted and shown live.
With `LLM_PROVIDER=anthropic` the loop is driven by Claude (`claude-opus-5-5`, adaptive effort,
prompt caching, server-side fallbacks). With the mock provider a deterministic offline planner
drives the same loop, so the page works without a key. Each answer records which mode produced it.

Turns run on the job queue, never in the request: `POST .../messages` returns immediately and
the UI polls the session.

## Custom tools (bring your own API)

Admins register HTTPS endpoints as tools (Integrations → Custom tools, or `POST /api/v1/custom-tools`):
name, method, URL template, JSON input schema, optional secret header (Fernet-encrypted at rest),
and `side_effect`. The tool is then usable by the Copilot as `custom__<name>`.

Guard-rails: https only; DNS is resolved and **every** address must be public (no loopback,
RFC 1918, link-local/metadata, CGNAT…); no redirects; per-tool timeout (default 15 s); 256 KB
response cap; input validated against the schema; side-effecting calls need an approval bound
to the exact payload hash and run exactly once with an idempotency key.
`POST /custom-tools/{id}/test` makes one real call with sample input and shows you the actual
response; nothing is pre-filled or simulated.

## MCP server (use OpsPilot from Claude Desktop, Claude Code, any MCP client)

The API serves a Streamable HTTP MCP endpoint at `http://127.0.0.1:8000/mcp` with tools
`list_agents`, `describe_agent`, `run_agent`, `start_workflow`, `get_workflow_run`,
`list_pending_approvals`, `search_knowledge`. Authenticate with a tenant API key
(`POST /api/v1/admin/api-keys`, e.g. scopes `["agents:read","agents:run","workflows:read","workflows:write","approvals:read","documents:read"]`):

```bash
claude mcp add --transport http opspilot http://127.0.0.1:8000/mcp --header "X-API-Key: opk_..."
```

Scopes are enforced per tool, and everything an MCP client does goes through the same policy
engine, approvals and audit log as the dashboard. For a public host add it to `MCP_ALLOWED_HOSTS`.

## Scaling

| `WORKER_MODE` | Who executes workflows, Copilot turns, bulk items | Use |
|---|---|---|
| `inline` | the calling thread | tests |
| `thread` (default) | a worker pool inside the API process, fed by the durable DB queue | single machine |
| `db` | any number of `python -m app.workers.runner --concurrency N` processes / containers on the same DB | horizontal scale |
| `celery` | Celery workers via Redis (workflows) | existing Celery estates |

The queue lives in the `jobs` table: on PostgreSQL workers claim with `FOR UPDATE SKIP LOCKED`.
Each claim takes a lease that the worker renews; a crashed worker's leases expire and the jobs
return to the queue with backoff, and go to `dead` after `max_attempts` (retry from `/system`).
Jobs are deduplicated (`dedupe_key`), tenants have a concurrency cap (`max_concurrent_runs`) so one
tenant cannot starve the others, and a workflow run additionally holds an atomic run lease so two
workers can never execute the same run. **Bulk runs** (`POST /api/v1/agents/{key}/batches`, up to
5,000 items) fan out one job per item; a stuck item whose worker died is reclaimed.
`/system` in the dashboard shows the queue, live workers and dead jobs.

Measured with real worker processes on one laptop (mock LLM): on PostgreSQL a 300-item bulk run
went from 14 to 21 items/s with 1 → 4 worker processes. Hard-killing a worker mid-run lost no items
and duplicated no side effects. SQLite gets no benefit from more workers. Full table and caveats
in [docs/DEPLOYMENT.md → Scale benchmark](docs/DEPLOYMENT.md#scale-benchmark).

## Repository layout

```
backend/
  app/
    agents/           base contract, registry, runner, services; catalog/ = the 25 agents (one module each)
    orchestration/    workflow engine (graph runner, checkpoints, resume, parallel, delegation), built-in definitions
    policy/           deterministic policy engine (allow / require_approval / deny)
    services/         actions (execute + reconcile), approvals, audit, usage, retrieval, maintenance, documents
    tools/            typed tool registry + catalog (98 tools) + platform adapter
    integrations/     adapter contract, 13 sandbox adapters, 7 live adapters, resolver, resilience helpers
    llm/              provider-agnostic gateway, mock provider, prompt-injection safety
    api/              FastAPI routes (v1), schemas, serializers, auth deps
    db/               SQLAlchemy models (28 tables), portable types, session
    workers/          thread/Celery queue, scheduler, maintenance jobs
    evaluation/       synthetic datasets + harness
    seed/             roles/permissions, catalog sync, demo tenant data
  alembic/            migrations (initial schema + PostgreSQL RLS/append-only hardening)
  tests/              unit · integration · security · agents · e2e  (236 tests; run on SQLite and PostgreSQL)
  load/               scale benchmark: real API + worker processes, crash test, exactly-once checks
frontend/             Next.js dashboard (see frontend/README.md)
docs/                 ARCHITECTURE · API · DEPLOYMENT · THREAT_MODEL · KPI_AND_ROI · EVALUATION_REPORT_TEMPLATE
docker-compose.yml · .github/workflows/ci.yml · .env.example · scripts/dev.ps1 · Makefile
```

## The 25 agents

| # | Department | Agent (`agent_key`) | Consequential actions are gated by |
|---|---|---|---|
| 1 | Sales | Lead Qualification (`lead_qualification`) | — (CRM writes are low risk) |
| 2 | Sales | AI Sales Development (`sales_development`) | approval before any email send |
| 3 | Sales | Sales Call Intelligence (`sales_call_intelligence`) | consent flag required |
| 4 | Sales | Proposal Generator (`proposal_generator`) | approval before delivery; deal desk for non-standard terms |
| 5 | Support | Customer Support (`customer_support`) | escalates unsupported/sensitive queries |
| 6 | Support | Complaint Resolution (`complaint_resolution`) | compensation only as approval-gated recommendation |
| 7 | Support | WhatsApp Business (`whatsapp_business`) | opt-in, 24h window, templates, approval |
| 8 | Support | Customer Retention (`customer_retention`) | campaigns never auto-sent |
| 9 | E-commerce | AI Shopping Assistant (`shopping_assistant`) | never checks out |
| 10 | E-commerce | Order Management (`order_management`) | customer updates & status changes approved |
| 11 | E-commerce | Inventory Forecasting (`inventory_forecasting`) | purchase orders critical-risk |
| 12 | E-commerce | Product Listing (`product_listing`) | publishing approved |
| 13 | Operations | Workflow Coordinator (`workflow_coordinator`) | escalations approved |
| 14 | Operations | Meeting-to-Execution (`meeting_to_execution`) | directory-resolved owners only |
| 15 | Operations | SOP Compliance (`sop_compliance`) | escalates significant findings |
| 16 | Operations | Business Intelligence (`business_intelligence`) | read-only |
| 17 | Finance | Invoice Processing (`invoice_processing`) | payables approved; never pays |
| 18 | Finance | Expense Audit (`expense_audit`) | routes to reviewers |
| 19 | Finance | Payment Follow-up (`payment_followup`) | reminders approved; never transfers |
| 20 | Finance | Procurement (`procurement`) | PO critical-risk |
| 21 | Technology | QA Testing (`qa_testing`) | execution approved, never production |
| 22 | Technology | Bug Triage (`bug_triage`) | human review when uncertain/critical |
| 23 | Technology | Product Research (`product_research`) | read-only |
| 24 | Technology | Release Monitoring (`release_monitoring`) | rollback is a recommendation only |
| 25 | Technology | Finance-Aware Business Analyst (`finance_analyst`) | read-only |

Each agent declares its contract (input/output schemas, allowed tools, permission scopes,
policies, approval rules, budgets) in code; `GET /api/v1/agents/{key}` exposes it.

## Testing

```bash
cd backend
pytest -q                         # 236 tests: unit, integration, security, per-agent, e2e (SQLite)
TEST_DATABASE_URL=postgresql+psycopg://…/empty_db pytest -q   # the same suite on PostgreSQL (schema via Alembic)
python -m load.scale_benchmark --check                         # multi-process throughput + crash test
python -m app.cli evaluate        # synthetic evaluation datasets (precision/recall, accuracy, intervention rate…)
ruff check app tests
```

Tests use SQLite, the mock LLM provider and sandbox adapters: no network, no real customer
data, no real messages. CI additionally runs the migrations and a smoke evaluation against
PostgreSQL, `pip-audit`, `bandit`, builds both containers and scans them with Trivy.

## Configuration

See [`.env.example`](.env.example). Key switches:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `sqlite:///./opspilot.db` (dev) or `postgresql+psycopg://…` (prod) |
| `WORKER_MODE` | `inline` (tests) · `thread` (dev) · `db` (separate `app.workers.runner` processes) · `celery` (needs `REDIS_URL`) |
| `WORKER_CONCURRENCY`, `JOB_LEASE_SECONDS` | in-process pool size; how long before a dead worker's jobs are re-queued |
| `LLM_PROVIDER` | `mock` · `anthropic` (+`ANTHROPIC_API_KEY`) · `openai` (+`OPENAI_API_KEY`) |
| `LLM_DEFAULT_MODEL`, `LLM_EFFORT`, `COPILOT_EFFORT` | model (`claude-opus-5-5`) and effort per tier |
| `COPILOT_MAX_ITERATIONS`, `COPILOT_MAX_TOOL_CALLS` | hard bounds on one Copilot turn |
| `MCP_ALLOWED_HOSTS` | Host headers the `/mcp` endpoint accepts (DNS-rebinding protection) |
| `CUSTOM_TOOLS_ALLOW_PRIVATE_NETWORK` | `false` by default; only for an isolated on-prem network you control |
| `SECRET_KEY`, `ENCRYPTION_KEY` | JWT signing and Fernet encryption of integration credentials |
| `OIDC_ISSUER`, `OIDC_JWKS_URL`, `OIDC_AUDIENCE` | SSO; set `ALLOW_PASSWORD_LOGIN=false` once configured |

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Dashboard opens but nothing loads / login fails | run `scripts\doctor.ps1`; the login page banner says whether the API is reachable through the proxy |
| `start.cmd` says a port is busy | it frees ports held by an old OpsPilot run itself; otherwise it picks the next free port and prints it |
| `python` opens the Microsoft Store | the WindowsApps stub; install Python from python.org, `start.cmd` skips the stub |
| Copilot message stays "thinking" | no worker is running: `WORKER_MODE=db` needs at least one `app.workers.runner`; check `/system` |
| Jobs in `dead` on `/system` | they failed `max_attempts` times; read `last_error`, fix, press Retry |
| `email-validator is not installed` | `pip install -r backend/requirements-dev.txt` (pinned) |
| Login returns 422 for `*.test` addresses | fixed: the API uses a syntactic e-mail check (RFC deliverability is the IdP's job) |
| `/health/ready` returns 503 | DB unreachable, or in production: unsafe `SECRET_KEY`, SQLite, missing `ENCRYPTION_KEY` |
| Runs stay `pending` | `WORKER_MODE=celery`/`db` without a worker; start `celery -A app.workers.celery_app:celery_app worker -Q workflows` / `python -m app.workers.runner`, or use `thread` |
| Run stuck `running` after a crash | the maintenance job (every 60 s) re-enqueues stale runs; `python -m app.cli maintenance` runs it once |
| Agent returns `agent_disabled` (423) | agent disabled for the tenant or tenant emergency-disabled (Admin → Tenant) |
| Integration shows `error` | the live connection test failed; see `last_error`; it stays unusable (sandbox fallback) until a test passes |
| Approvals return 409 | expired, already decided, or payload hash mismatch (re-request approval) |
| Windows: `winget` installed Python/Node but commands not found | open a new terminal, or use the full paths in `scripts/dev.ps1` |

## Documentation

- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — how to use every page, agent, tool and workflow (for operators, approvers and admins)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, data flow, diagram, design decisions, mock vs live
- [docs/API.md](docs/API.md) — endpoints, auth, pagination, errors, idempotency, webhooks
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — production prerequisites, PostgreSQL RLS, secrets, scaling, backup/restore, observability
- [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) — assets, trust boundaries, threats and mitigations
- [docs/KPI_AND_ROI.md](docs/KPI_AND_ROI.md) — KPI definitions, ROI calculator, alerts
- [docs/EVALUATION_REPORT_TEMPLATE.md](docs/EVALUATION_REPORT_TEMPLATE.md)
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md) — what is mock, what is real, what is left for production

## License

Proprietary — all rights reserved (change as appropriate for your organisation).
