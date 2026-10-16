# API reference (v1)

Base URL: `http://<host>:8000/api/v1`. Interactive docs: `/docs` (Swagger) and `/redoc`; the
OpenAPI document is at `/openapi.json`. All responses are JSON.

## Authentication

| Method | Header | Use |
|---|---|---|
| Bearer JWT (local issuer) | `Authorization: Bearer <token>` from `POST /auth/login` | dashboard users (dev; disable with `ALLOW_PASSWORD_LOGIN=false`) |
| Bearer JWT (OIDC) | token issued by your IdP; verified against `OIDC_JWKS_URL` | SSO users, mapped by `sub` to `users.external_subject` |
| API key | `X-API-Key: opk_…` created in Admin → API keys | machine clients (event ingestion, reporting) |
| Webhook signature | `X-OpsPilot-Signature: t=<unix>,v1=<hmac-sha256>`; Meta `X-Hub-Signature-256`; Shopify `X-Shopify-Hmac-Sha256` | provider webhooks (no bearer token) |

The tenant is always derived from the verified credential. Tenant IDs in request bodies are ignored.

**Permissions** are strings like `workflows:write`; roles aggregate them (`admin` = `*`;
`platform:admin` must be granted explicitly). Every endpoint lists its required permission in
the OpenAPI description. Approvals must be decided by human users (API keys are refused).

## Conventions

* **Pagination**: `limit` (max 200/500) and `offset`; responses are `{items, total, limit, offset}`.
* **Filtering**: documented query parameters per endpoint (e.g. `status`, `workflow_key`, `q`, `severity`, `correlation_id`).
* **Errors**: `{"error": {"code", "message", "details", "correlation_id"}}` with stable codes:
  `validation_failed` 422 · `unauthenticated` 401 · `forbidden` / `tool_not_allowed` / `tenant_isolation_violation` 403 ·
  `not_found` 404 · `conflict` 409 · `agent_disabled` 423 · `integration_not_configured` 424 · `quota_exceeded` / `rate_limited` 429 ·
  `integration_error` / `llm_error` 502 · `internal_error` 500 (never includes stack traces).
* **Correlation**: send `X-Correlation-ID` (alphanumeric, ≤ 64) or receive a generated one; it is stamped on runs, audit events and logs.
* **Idempotency**: `Idempotency-Key` header on `POST /workflows`, `POST /events`, `POST /agents/{id}/run`. A reused key with a different body returns 409. Events are additionally deduplicated by `(source, event_type, external_id)`.
* **Sensitive data**: outputs are redacted (secrets always; long free-text fields truncated unless the user holds `data:sensitive`). Credentials are write-only.

## Endpoints

### Auth
| Method & path | Permission | Notes |
|---|---|---|
| `POST /auth/login` | — | `{tenant, email, password}` → `{access_token, expires_in, user, tenant}`; rate-limited per IP |
| `GET /auth/me` | any | current user, roles, permissions, tenant |
| `GET /auth/demo-accounts` | — | seeded demo users (empty in production) |

### Events & webhooks
| `POST /events` | `events:write` | `{source, event_type, external_id?, payload, workflow_key?}` → 202 `EventOut` (`status`: dispatched / unrouted / failed; `duplicate` flag) |
| `GET /events` | `events:read` | filters `status`, `event_type` |
| `POST /webhooks/{tenant_slug}/{provider}` | signature | normalises provider payloads (WhatsApp Cloud API, Shopify) into events |
| `GET /webhooks/{tenant_slug}/whatsapp` | — | Meta verification handshake (`hub.verify_token` from the integration config) |

