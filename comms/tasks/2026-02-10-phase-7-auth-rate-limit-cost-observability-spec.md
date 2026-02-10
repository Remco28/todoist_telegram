# Phase 7 Spec: Auth, Rate Limits, and Cost Observability v1

## Rationale
Phase 6 made operations observable and recoverable. The next production risk is uncontrolled access and unbounded usage cost. Phase 7 establishes strict request identity, abuse guardrails, and token/cost visibility so the system can scale safely.

## Objective
Implement baseline security and usage governance without changing core product behavior.

## Scope (This Spec Only)
- Explicit token-to-user mapping support.
- Rate limiting for critical API surfaces.
- Prompt token/cost accounting and daily summary endpoint.

Out of scope:
- OAuth/login UI.
- Billing integration with external payment systems.
- Multi-tenant admin dashboards.

## Files and Functions To Modify

### `backend/common/config.py`
Add settings:
- `RATE_LIMIT_WINDOW_SECONDS` (default 60),
- `RATE_LIMIT_CAPTURE_PER_WINDOW` (default 20),
- `RATE_LIMIT_QUERY_PER_WINDOW` (default 30),
- `RATE_LIMIT_PLAN_PER_WINDOW` (default 15),
- `COST_INPUT_PER_MILLION_USD` (default 0.20),
- `COST_CACHED_INPUT_PER_MILLION_USD` (default 0.05),
- `COST_OUTPUT_PER_MILLION_USD` (default 0.50).

### `backend/api/main.py`
1. Auth hardening:
- Extend auth dependency to support explicit env mapping format:
  - `APP_AUTH_TOKEN_USER_MAP="tokenA:usr_dev,tokenB:usr_2"`
- Preserve backward compatibility with current token list.
- Unknown tokens always denied.

2. Rate limiting:
- Add Redis-backed limiter helper keyed by `(user_id, endpoint_class)`.
- Enforce on:
  - `POST /v1/capture/thought` (capture limit),
  - `POST /v1/query/ask` (query limit),
  - `POST /v1/plan/refresh` (plan limit).
- Return `429` with clear message on exceed.

3. Cost summary endpoint:
- Add authenticated `GET /health/costs/daily` returning:
  - day (UTC),
  - totals for input/output tokens,
  - estimated USD cost,
  - breakdown by operation/model.

### `backend/common/adapter.py`
- Ensure adapter responses return token usage metadata when available.
- Keep behavior safe when provider does not return usage fields.

### `backend/tests/`
Add tests for:
- token-to-user auth mapping behavior,
- rate-limit boundary + reset window behavior,
- daily cost aggregation response correctness.

### `docs/EXECUTION_PLAN.md` and `docs/PHASES.md`
- Mark Phase 7 active and track progress notes.

## Required Behavior
1. Every authenticated call resolves to a deterministic `user_id`.
2. Burst traffic above configured thresholds gets `429` without crashing workers.
3. Cost endpoint provides actionable daily usage/cost totals.
4. Existing endpoints remain backward compatible for current single-user setup.

## Acceptance Criteria
1. Auth mapping supports multiple tokens with stable user mapping.
2. Unknown bearer token returns `401`.
3. Capture/query/plan endpoints enforce independent rate limits.
4. Rate-limit counters reset correctly after window elapses.
5. Daily cost endpoint returns valid JSON totals + operation/model breakdown.
6. Compile/lint sanity passes for touched files.
7. Regression tests cover auth + limits + cost calculations.

## Developer Handoff Notes
- Keep implementation minimal and deterministic.
- Do not introduce new infrastructure beyond existing Redis/Postgres.
- Fail closed for auth and fail safe for missing usage metadata.
- Log `IMPL IN_PROGRESS` and `IMPL DONE` in `comms/log.md`.

## Done Criteria
- Acceptance criteria demonstrated in implementation notes and test output.
- Architect review passes.
- Spec archived to `comms/tasks/archive/` after pass.
