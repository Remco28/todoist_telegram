# Phase 3 Revision 3: Final Blocked-Items and Fallback Compliance

## Rationale
Revision 2 resolved major issues, but two behavioral requirements are still not fully satisfied: explicit blocked tasks are not represented in `blocked_items`, and invalid plan validation paths do not use the required fallback event/type flow. This revision is intentionally minimal.

## Remaining Blockers
- Explicit `status=blocked` tasks are not surfaced in `blocked_items`.
- Invalid plan payload handling does not consistently fallback + log `plan_rewrite_fallback` as required.

## Required Changes

### 1) Include Explicitly Blocked Tasks in `blocked_items`
File:
- `backend/common/planner.py`

Requirements:
- Preserve ranking candidates as `status == open`.
- Also include tasks with `status == blocked` in `blocked_items` with a deterministic `blocked_by` reason.
- Keep `today_plan` exclusion behavior unchanged.

Acceptance check:
- A task with `status=blocked` appears in `blocked_items` and never in `today_plan`.

### 2) Enforce Plan Validation Fallback Contract
Files:
- `backend/api/main.py`
- `backend/worker/main.py`

Requirements:
- If plan payload fails `PlanResponseV1` validation:
  - produce deterministic schema-valid fallback payload,
  - log `event_log.event_type = plan_rewrite_fallback` (not a new event type),
  - continue safely (no unhandled validation exception).
- Worker should only cache a validated payload.
- API `GET /v1/plan/get_today` should never return raw invalid plan payload.

Implementation note:
- Keep this narrow. Do not redesign planner shape.

## Acceptance Criteria
1. `status=blocked` tasks are represented in `blocked_items` with non-empty `blocked_by`.
2. Validation failure path in API emits schema-valid fallback response and logs `plan_rewrite_fallback`.
3. Validation failure path in worker emits `plan_rewrite_fallback` and avoids caching invalid payload.
4. Compile check passes:
- `python3 -m py_compile backend/common/planner.py backend/api/main.py backend/worker/main.py`
