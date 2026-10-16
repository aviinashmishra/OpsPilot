# KPI definitions and ROI calculator

All KPIs are computed deterministically from persisted records. Sources are the
`workflow_runs`, `agent_runs`, `tool_executions`, `approvals`, `usage_records` and
`daily_metrics` tables; the Analytics page (`GET /api/v1/reports`) and the nightly
`compute_daily_metrics` job expose the same definitions.

## Platform KPIs

| KPI | Definition | Source |
|---|---|---|
| Workflow completion rate | `completed ÷ (completed + failed + timed_out + cancelled)` over the period | workflow_runs |
| Agent success rate (by agent / task type) | `(completed + needs_approval) ÷ runs` | agent_runs |
| Input/output validation failures | agent_runs whose `error.code ∈ {validation_failed, agent_output_invalid, llm_output_invalid}` | agent_runs |
| Tool execution failure rate | `(failed + dead_letter) ÷ tool_executions` | tool_executions |
| Duplicate external action rate | side-effect executions that reached the provider twice for one logical action ÷ side-effect executions. Suppressed duplicates (`duplicate_suppressed=true`) are reported separately and count as prevented. | tool_executions |
| Median / p95 latency | per workflow run: `finished_at − started_at`; per agent run: `latency_ms` | workflow_runs, agent_runs |
| Cost per successful workflow | `Σ workflow cost_usd ÷ completed runs` (model cost from provider usage × price table; infra via `roi.infra_cost_per_run_usd`) | workflow_runs |
| Token consumption | `Σ prompt_tokens + completion_tokens` | agent_runs / usage_records |
| Human approval latency | `decided_at − created_at` averaged over decided approvals | approvals |
| Task extraction precision / recall | from evaluation datasets with labelled expectations (`extract` checks) | evaluation_results |
| Time saved vs baseline | `Σ baseline_minutes_saved` of successful agent runs; the baseline is a per-agent **measured** number configured in the catalog (`AgentSpec.baseline_minutes_saved`) — re-measure per tenant | workflow_runs.estimated_minutes_saved |
| User correction rate | `rejected approvals ÷ decided approvals` (+ manual task edits where tracked) | approvals |
| Integration uptime | `1 − (transient/circuit-open failures ÷ calls)` per provider | tool_executions |
| Customer activation / retention | tenants with ≥ 1 completed workflow in their first 14 days; tenants active month-over-month | workflow_runs by tenant |

## ROI model

The platform separates three numbers and never conflates them:

1. **Estimated minutes saved** — `Σ baseline_minutes_saved` over successful runs.
2. **Estimated labour value (USD)** — `minutes_saved ÷ 60 × loaded_hourly_cost_usd`.
3. **Realized savings (USD)** — `estimated_labour_value × realization_rate`, where the
   realization rate is set by finance after verifying that saved time was actually
   converted (headcount avoided, overtime reduced, SLA penalties avoided). It defaults
   to **0**, so no realized savings are claimed until verified.

```
net_estimated_value = estimated_labour_value − ai_cost − infra_cost − platform_fee
payback_months      = platform_fee ÷ max(realized_savings_per_month, ε)
```

### Tenant settings (Admin → Tenant → settings.roi)

| Key | Meaning | Default |
|---|---|---|
| `loaded_hourly_cost_usd` | fully loaded cost of the people whose work is automated | 45 |
| `infra_cost_per_run_usd` | compute/storage/queue cost attributed per workflow run | 0.002 |
| `realization_rate` | finance-verified share of saved time converted into cash savings | 0.0 |
| `monthly_platform_fee_usd` | subscription cost, for payback | 0 |

### Worked example (demo tenant, mock provider)

| Input | Value |
|---|---|
| Successful workflow runs / month | 1,200 |
| Average minutes saved per run | 18 |
| Loaded hourly cost | $48 |
| AI cost per run (real provider, est.) | $0.02 |
| Infra per run | $0.002 |
| Realization rate | 0.5 |

```
minutes_saved     = 1,200 × 18          = 21,600 min  (360 h)
labour_value      = 360 × 48            = $17,280
realized_savings  = 17,280 × 0.5        = $8,640
costs             = 1,200 × (0.02+0.002)= $26.40
net_estimated     = 17,280 − 26.40      ≈ $17,254   (estimate)
```

Only the $8,640 is reportable as savings; the rest is labelled *estimated labour value*.

## Alerting (configurable)

| Alert | Rule | Incident kind |
|---|---|---|
| Failed workflows | any run → `failed`/`timed_out` | `workflow_failed` |
| Abnormal model cost | daily `ai_cost_usd` > 1.5 × 7-day average | `cost_anomaly` (Finance Analyst agent) |
| Repeated integration failures | ≥ 5 consecutive transient failures → circuit open | `integration_failure` |
| Policy violations | denied actions, tampered approvals, SOP violations | `policy_violation` |
| Budget threshold breach | cost centre ≥ 90 % of monthly budget | `cost_anomaly` |
