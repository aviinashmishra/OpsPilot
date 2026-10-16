# Security threat model

Scope: the OpsPilot platform (API, workers, dashboard, database, integrations, LLM providers).
Method: STRIDE over the trust boundaries below, with mitigations that exist in code today and
residual risks called out explicitly.

## Assets

1. Tenant business data (leads, customers, orders, invoices, transcripts, documents).
2. Integration credentials and webhook secrets.
3. The ability to trigger external side effects (emails, WhatsApp, tickets, POs, payables).
4. Approval decisions and the audit trail (non-repudiation).
5. LLM spend / quotas.
6. User identities and roles.

## Trust boundaries

```
Internet ──► [B1] API edge (TLS, auth, rate limits)
API ──► [B2] Orchestrator/agents (untrusted content enters prompts here)
Agents ──► [B3] Policy engine + approvals (only path to side effects)
Platform ──► [B4] Providers (live adapters) and LLM providers
Platform ──► [B5] Database (tenant isolation) and object storage
Dashboard (browser) ──► [B6] API
```

## Threats and mitigations

| ID | Threat (STRIDE) | Mitigation in code | Residual / operator action |
|---|---|---|---|
| T1 | **Spoofing** a tenant via forged tenant id / claims | Tenant derived only from verified JWT (`tid` + user lookup must match) or API key row; forged tokens with unknown users rejected (test `test_tenant_claim_in_token_cannot_be_forged`) | Protect `SECRET_KEY`; prefer OIDC with RS256 + JWKS |
| T2 | **Spoofed webhooks** inject events | HMAC verification per provider (OpsPilot `t=,v1=` with 5-min replay window; Meta `sha256=`; Shopify base64), per-integration secrets, tenant resolved from path + verified | Rotate webhook secrets; monitor `webhook.signature_invalid` audit events |
| T3 | **Tampering** with an approved action between approval and execution | Approval bound to `sha256(tool, action_type, payload, tenant, agent)`; mismatch → `superseded` + critical audit event; reviewer may echo the hash they saw | DB write access is itself privileged; alert on `approval.tampered` |
| T4 | **Tampering** with the audit log | Each event stores a SHA-256 content hash; a single sealer per tenant links committed events into a gap-free chain (`seq`, `prev_hash`, `chain_hash`); `GET /audit-events/verify` recomputes every content hash and link, so edits and deletions are detected; on PostgreSQL the app role has no UPDATE/DELETE except the three chain columns, and a trigger refuses to change a sealed event or any event's content (tests: `tests/integration/test_audit_chain.py`, run on SQLite and PostgreSQL) | Events are unsealed for ≤ 1 min after writing; the oldest retained event is the trust anchor after retention; anyone with the DB owner role can rewrite history, so ship sealed chain heads (or the events) to an external WORM store |
| T5 | **Repudiation** of approvals | Reviewer id, timestamp, note and execution result stored; decisions only by human principals (API keys refused); separation of duties | Enforce MFA at the IdP |
| T6 | **Information disclosure** across tenants | `tenant_id` on every table + application filters; PostgreSQL RLS policies; sandbox records tenant-scoped; cross-tenant tests | Run DB as `opspilot_app` so RLS is active; never query with the owner role |
| T7 | **Information disclosure** of secrets | Credentials Fernet-encrypted; API keys stored as SHA-256; log/serializer redaction of secret-looking keys and bearer tokens; credentials write-only in API; error handler never returns stack traces | Store `ENCRYPTION_KEY` in a secrets manager; rotation runbook |
| T8 | **Prompt injection** via customer messages, transcripts, documents, reviews | Untrusted text wrapped as data with explicit instruction; pattern scan → warnings and escalation to humans; agents validate outputs deterministically (citations must match retrieved sources, numbers must exist in inputs, owners must resolve in the directory); the model never decides policy; tools are allowlisted per agent | New injection styles evade regexes: keep humans in the loop for high-risk actions (default policy) |
| T9 | **Elevation of privilege** by the model ("grant yourself admin") | Permissions come from roles/API-key scopes only; policy engine evaluates tool allowlists + actor permissions; critical tools always need approval; `platform:admin` is never implied by `*` | — |
| T10 | **Elevation of privilege** by users | Role grants limited to the granter's own permissions; cannot remove own admin/deactivate self; quotas/plans only for `platform:admin` | — |
| T11 | **Malicious documents** (active PDF content, embedded instructions, secrets) | Type/size allow-list, scan for `/JavaScript`, `/Launch`, `/OpenAction`, injection patterns and credential patterns; flagged docs excluded from retrieval | Add AV scanning (ClamAV) at upload in regulated environments |
| T12 | **Denial of service** / cost abuse | Per-tenant rate limits (Redis or in-memory), monthly workflow/token quotas, per-agent token budgets, tool-call caps, workflow step limits and deadlines, bounded delegation depth, request size limits | Edge WAF / IP throttling |
| T13 | **Duplicate / runaway side effects** (replays, retries, crashes) | Event dedupe keys, `Idempotency-Key`, derived idempotency keys on actions, `in_progress` marker before provider calls, verification instead of blind retry for non-idempotent tools, dead-letter queue, circuit breakers | Live adapters without native idempotency (Slack, SendGrid) rely on verification; review `tool_executions.status = unknown` |
| T14 | **Unsafe automation** (sending, paying, deploying) | Agents only propose; external comms, payables, POs, listing publication, rollbacks require approval; agents literally lack tools to pay or deploy; emergency disable per tenant | Keep `auto_approve` rules narrow; review them in audits |
| T15 | **Supply chain** | Pinned dependencies, `pip-audit`, `bandit`, Trivy image scan in CI, non-root container | Enable Dependabot/Renovate; sign images |
| T16 | **Data retention / privacy** | Tenant `retention_days`; retention job; protected characteristics stripped before scoring; consent checks before outreach | Define lawful basis per channel; DSAR tooling |
| T17 | **SSRF via custom tools** (tenant admin, or a model-chosen input, points a tool at `169.254.169.254`, `localhost`, an internal service, or a host that redirects / DNS-rebinds there) | https only; host resolved before the call and **every** resolved address must be globally routable (loopback, RFC 1918, link-local, CGNAT, multicast, reserved, IPv6 ULA/link-local and IPv4-mapped all refused); redirects disabled; input values are URL-encoded into the template and cannot change scheme/host; response size and timeout capped; tests parametrised over private/metadata addresses | A TOCTOU window remains between the resolution check and the connection (DNS rebinding with TTL 0). In production also route egress through a proxy that enforces the same rule, and keep `CUSTOM_TOOLS_ALLOW_PRIVATE_NETWORK=false` |
| T18 | **Custom tool secrets** leaking | Auth header value Fernet-encrypted, write-only in the API (`has_secret` only), never put in prompts, tool results or audit details | Prefer narrowly-scoped tokens for the target API |
| T19 | **Model-driven tool misuse** in the Copilot (prompt injection in tool results steering the model to call a side-effecting tool) | The model only sees tools the caller's RBAC allows; built-in tools exposed to it are read-only; agents it calls still propose and the policy engine still decides; side-effecting custom tools always require approval bound to the payload hash; iteration and tool-call caps; every call is a persisted, audited step | Approvers must read the exact payload shown, not the Copilot's summary of it |
| T20 | **MCP endpoint abuse** (unauthenticated use, over-scoped keys, DNS rebinding from a browser) | Every tool call authenticates a tenant API key and checks the scope the tool needs; same policy/approval/audit path as the REST API; API keys cannot decide approvals; Host header allow-list (`MCP_ALLOWED_HOSTS`); stateless transport (no session to hijack) | Issue MCP keys with the minimum scopes and an expiry; rotate on staff changes |
| T21 | **Queue poisoning / starvation** (one tenant floods jobs; a poison job crashes workers repeatedly) | Per-tenant concurrency cap on claims, job dedupe keys, bounded attempts with backoff then `dead`, leases so a crashed worker's job is retried elsewhere, workflow run lease so a retried job cannot double-execute a run | Alert on dead jobs and queue depth (`/system/queue`) |

