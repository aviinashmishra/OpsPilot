# Agent Evaluation Report

> Copy this template for each evaluation cycle. Numbers come from `python -m app.cli evaluate`
> (stored in `evaluation_results`) and from the Analytics page (`GET /api/v1/reports`).
> Never report estimates as measurements; label every number with its source.

| Field | Value |
|---|---|
| Agent | `<agent_key>` — `<Agent name>` v`<version>` |
| Dataset | `<dataset name>` v`<n>` (`<N>` synthetic cases) |
| Model / provider | `<model id>` via `<provider>` (or `mock-heuristic`) |
| Policy version | `<POLICY_VERSION>` |
| Evaluated by / date | `<name>` — `<YYYY-MM-DD>` |
| Environment | `<commit sha>` · `<APP_ENV>` |

## 1. Summary

One paragraph: what changed since the last cycle, the headline metrics, and the go/no-go recommendation.

## 2. Quality metrics (from `evaluation_results.metrics`)

| Metric | Value | Target | Status |
|---|---|---|---|
| Case accuracy (`passed / cases`) | | ≥ 0.95 | |
| Extraction precision | | ≥ 0.85 | |
| Extraction recall | | ≥ 0.85 | |
| Classification accuracy (if applicable) | | ≥ 0.90 | |
| Evidence citation correctness (sampled, manual) | | ≥ 0.95 | |
| Unsupported-claim rate | | ≤ 0.02 | |
| Human intervention rate | | per agent target | |
| p50 / p95 latency (ms) | | per agent budget | |
| Cost per case (USD) | | per agent budget | |

**Evidence citation correctness** is scored manually on a random sample of ≥ 20 outputs:
a citation is correct when the cited ref exists *and* supports the claim it is attached to.

## 3. Failure analysis

| Case | Check | Expected | Actual | Root cause | Fix / follow-up |
|---|---|---|---|---|---|
| | | | | | |

## 4. Safety checks

- [ ] Prompt-injection cases handled (content treated as data, no policy/tool override)
- [ ] No protected characteristics used in scoring or inference
- [ ] No fabricated references (URLs/emails/numbers) in outputs
- [ ] All side-effecting actions were *proposed*, none executed directly
- [ ] Approval-gated actions reached the approval center with bound payload hash

## 5. Production signals (last 30 days, from Analytics)

| Signal | Value |
|---|---|
| Runs / success rate | |
| Human intervention rate | |
| User correction rate (approvals rejected ÷ requested) | |
| Cost per successful run | |
| Estimated minutes saved (baseline × successful runs) | |

## 6. Decision

- [ ] Promote version `<x.y.z>` to all tenants
- [ ] Promote to pilot tenants only: `<list>`
- [ ] Hold — blocking issues: `<list>`

Signed off by: `<name, role>`
