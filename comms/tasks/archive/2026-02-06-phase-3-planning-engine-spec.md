# Phase 3 Spec: Planning Refresh Engine v1

## Rationale
The next irreducible requirement is prioritization. We already capture state (Phase 1) and retrieve bounded memory (Phase 2); now we need a deterministic planner that turns stored tasks into a reliable execution order, then uses the model only for language quality and explanations. This keeps control in backend logic while still giving natural responses.

## Objective
Implement Phase 3 planning + query read path:
1. Deterministic, dependency-aware task scoring and ranking.
2. `plan.refresh` and `plan.get_today` API surface.
3. LLM rewrite/explanation stage over deterministic plan data.
4. Read-only query endpoint using Phase 2 context assembly.

## Scope (This Spec Only)
- Planning algorithm and blocked-task handling.
- Plan refresh worker implementation.
- API endpoints for planning and query mode.
- Validation/fallback behavior for provider outputs.

Out of scope:
- Telegram bot UX.
- Todoist sync.
- Multi-user tenancy redesign beyond current auth/user_id model.

## Files and Functions To Modify

### `backend/common/config.py`
Add planning/query settings with safe defaults:
- `PLAN_TOP_N_TODAY` (default `6`)
- `PLAN_TOP_N_NEXT` (default `8`)
- `PLAN_WEIGHT_URGENCY` (default `4.0`)
- `PLAN_WEIGHT_IMPACT` (default `3.0`)
- `PLAN_WEIGHT_GOAL_ALIGNMENT` (default `2.0`)
- `PLAN_WEIGHT_STALENESS` (default `1.0`)
- `PLAN_WEIGHT_BLOCKER_PENALTY` (default `6.0`)
- `QUERY_MAX_TOKENS` (default `2000`)

### New file: `backend/common/planner.py`
Implement deterministic planner helpers:
- `collect_planning_state(db, user_id) -> dict`
- `detect_blocked_tasks(tasks, links) -> (ready_ids, blocked_map)`
- `score_task(task, features, weights, now) -> (score: float, factors: list[str])`
- `build_plan_payload(state, now) -> dict` (shape aligned with `docs/contracts/plan_response.schema.json`)
- `render_fallback_plan_explanation(plan_payload) -> dict`

### `backend/common/adapter.py`
Add/complete methods:
- `rewrite_plan(plan_state: dict) -> dict`
- `answer_query(query: str, retrieved_context: dict) -> dict`

Requirements:
- Return contract-safe dicts.
- If provider call fails or response shape is invalid, return deterministic fallback payload.

### `backend/worker/main.py`
Implement `plan.refresh` topic handler:
- Build deterministic plan payload.
- Call `adapter.rewrite_plan(...)` for optional language layer.
- Persist observability (`prompt_runs`, `event_log`) and write Redis cache key for latest plan snapshot:
  - key: `plan:today:{user_id}:{chat_id}`
  - TTL: 24h

### `backend/api/schemas.py`
Add request/response models:
- `PlanRefreshRequest(chat_id: str, window: str = "today")`
- `PlanRefreshResponse(status, enqueued, reason, job_id)`
- `PlanTodayResponse` aligned with plan response contract.
- `QueryAskRequest(chat_id: str, query: str, max_tokens: Optional[int])`
- `QueryAskResponse` aligned with query response contract.

### `backend/api/main.py`
Add endpoints:
- `POST /v1/plan/refresh` (auth required, idempotency required)
- `GET /v1/plan/get_today` (auth required, read-only)
- `POST /v1/query/ask` (auth required, read-only semantics)

Use current queue mechanism for refresh. `get_today` should:
1. Read cached plan snapshot from Redis.
2. If absent, compute deterministic plan inline and return it.

`query/ask` should:
1. Build context via `assemble_context(...)`.
2. Call `adapter.answer_query(...)`.
3. Validate response shape; fallback if invalid.
4. Must not mutate `tasks`, `goals`, `problems`, `entity_links`, or `inbox_items`.

## Deterministic Planning Rules (Required)
1. Candidate tasks: `status = open` only.
2. Blocked if:
- task status is `blocked`, or
- has `depends_on` link to a task not `done`, or
- is target of a `blocks` link from a task not `done`.
3. Blocked tasks are excluded from `today_plan` and included in `blocked_items` with reasons.
4. Rank order is deterministic from DB state + fixed `now`.
- Tie-break order: higher score, earlier due date, newer priority (1 highest), older `updated_at`, lexical `task.id`.
5. `today_plan` limited by `PLAN_TOP_N_TODAY`; `next_actions` limited by `PLAN_TOP_N_NEXT`.

## Scoring Inputs (Required)
Use weighted sum of normalized features:
- Urgency: overdue/due soon boost.
- Impact: `impact_score` if present.
- Goal alignment: task has link to active goal (`supports_goal` or task->goal entity link).
- Staleness: older `updated_at` gets modest boost.
- Blocker penalty: applied before blocked exclusion for rationale consistency.

Return `why_this_order` factors per task from this enum set:
- `overdue`, `due_soon`, `high_impact`, `goal_alignment`, `dependency_ready`, `stale`, `quick_win`

## Query Mode Rules (Required)
- Query endpoint is read-only for structured business tables.
- Provider output is treated as answer text, not DB instructions.
- Include citations when available (`entity_type`, `entity_id`).
- Optional suggested actions may be returned as hints only; no implicit writes.

## Validation and Fallback Requirements
- Validate plan and query payloads against expected required fields before returning.
- On invalid provider output, return deterministic fallback plus `event_log` entry (`plan_rewrite_fallback` or `query_fallback_used`).
- Log `prompt_runs` for `plan` and `query` operations with status success/error.

## Acceptance Criteria
1. `POST /v1/plan/refresh` enqueues `plan.refresh` and returns job metadata.
2. `GET /v1/plan/get_today` returns deterministic plan payload matching v1 contract shape.
3. Repeated `get_today` calls with unchanged DB state return same ordering.
4. Blocked tasks are not in `today_plan` and appear in `blocked_items` with reason strings.
5. `POST /v1/query/ask` returns query payload without mutating core entity tables.
6. Provider failure/invalid output triggers fallback response and audit events.
7. Existing Phase 1 and Phase 2 behaviors remain non-regressed.

## Developer Handoff Notes
- Keep deterministic planner as source of truth; LLM rewrite is optional layer.
- Avoid migration churn in this phase unless strictly required.
- If adding helper functions, keep them pure and unit-testable.
- Record `IMPL IN_PROGRESS` and `IMPL DONE` in `comms/log.md`.

## Done Criteria
- All acceptance criteria demonstrated with endpoint-level evidence.
- Architect review passes.
- This spec is archived to `comms/tasks/archive/`.
