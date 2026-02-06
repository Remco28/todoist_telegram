# Phase 1 Revision Spec (Revision 1)

## Rationale
The submitted implementation fails core Phase 1 guarantees (capture reliability, endpoint completeness, idempotent safety, and acceptance gate behavior). This revision isolates the minimum changes required to make the current implementation pass the existing Phase 1 specs and acceptance scenarios.

## Objective
Bring the current `backend/` implementation into compliance with:
- `comms/tasks/2026-02-06-phase-1-implementation-spec.md`
- `comms/tasks/2026-02-06-phase-1-acceptance-test-spec.md`
- `comms/tasks/2026-02-06-phase-1-worker-and-queue-spec.md`

## Files To Modify
- `backend/api/main.py`
- `backend/api/schemas.py`
- `backend/common/adapter.py`
- `backend/worker/main.py`
- `backend/common/models.py` (only if required for correctness)
- `backend/migrations/versions/5638dfedf9dc_initial_schema.py` (only if required for correctness)

## Required Changes

### 1) Fix capture reliability and adapter return contract
- Ensure `LLMAdapter.extract_structured_updates(...)` always returns a dict shape the API can safely consume.
- Add a deterministic fallback response when provider is unavailable.
- In `capture/thought`, fail with spec-compliant `422` on invalid provider output after retry policy.
- Prevent partial writes when extraction/validation fails.

### 2) Fix missing imports/runtime errors in API
- Add all required imports in `backend/api/main.py` so endpoints run without `NameError`:
  - models used by handlers (`Task`, `Goal`, `Problem`, `EntityLink`, `InboxItem`, `EventLog`, `PromptRun`)
  - `adapter`
  - `time`
- Remove unused imports if any.

### 3) Complete required endpoints
- Implement `PATCH /v1/problems/{problem_id}` exactly as allowed fields in spec.
- Keep `GET/PATCH` behavior for tasks/goals/problems consistent.

### 4) Fix task status completion behavior
- Ensure `PATCH /v1/tasks/{task_id}` sets `completed_at` when status becomes `done`.
- Ensure leaving `done` clears `completed_at` (schema integrity rule).
- Handle enum-vs-string comparisons correctly.

### 5) Enforce auth-scoped data access
- Do not trust `payload.user_id` for write authority.
- Use authenticated user identity for all read/write filters and inserts.
- Scope list/update/delete queries to authenticated user.

### 6) Finish capture write coverage for Phase 1
- Implement creation/update handling for goals/problems/links in `capture/thought` (not tasks-only).
- Keep deterministic matching rules from spec (title-normalized exact match behavior).
- Include `no_change` response path when nothing actionable is applied.

### 7) Idempotency behavior compliance
- Preserve current replay behavior for `capture/thought` and ensure same-key same-body returns original response.
- Same key + different body must return `409`.
- For other write endpoints, either:
  - implement full replay persistence, or
  - explicitly scope idempotency middleware to `capture/thought` only for this revision and document this in code comments and log.
- Choose one path and keep behavior consistent.

### 8) Worker retry policy compliance
- Implement retry/backoff for transient failures in worker job processing.
- Add dead-letter behavior after max attempts (can be Redis list-based for now).
- Keep current topic support (`memory.summarize`, `plan.refresh`, `sync.todoist`).

### 9) Acceptance scenario compliance
- Verify and document pass results for all six scenarios in:
  - `comms/tasks/2026-02-06-phase-1-acceptance-test-spec.md`
- Include evidence in `comms/log.md` with `IMPL DONE` summary.

## Constraints
- Do not broaden scope beyond Phase 1.
- Do not add Telegram UX or Todoist sync business logic.
- Keep schema/API contracts aligned with existing Phase 1 specs.

## Expected Behavior After Revision
- `POST /v1/capture/thought` succeeds for valid inputs and is idempotent per spec.
- Invalid provider output fails safely with `422` and no partial write side effects.
- Required CRUD/update/link endpoints exist and are auth-scoped.
- Worker handles retries/backoff/dead-letter for failed jobs.
- All six acceptance scenarios pass in staging.
