# Architecture

OpsPilot is one platform, not 25 chatbots. Every agent is a thin, typed module that plugs into
shared infrastructure: the orchestrator, tool registry, policy engine, approval service, LLM
gateway, durable state and audit log.

## System diagram

```mermaid
flowchart LR
  subgraph Clients
    UI[Next.js dashboard<br/>same-origin /api/v1 proxy]
    WH[Provider webhooks<br/>signed]
    API_C[API clients<br/>X-API-Key]
    MCPC[MCP clients<br/>Claude Desktop / Code]
  end

  subgraph API["FastAPI (api/v1)"]
    AUTH[Auth: OIDC JWT / local JWT / API keys<br/>tenant from credential only]
    EV[/events/]
    WF[/workflows/]
    AG[/agents/]
    AP[/approvals/]
    ADM[/admin, integrations, reports, audit/]
    COP[/copilot, tools, custom-tools, batches, system/]
    MCP[/mcp Streamable HTTP/]
  end

  subgraph Core["Shared platform"]
    ORCH[Workflow orchestrator<br/>graph runner · checkpoints · resume · parallel · bounded delegation]
    RUN[Agent runner<br/>validate in/out · budgets · usage]
    REG[(Agent registry<br/>25 specs)]
    POL[Policy engine<br/>allow / approve / deny]
    ACT[Action service<br/>idempotency · verify · dead-letter]
    APR[Approval service<br/>payload-hash bound · SoD · expiry]
    TOOLS[(Tool registry<br/>98 typed tools)]
    LLM[LLM gateway<br/>mock / Anthropic / OpenAI<br/>structured output · safety]
    RAG[Retrieval<br/>BM25 (+pgvector)]
    LOOP[Ops Copilot tool loop<br/>Claude tool use / offline planner<br/>agents + read tools + custom tools as tools]
    CUST[Custom HTTP tools<br/>SSRF guard · encrypted secret]
  end

  subgraph Integrations
    RES[Adapter resolver]
    MOCK[13 sandbox adapters<br/>tenant sandbox records]
    LIVE[7 live adapters<br/>Slack · HubSpot · SendGrid · Jira · Shopify · WhatsApp · Zendesk]
  end

  subgraph Data["PostgreSQL (RLS) / SQLite dev"]
    DB[(28 tables: tenants, users, roles, integrations,<br/>agent defs/versions, workflow defs/runs/checkpoints,<br/>agent runs, approvals, tool executions, tasks,<br/>documents/chunks, audit (hash chain), metrics, usage,<br/>incidents, dead letters, idempotency, sandbox records)]
  end

  subgraph Workers
    Q[Durable DB job queue<br/>leases · retries · dead jobs · dedupe · tenant caps]
    WK[Worker processes ×N<br/>app.workers.runner / in-process pool / Celery]
    BEAT[Maintenance: expire approvals · reap leases · recover stale runs ·<br/>reconcile unknown executions · seal audit chain · metrics · retention]
  end

  UI --> API
  WH --> EV
  API_C --> EV
  MCPC --> MCP --> RUN
  MCP --> ORCH
  COP --> Q
  Q --> WK --> LOOP
  WK --> ORCH
  LOOP -->|agent__*| RUN
  LOOP -->|read tools| TOOLS
  LOOP -->|custom__*| POL
  ACT --> CUST
  EV --> ORCH
  WF --> ORCH
  AG --> RUN
  AP --> APR
  ORCH --> Q
  ORCH --> RUN --> REG
  RUN --> LLM
  RUN --> RAG
  RUN -->|read-only tools| TOOLS
  RUN -->|proposed actions| POL --> ACT
  POL -->|require approval| APR --> ACT
  ACT --> TOOLS --> RES
  RES --> MOCK
  RES --> LIVE
  Core --> DB
  BEAT --> DB
```

## Request lifecycle (the 15 orchestrator steps)

