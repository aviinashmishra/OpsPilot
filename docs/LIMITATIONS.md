# Known limitations and production prerequisites

This file is the honest ledger of what is implemented, what is sandboxed, and what you must do
before trusting OpsPilot with real customers.

## Implemented and tested
- 25 agents with typed contracts, deterministic cores, model-assisted extraction/narrative, evaluation datasets (all passing on the mock provider).
- Orchestrator: graph execution, checkpoints, resume after crash, parallel branches, bounded delegation, cancellation, retry, dead letters, incidents.
- Policy engine, approval service (hash-bound, SoD, expiry, exactly-once), action executor with idempotency and reconciliation.
- Multi-tenancy, RBAC, API keys, local JWT, OIDC verification code path, rate limits, quotas, audit hash chain, retention.
- 13 sandbox adapters, 7 live adapters (unit-tested with mocked HTTP), signed webhooks, WhatsApp handshake.
- REST API, Alembic migrations (SQLite + PostgreSQL with RLS), Docker/Compose, CI, dashboard.
- Ops Copilot: bounded tool-use loop over the 25 agents, 27 read tools, platform operations and tenant custom tools; persisted live steps. Tested with a scripted fake Claude client (request shape, parallel results, errors, budgets) and with the offline planner end to end.
- Custom HTTP tools with SSRF guard, encrypted secrets and approval-gated side effects; MCP server (Streamable HTTP) with API-key scopes.
- Durable job queue (leases, retries, dead jobs, dedupe, tenant caps), separate worker processes (`WORKER_MODE=db`), workflow run leases, bulk agent runs; measured with real processes (docs/DEPLOYMENT.md → Scale benchmark).

## Sandbox / mock by default
- `LLM_PROVIDER=mock`: every model call runs the agent's deterministic heuristic. Quality with a real model will differ; the evaluation harness exists precisely to measure that before rollout.
- All integrations start in sandbox mode on synthetic tenant data. The dashboard labels this explicitly. No message, ticket, PO or payment ever leaves the system in sandbox mode.

## Not yet production-grade
| Area | Status | What to do |
|---|---|---|
| Live adapters | Implemented against documented APIs; **never run against real accounts here** | Validate each with vendor sandbox credentials; add contract tests |
| Accounting / procurement / Google Workspace / Datadog live adapters | Not implemented (sandbox only) | Implement per `integrations/live.py` pattern |
| Embeddings / pgvector | Column + extension wired; embedding provider not called | Add an embedding call in `services/retrieval.index_document` |
| OCR / document AI | Minimal PDF text extraction | Plug a document-AI provider into `services/documents.extract_text` |
| OIDC | Verification implemented; not exercised against a real IdP in tests | Test with your IdP; disable password login |
| Agent timeouts | Enforced via token/tool-call budgets and workflow deadlines, not a hard per-agent wall clock | Run agents under Celery time limits (`task_time_limit`) |
| Rate limiting | In-memory per process unless `REDIS_URL` set | Use Redis in production |
| Live Claude path | Request shape, tool-loop handling and error mapping are unit-tested against a fake client; **no call to the real Anthropic API was made in this repository** (no key) | Set `LLM_PROVIDER=anthropic` + key, run `python -m app.cli evaluate` and a few Copilot sessions, compare with the mock baseline |
| Live Gemini path | `GeminiProvider` (google-genai SDK): request shape, history conversion both ways (function calls/responses, thought signatures), structured output, error and safety mapping are unit-tested against a fake client; **no call to the real Gemini API was made in this repository** (no key). A Copilot session started on Claude and continued on Gemini (or back) is converted best-effort: Claude thinking blocks are dropped, and Gemini's `thought_signature` field is not stripped before replay to Claude | Set `LLM_PROVIDER=gemini`, `GEMINI_API_KEY` and Gemini model ids, run `python -m app.cli evaluate` and a few Copilot sessions; start new Copilot sessions after switching provider |
| Neon | All migrations (through `c7d1e2f3a4b5`) applied to a Neon PostgreSQL 18 database via the direct endpoint, pgvector enabled. The test suite and benchmark were not run against Neon; the pooled (`-pooler`) endpoint is supported in code (no startup options, no prepared statements) but untested | Prefer the direct endpoint; run the suite with `TEST_DATABASE_URL` on a separate empty Neon branch |
| PostgreSQL | Full test suite (236), migrations up/down/check and the multi-process benchmark were run on a local PostgreSQL 16 (via `pgserver`, no Docker). Not run: Docker Compose stack, managed PostgreSQL, pgvector-enabled schema, the least-privilege `opspilot_app` role | CI runs all of it on `pgvector/pgvector:pg16`; run as `opspilot_app` before go-live |
| Load testing | Single-machine benchmark with the mock LLM (docs/DEPLOYMENT.md); one unexplained ~35 min worker stall in one early PostgreSQL run (now guarded by `lock_timeout`) | Repeat on your infrastructure; real LLM latency will dominate |
| Custom tools DNS rebinding | Addresses are checked before the call; a TTL-0 rebind between check and connect is not prevented in-process | Enforce egress through a proxy with the same allow rule |
| Pricing table | Default per-token prices in `llm/gateway.py` | Override to match your contract |
| Frontend tests | Lint + type-check + build + Playwright journeys (`e2e/`) against a running local stack | Run them in CI against the Compose stack |
| Minutes-saved baselines | Per-agent defaults in `AgentSpec.baseline_minutes_saved` | Measure per tenant; realization rate set by finance |

## Operational caveats
- Thread worker mode is single-node; use `WORKER_MODE=db` (runner processes on any number of machines, same PostgreSQL) or Celery for multi-node.
- SQLite serialises writes: extra worker processes add little throughput there (see the benchmark). The horizontal-scale path is PostgreSQL.
- `inline` worker mode (tests) executes workflows synchronously inside the request.
- SQLite is for development/tests only (no RLS, limited concurrency).
