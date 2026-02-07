# Phase 3 Revision 2: Final Determinism and Contract Tightening

## Rationale
Revision 1 fixed most structural issues, but two correctness gaps remain: dependency evaluation is currently performed on an incomplete task set (causing false blocked classification), and plan responses still include non-contract fields that violate the v1 schema. There is also an auth-scope regression that must be restored to preserve Phase 1 guarantees.

## Blocking Findings
- Dependency checks only see open tasks, so dependencies on already-done tasks are treated as unknown/unfinished.
- Plan payload includes `explanation`, which is not allowed by `docs/contracts/plan_response.schema.json` (`additionalProperties: false`).
- Auth identity handling regressed to always returning `usr_dev`, breaking prior multi-user behavior and risking Phase 1 regression.

## Required Changes

### 1) Fix Dependency Evaluation Data Scope
File:
- `backend/common/planner.py`

Requirements:
- `collect_planning_state` must load enough task state to evaluate dependency completion correctly.
- Keep ranking candidates as `status == open` only, but dependency resolution must include referenced non-open tasks.
- Eliminate the current “unknown task => unfinished” false-positive for dependencies that are actually `done`.

Implementation constraint:
- Split into two sets in state:
  - `candidate_tasks` (open tasks only)
  - `task_lookup` or `all_tasks` (for dependency status checks)
- `blocked_items` must be derived deterministically from candidate set + explicit blocked tasks if represented in plan scope.

### 2) Remove Non-Contract Plan Fields
Files:
- `backend/common/planner.py`
- `backend/common/adapter.py`
- `backend/api/schemas.py`

Requirements:
- Returned plan payload must strictly match plan schema fields.
- Remove `explanation` from plan payload/model and from rewrite/fallback steps.
- LLM rewrite may update allowed fields only (`reason`, `why_this_order`, etc.) but must not introduce extras.

### 3) Restore Auth Identity Mapping (Regression Fix)
File:
- `backend/api/main.py`

Requirements:
- Restore token-to-user mapping behavior used previously for scoped idempotency and multi-user tests.
- Minimum expected behavior:
  - known test token maps to `usr_2`
  - default valid token maps to `usr_dev`
- Keep authorization checks otherwise unchanged.

### 4) Add Strict Plan Payload Validation Before Return/Cache
Files:
- `backend/api/main.py`
- `backend/worker/main.py`

Requirements:
- Validate plan payload with `PlanResponseV1` before returning from `GET /v1/plan/get_today` and before caching in worker.
- On invalid plan payload, use deterministic fallback payload that passes schema and log `plan_rewrite_fallback`.

## Acceptance Criteria for Revision 2
1. Dependency checks correctly treat referenced `done` tasks as done (no false blocked classification from missing lookup rows).
2. `GET /v1/plan/get_today` output contains no extra keys outside plan v1 schema.
3. Worker-cached plan snapshots are schema-valid (`PlanResponseV1`) before write.
4. Auth mapping again differentiates at least two users (`usr_dev`, `usr_2`) by token.
5. Compile check passes:
- `python3 -m py_compile backend/api/main.py backend/common/planner.py backend/common/adapter.py backend/worker/main.py`