1. **Receive** — `POST /events` (user/API-key auth) or `POST /webhooks/{tenant}/{provider}` (HMAC-verified).
2. **Authenticate & resolve tenant** — only from the verified JWT/API key/webhook secret, never from the body.
3. **Validate & deduplicate** — payload size limits; `(tenant, dedupe_key)` unique constraint; duplicates return the original event and run.
4. **Select workflow** — `EVENT_ROUTING` (event type → workflow key) or explicit `workflow_key`; tenant-specific definitions override platform templates.
5. **Retrieve context** — agents read only through allowed, read-only tools (CRM, orders, knowledge base…).
6. **Dispatch agent** — `run_agent` validates input against the agent's Pydantic model, builds `AgentContext`, enforces token budget and tool-call limits.
7. **Validate result** — output validated against the declared output model; evidence refs checked; unsupported links/figures stripped by the agents themselves.
8. **Policy** — `evaluate_action` decides allow / require_approval / deny per proposed action, deterministically.
9. **Approval** — `Approval` row bound to `sha256(tool, type, payload, tenant, agent)`; run status → `waiting_approval`.
10. **Execute** — `ActionService.execute` writes an `in_progress` `ToolExecution` **before** calling the provider (crash marker), uses idempotency keys, and never resends a non-idempotent action after a timeout.
11. **Verify** — unknown outcomes are reconciled via `adapter.verify_action` (now or by the maintenance job).
12. **Persist** — each node transition is a `WorkflowCheckpoint`; the run's `state.nodes` holds every agent's structured output.
13. **Retry** — transient errors re-enqueue the run with backoff (bounded by `MAX_RUN_ATTEMPTS`); terminal failures open an `Incident` and a `DeadLetter`.
14. **Resume** — `recover_stale_runs` re-enqueues runs whose worker heartbeat stopped; execution continues from `current_node`.
15. **Return** — `GET /workflows/{id}` returns status, checkpoints, agent runs, pending approvals, graph and correlation id.

## Agent contract

```python
class AgentSpec:   key, name, department, version, description, use_cases,
                   input_model, output_model, allowed_tools, permission_scopes,
                   policies, approval_rules, timeout_seconds, token_budget,
                   risk_level, model_tier, evaluation_dataset, baseline_minutes_saved
class AgentContext: tenant_id, actor_id, workflow_run_id, agent_run_id, correlation_id,
                   permissions, policy_version, node_key, depth, tenant_config, agent_config, now
class AgentResult: status, data, evidence_refs, evidence, missing_information,
                   proposed_actions, warnings, summary, confidence, estimated_minutes_saved
```

Agents receive `AgentServices` with a **scoped `ToolInvoker`** (allowlist + permission + read-only
+ call limit enforcement, every call recorded as a `ToolExecution`) and the LLM gateway.
They return `ProposedAction`s; they cannot execute side effects.

### Deterministic vs model work

| Deterministic code | Model (with heuristic fallback) |
|---|---|
| routing, permissions, policy, approvals, idempotency | extraction from free text (transcripts, invoices, bug reports) |
| all money math (Decimal), scores, forecasts, KPIs, SLAs, deadlines | summaries and narratives (checked for unsupported figures/causal claims) |
| duplicate detection, 3-way matching, evidence validation | classification (intent, category) — then re-validated against rules |

Every model call goes through `LLMGateway.structured()` with a Pydantic schema and a
`heuristic` callable. Under `LLM_PROVIDER=mock` the heuristic *is* the implementation, which
is why the whole platform works offline and why tests are deterministic. With a real provider,
the heuristic is only used as a labelled fallback after retries (`model="heuristic-fallback"`
+ warning), never silently.

## Workflow graphs

Workflows are JSON graphs of typed nodes (`agent`, `condition`, `approval_gate`, `parallel`,
`workflow`, `action`, `end`) with `$.input…` / `$.nodes.<key>.data…` input mapping. Ten built-in
templates live in `orchestration/definitions.py`; tenants can add their own via
`POST /workflows/definitions` (validated: known node types, known agents, existing targets).
Bounds: `WORKFLOW_MAX_STEPS`, `MAX_DELEGATION_DEPTH = 3`, per-run deadline, per-agent token
budget and `MAX_TOOL_CALLS_PER_RUN`.

## Multi-tenancy

* Every tenant-owned table has a non-null `tenant_id` (+ index); all queries filter on the
  authenticated principal's tenant.