### Workflows
| `POST /workflows` | `workflows:write` | `{workflow_key, input}` → 202 run (status `pending` → executes async; `inline` mode executes synchronously) |
| `GET /workflows` | `workflows:read` | `status` (comma list), `workflow_key`, `q` (run id / correlation id) |
| `GET /workflows/{run_id}` | `workflows:read` | detailed: `checkpoints[]`, `agent_runs[]`, `state.nodes`, `pending_approvals[]`, `graph`, `output` |
| `POST /workflows/{run_id}/cancel` | `workflows:write` | cancels pending/waiting runs immediately; running runs stop at the next node |
| `POST /workflows/{run_id}/retry` | `workflows:write` | failed/timed-out runs resume from the last checkpoint |
| `GET /workflows/definitions` | `workflows:read` | platform templates + tenant definitions |
| `POST /workflows/definitions` | `workflows:admin` | validated graph; versions automatically |

### Agents
| `GET /agents` | `agents:read` | all 25 with tenant enablement, config and run stats; filters `department`, `q` |
| `GET /agents/{agent_id}` | `agents:read` | contract (schemas), tools, policies, recent runs, latest evaluation |
| `PATCH /agents/{agent_id}` | `agents:admin` | `{enabled, config, model_override, disabled_reason}` |
| `POST /agents/{agent_id}/run` | `agents:run` | `{input, mode: "workflow" (durable, approval-gated) | "direct"}` → result, actions, usage, tool modes |
| `GET /agents/{agent_id}/runs` | `agents:read` | paginated run history |

### Tasks, approvals, integrations
| `GET/POST /tasks`, `PATCH /tasks/{id}` | `tasks:read` / `tasks:write` | board; `overdue=true` filter |
| `GET /approvals` | `approvals:read` | `status` (default `pending`; `all`), `risk_level`, `agent_key`, `run_id` |
| `GET /approvals/{id}` | `approvals:read` | exact payload, hash, policy, evidence, context |
| `POST /approvals/{id}/decision` | `approvals:decide` + the approval's `required_permission` | `{decision: approve|reject, note?, payload_hash?}`; executes exactly once on approve; resumes the run |
| `GET /integrations` | `integrations:read` | one row per provider family with `mode` (mock/live), status, last test |
| `GET /integrations/catalog` | `integrations:read` | families, supported live providers, required credentials |
| `POST /integrations` | `integrations:admin` | upsert; credentials encrypted at rest; live rows start `pending_test` |
| `POST /integrations/{id}/test` | `integrations:admin` | real connection test; only a passing test sets `connected` |
| `POST /integrations/{id}/sync` | `integrations:admin` | records a sync checkpoint |

### Reports, usage, audit, incidents, documents, evaluations, admin
| `GET /reports/overview?days=` | `reports:read` | dashboard overview |
| `GET /reports?days=` | `reports:read` | KPIs, ROI, per-agent and per-workflow performance |
| `GET /usage?period=YYYY-MM` | `usage:read` | metering + quotas + utilisation |
| `GET /audit-events` · `GET /audit-events/verify` | `audit:read` | searchable trail; hash-chain verification |
| `GET /incidents` · `POST /incidents/{id}/resolve` | `reports:read` / `incidents:write` | |
| `GET /documents` · `POST /documents/text` · `POST /documents/upload` · `GET /documents/search?q=` · `DELETE /documents/{id}` | `documents:*` | scanned (active PDF content, injection, secrets), chunked, indexed |
| `GET /evaluations` · `POST /evaluations/run` · `POST /evaluations/run-all` | `agents:read` / `agents:admin` | synthetic evaluation harness |
| `GET/PATCH /admin/tenant` | `tenant:read` / `tenant:admin` | settings (`policies`, `roi`), retention, **emergency_disabled**; plan/quotas need `platform:admin` |
| `GET/POST /admin/users`, `PATCH /admin/users/{id}` | `users:*` | privilege-escalation guarded |
| `GET/POST /admin/roles`, `GET /admin/permissions` | `roles:*` | |
| `GET/POST/DELETE /admin/api-keys` | `apikeys:admin` | plaintext returned once |
| `GET/POST /admin/tenants` | `platform:admin` | tenant onboarding |