## Abuse cases exercised by tests

`tests/security/test_security.py` covers: cross-tenant reads/writes, forged tokens, unlisted and
side-effecting tool calls from agents, tool-call limits, prompt injection in messages and
transcripts, malicious PDF upload, webhook signature/replay/handshake, secret leakage in API
and audit, privilege escalation, model self-authorisation, security headers and correlation-id
sanitisation. `tests/integration/test_approvals_and_actions.py` covers approval tampering,
expiry, separation of duties, exactly-once execution, reconciliation and duplicate suppression.
`tests/integration/test_copilot_tools_batches_mcp.py` covers SSRF refusals (loopback, RFC 1918,
link-local metadata, CGNAT, IPv6 loopback and ULA, IPv4-mapped IPv6), invalid tool definitions, side-effecting custom tools
requiring approval and executing once, Copilot session privacy and permissions, and MCP calls with
missing, invalid and under-scoped API keys. `tests/integration/test_scale_queue.py` covers
exactly-once job claims under concurrency, tenant caps, lease expiry and the run lease.

## Out of scope / assumptions

* The IdP, network, and cloud account are configured securely.
* LLM providers are trusted with tenant data under contract; use a provider with zero-retention
  terms or self-hosted models for regulated data. The mock provider sends nothing externally.
* Live provider adapters have not been security-reviewed against each vendor's current API
  behaviour in this repository.