* On PostgreSQL the hardening migration enables **row-level security** with a policy on
  `current_setting('app.current_tenant')`, which `set_tenant_context` sets per session. Run the
  API/workers as the `opspilot_app` role so RLS applies.
* Sandbox data (`business_records`) is tenant-scoped too, so demo data never crosses tenants.
* Quotas (`workflow runs`, `LLM tokens` per month) are enforced at run start; per-tenant rate limits
  on ingestion and agent runs.

## What is mock vs live

| Component | Mock / sandbox | Live |
|---|---|---|
| LLM | `MockProvider` + per-agent heuristics (default) | Anthropic / OpenAI via official SDKs when keys are set (the Anthropic path is unit-tested against a fake client only; no live call was made in this repository) |
| Ops Copilot | deterministic offline planner drives the same tool loop | Claude tool use (`claude-opus-5-5`) when `LLM_PROVIDER=anthropic` |
| Custom tools | — | always real HTTPS calls to the tenant's endpoint (tests use `httpx.MockTransport`) |
| CRM, email, chat, issues, helpdesk, commerce, accounting, WhatsApp, workspace, monitoring, procurement, feedback, metrics | 13 sandbox adapters over tenant sandbox records (persistent, idempotent, verifiable) | HubSpot, SendGrid, Slack, Jira, Shopify, WhatsApp Cloud API, Zendesk (documented REST APIs, `httpx`, tested with `MockTransport` only — **not** validated against real accounts in this repo) |
| Accounting, procurement, workspace (Google), monitoring (Datadog/Grafana), feedback, metrics | sandbox only | not implemented; `IntegrationNotConfigured` is raised explicitly |
| Document extraction | plain text/markdown/CSV/JSON; minimal PDF literal-text extraction | plug a document-AI provider into `services/documents.extract_text` |
| Embeddings / pgvector | lexical BM25 retrieval (always on) | `VectorType` column + `ENABLE_PGVECTOR`; embedding calls not wired to a provider yet |

The dashboard labels every integration **Sandbox** or **Live**, and tool executions record the
`mode` they ran in, so audit trails never confuse the two.

## Key design decisions

* **Agents propose, the platform disposes.** No agent holds credentials or can call a
  side-effecting tool; the policy engine and approval service sit between every proposal and
  execution, and the model cannot influence their decision beyond the content it proposes.
* **Crash-safe side effects.** `ToolExecution(in_progress)` is committed before the provider call;
  idempotency keys are derived from the payload when the agent does not supply one; unknown
  outcomes are verified, not retried, for non-idempotent tools.
* **Approvals are bound to bytes.** The approval stores the exact payload and its hash; a mismatch
  (tampering or a changed action) supersedes the approval and requires a new one. Requester ≠
  reviewer, expiry, and reviewer permission are enforced in code.
* **Durable graph execution.** Node-level checkpoints + heartbeat make worker restarts safe in
  both thread and Celery modes; completed nodes are never re-run, and side effects inside a
  re-run node are deduplicated by idempotency key.
* **Portable storage.** Custom `GUID`/`JSONType`/`VectorType` columns run on SQLite (dev/test) and
  PostgreSQL (prod) from the same models and migrations; the full test suite runs on both.
* **The queue is a table.** Jobs live in PostgreSQL next to the state they act on, so enqueueing is
  transactional with the change that caused it, and scaling out is "start another worker process".
  Workers claim with `FOR UPDATE SKIP LOCKED`, hold renewable leases, and retry with backoff;
  per-tenant concurrency caps keep tenants fair. Celery remains an option, not a requirement.
* **Model-driven tool use without giving the model authority.** The Copilot lets Claude choose
  which agents and tools to call and in what order, but every tool it can see is filtered by the
  user's RBAC, built-in tools exposed to it are read-only, agents it calls still only propose, and
  custom side-effecting tools go through the same policy engine and hash-bound approvals.
* **Audit writes don't contend.** Events carry a content hash; a per-tenant sealer links committed
  events into the chain. Concurrent workers therefore never fork the chain or serialise on it.
* **Estimated ≠ realized.** ROI reporting keeps estimated labour value and finance-verified
  realized savings separate, with a default realization rate of 0.
