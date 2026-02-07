# Phase 3 Revision 1: Contract Compliance and Deterministic Planning Corrections

## Rationale
The current Phase 3 implementation is close structurally but fails the contract layer that keeps planning and query behavior reliable across provider changes. This revision is intentionally narrow: enforce response contracts, restore deterministic planning semantics from spec, and close validation/fallback gaps.

## Blocking Findings Summary
- Plan payload shape does not match `docs/contracts/plan_response.schema.json`.
- Query payload shape does not match `docs/contracts/query_response.schema.json`.
- Provider output is not schema-validated before return.
- Planner logic deviates from required candidate/filter/goal-alignment rules.
- Required observability for `plan`/`query` error paths is incomplete.

## Required Changes

### 1) Plan Response Contract Alignment (Hard Requirement)
Files:
- `backend/common/planner.py`
- `backend/api/schemas.py`
- `backend/api/main.py`
- `backend/worker/main.py`

Make plan output match v1 plan schema exactly:
- Top-level required keys:
  - `schema_version: "plan.v1"`
  - `plan_window: "today"` (for current scope)
  - `generated_at` (ISO datetime)
  - `today_plan` (array of planItem)
  - `next_actions` (array of planItem)
  - `blocked_items` (array of blockedItem)
- Use plan item keys:
  - `task_id`, `rank`, `title`
  - optional `reason`, `score`, `estimated_minutes`
- Use blocked item keys:
  - `task_id`, `title`, `blocked_by` (array of strings)
- Provide `why_this_order` entries with enum-valid factors only.

Current non-compliant keys like `id`, `why`, `reason` (for blocked items), and missing `schema_version`/`plan_window` must be removed/fixed.

### 2) Query Response Contract Alignment + Validation
Files:
- `backend/common/adapter.py`
- `backend/api/schemas.py`
- `backend/api/main.py`

Query response must include required keys:
- `schema_version: "query.v1"`
- `mode: "query"`
- `answer`
- `confidence` (0..1)

Also enforce shape for optional fields:
- `suggested_actions` must be array of objects (not strings) if present.
- `citations` objects must include `entity_type` + `entity_id`.

In `POST /v1/query/ask`:
- Validate provider response shape before returning.
- If invalid, return deterministic fallback query payload and log `query_fallback_used`.

### 3) Deterministic Planning Rule Fixes
File:
- `backend/common/planner.py`

Implement Phase 3 rules exactly:
- Candidate tasks for ranking must be `status == open` only.
- Keep blocked handling rules from spec:
  - explicit blocked status,
  - unfinished `depends_on`,
  - unfinished upstream `blocks`.
- Exclude blocked from `today_plan`; include in `blocked_items` with concrete reasons.
- Goal alignment must include:
  - `supports_goal` links, and
  - task->goal entity links,
  - and only count alignment when target goal is active.
- Apply deterministic tie-break order exactly as spec.
- Remove unused misleading settings/logic or wire them correctly (`PLAN_WEIGHT_BLOCKER_PENALTY`).

### 4) Required Error-path Observability
Files:
- `backend/worker/main.py`
- `backend/api/main.py`

For both `plan` and `query` operations:
- Write `prompt_runs` for success and failure paths (`status="success"|"error"`, `error_code` when error).
- Keep fallback event logs (`plan_rewrite_fallback`, `query_fallback_used`) in fallback paths.

### 5) Cleanup/Regression Safety
File:
- `backend/api/main.py`

- Remove duplicate `GET /v1/memory/context` route definition (retain single canonical handler).
- Ensure existing Phase 1/2 endpoints and behavior remain unchanged.

## Acceptance Criteria for This Revision
1. `GET /v1/plan/get_today` response validates against `docs/contracts/plan_response.schema.json` required structure.
2. `POST /v1/query/ask` response validates against `docs/contracts/query_response.schema.json` required structure.
3. Invalid provider output in plan/query triggers deterministic fallback and corresponding event log entry.
4. Planner ranks only open tasks and routes blocked items to `blocked_items` with `blocked_by` array.
5. Prompt run records exist for both success and error cases of `plan` and `query`.
6. `backend/api/main.py` has no duplicate route declarations for `/v1/memory/context`.
7. Compile check passes:
- `python3 -m py_compile backend/api/main.py backend/api/schemas.py backend/common/planner.py backend/common/adapter.py backend/worker/main.py`
