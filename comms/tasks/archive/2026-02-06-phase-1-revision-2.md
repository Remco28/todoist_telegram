# Phase 1 Revision Spec (Revision 2)

## Rationale
Revision 1 resolved several critical issues, but a few contract-breaking gaps remain. This revision is intentionally narrow: close only the remaining blockers required to pass the current Phase 1 acceptance gate.

## Objective
Resolve all remaining Phase 1 compliance failures identified in Architect review, without expanding scope.

## Sources of Truth
- `comms/tasks/2026-02-06-phase-1-implementation-spec.md`
- `comms/tasks/2026-02-06-phase-1-acceptance-test-spec.md`
- `comms/tasks/2026-02-06-phase-1-revision-1.md`

## Files To Modify
- `backend/api/main.py`
- `backend/api/schemas.py`
- `backend/common/adapter.py` (only if needed for validation/retry behavior)
- Optional test files if present/added for acceptance evidence

## Required Changes

### 1) Implement links handling in `capture/thought`
- Replace the placeholder at `backend/api/main.py` around links handling with real processing logic.
- Consume `extraction["links"]` and create valid `entity_links` rows.
- Increment `applied.links_created` correctly.
- Enforce user scoping and link enum validation.

### 2) Complete write-endpoint idempotency
- Add idempotency support to `DELETE /v1/links/{link_id}`.
- Ensure same key + same request returns original response body.
- Ensure same key + different body returns `409`.
- Keep behavior consistent with other write endpoints.

### 3) Enforce invalid provider output contract (validate + retry + 422)
- In `capture/thought`, validate extraction output shape before applying writes.
- Add retry loop for invalid output (at least 2 attempts total).
- On repeated invalid output, return `422`.
- Log prompt run failures appropriately.

### 4) Remove partial-write behavior on extraction failure
- Ensure extraction failure path does not commit partial business state from the same capture request.
- Keep failure handling auditable, but make capture transaction safe and atomic with respect to inbox/entity mutations.

### 5) Align request schema with auth ownership model
- Remove `user_id` from capture request body in `backend/api/schemas.py`.
- Use authenticated user identity only.
- Ensure endpoint implementation and docs/comments match this behavior.

### 6) Close remaining `GET /v1/tasks` contract gaps
- Add support for:
  - `goal_id` filter
  - `cursor` pagination primitive (simple opaque/id-based is acceptable)
  - `limit` max enforcement at 200
- Keep existing status filtering.

## Acceptance Requirements (Must Provide Evidence)
- Scenario 1: capture creates structured data including links when provided.
- Scenario 2: idempotency replay works on all write endpoints, including delete link.
- Scenario 3: invalid provider output returns `422` after retry, with no partial entity writes.
- Scenario 4: task update done-state logic still passes (`completed_at` set/cleared correctly).
- Scenario 5: auth remains enforced.
- Scenario 6: summary job still enqueues and worker processes/retries as designed.

## Constraints
- No Telegram features.
- No Todoist sync business logic.
- No architecture rewrite.
- Keep changes minimal and localized to pass gate.

## Done Criteria
- All above required changes implemented.
- No new regressions in previously fixed areas.
- `comms/log.md` includes `IMPL DONE` with explicit evidence summary for all six scenarios.