### Ops Copilot (model-driven tool use)
| Method & path | Permission | Notes |
|---|---|---|
| `GET /copilot/status` | `agents:run` | mode (`claude` / `offline`), model, and the tools this user can reach |
| `POST /copilot/sessions` | `agents:run` (users only; API keys → 403) | `{message}` → 202 session; the turn runs on the job queue |
| `GET /copilot/sessions` · `GET /copilot/sessions/{id}` | `agents:run` | own sessions only (others → 403); poll the session while a message is `running`: `messages[].steps[]` are the live tool calls (`tool`, `input`, `status` ok / error / needs_approval, `output`) |
| `POST /copilot/sessions/{id}/messages` | `agents:run` | follow-up; 409 while the previous turn is still running |
| `DELETE /copilot/sessions/{id}` | `agents:run` | |

### Tools, custom tools, bulk runs, queue
| Method & path | Permission | Notes |
|---|---|---|
| `GET /tools` | `agents:read` | every built-in tool (family, risk, side effect, input schema) + this tenant's custom tools |
| `GET /custom-tools` | `integrations:read` | secrets never returned (`has_secret` only) |
| `POST /custom-tools` · `PATCH/DELETE /custom-tools/{id}` | `integrations:admin` | `{name, description, method, url_template, input_schema, headers?, auth_header_name?, auth_secret?, side_effect, risk_level, timeout_seconds}`; URL must be https and resolve to public addresses |
| `POST /custom-tools/{id}/test` | `integrations:admin` | one real call with `{input}` → `{ok, latency_ms, result, error}`; side-effecting tools also need `confirm_side_effect: true`; audited |
| `POST /agents/{agent_id}/batches` | `agents:run` | `{items: [input, …] (≤ 5,000), name?, execute_actions}` → 202; each item is validated against the agent's input schema before anything is queued |
| `GET /batches` · `GET /batches/{id}` | `agents:read` | progress counters + item results (`status` filter, paginated) |
| `POST /batches/{id}/cancel` | `agents:run` | queued items become `cancelled`; running ones finish |
| `GET /system/queue` | `reports:read` | queue depth by kind/status, live workers (heartbeats), recent and dead jobs |
| `POST /system/jobs/{id}/retry` | `tenant:admin` | re-queue a `dead` job of this tenant |

### MCP (Model Context Protocol)
`POST /mcp` (Streamable HTTP, stateless, JSON responses; outside `/api/v1`). Auth: `X-API-Key: opk_…`
or `Authorization: Bearer opk_…`. Tools and the scope each needs: `list_agents`, `describe_agent`
(`agents:read`), `run_agent` (`agents:run`), `start_workflow` (`workflows:write`),
`get_workflow_run` (`workflows:read`), `list_pending_approvals` (`approvals:read`),
`search_knowledge` (`documents:read`). Errors come back as MCP tool errors (`isError: true`) with
the platform's message. Host header must match `MCP_ALLOWED_HOSTS`.

### Health & metrics
`GET /api/v1/health` (public: version, LLM mode, worker mode; used by the dashboard and `start.ps1`), `GET /health/live`, `GET /health/ready` (503 when DB unreachable or production config unsafe), `GET /metrics` (Prometheus).

## Tenant policy settings (`PATCH /admin/tenant` → `settings.policies`)

```json
{
  "approval_mode": "standard",            // or "strict": every side effect needs approval
  "amount_threshold": 1000,               // payload amounts above this need approval
  "external_comms_require_approval": true,
  "separation_of_duties": true,
  "approval_ttl_hours": 48,
  "denied_tools": ["commerce.create_purchase_order"],
  "auto_approve": [                       // narrow allowlists only; critical-risk tools can never be auto-approved
    {"name": "receipts", "tool": "email.send", "conditions": {"template_id_in": ["TPL-RECEIPT"]}},
    {"name": "ops-chat", "tool": "chat.post_message", "conditions": {"channel_in": ["#ops"]}}
  ]
}
```
