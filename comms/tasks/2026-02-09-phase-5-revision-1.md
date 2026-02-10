# Phase 5 Revision 1: Todoist Sync Correctness and Visibility

## Rationale
Phase 5 v1 is close, but it fails acceptance on core sync correctness and observability details. This revision is intentionally narrow and addresses only the blockers from architect review.

## Blockers To Fix
- Todoist update path assumes JSON response and fails on valid `204 No Content`.
- Unmapped create failures are not reflected in sync status visibility.
- `done` tasks without existing mapping are created but not closed in same sync run.
- Failure events do not include retry metadata.
- No Phase 5 tests validate required behaviors.

## Required Changes

### 1) Handle Todoist 204 Responses Safely
File:
- `backend/common/todoist.py`

Requirements:
- `update_task(...)` must not unconditionally call `resp.json()`.
- Treat `200/201` with JSON body as parsed dict.
- Treat `204` as success with deterministic return (for example `{}`).
- Keep timeout and token-safe error handling.

Acceptance check:
- A mocked `204` update response does not raise decode errors and sync marks mapping as `synced`.

### 2) Make Create-Failure Visibility Deterministic
Files:
- `backend/common/models.py`
- `backend/migrations/versions/*`
- `backend/worker/main.py`
- `backend/api/main.py`

Requirements:
- Add `last_attempt_at` to `todoist_task_map` so failures without remote ID are visible.
- For unmapped task create failure, create or upsert a map row with:
  - `todoist_task_id` placeholder sentinel (deterministic, e.g. `pending:<local_task_id>`),
  - `sync_state = "error"`,
  - `last_error`,
  - `last_attempt_at`.
- Keep `(user_id, local_task_id)` unique as identity anchor.
- Status endpoint must surface these error rows in `error_count`.

Implementation note:
- If you prefer avoiding sentinel remote IDs, add a nullable remote ID migration and keep uniqueness semantics safe. Either approach is acceptable, but status visibility must be correct.

Acceptance check:
- When create fails for a new task, `/v1/sync/todoist/status` increments `error_count` and includes updated sync timing metadata.

### 3) Enforce Source-of-Truth for Unmapped `done` Tasks
File:
- `backend/worker/main.py`

Requirements:
- If local task is `done` and has no mapping:
  1. create remote task,
  2. insert mapping,
  3. close remote task in same run.
- Clear `last_error` and update sync timestamps on success.

Acceptance check:
- Unmapped `done` task results in both create and close calls, with mapping ending in `synced`.

### 4) Add Retry Metadata to Failure Events
File:
- `backend/worker/main.py`

Requirements:
- `todoist_sync_task_failed` event payload must include retry context fields:
  - `job_id`,
  - `attempt`,
  - `max_attempts`,
  - `will_retry` (boolean),
  - `next_retry_delay_seconds` (or `null` when none).
- Keep deterministic error reason field.

Acceptance check:
- Failure EventLog rows include retry metadata fields above.

### 5) Add Phase 5 Tests
Files:
- `backend/tests/test_todoist_sync.py` (new)
- Optional fixture updates in `backend/tests/conftest.py`

Required test coverage:
1. New unmapped open task -> create called once, mapping inserted `synced`.
2. Existing mapped task update -> update called, mapping remains `synced`.
3. Unmapped `done` task -> create then close in same run.
4. Todoist update returns `204` -> treated as success.
5. Create failure for unmapped task -> mapping reflected as `error`, status endpoint shows error.
6. Failure event payload includes retry metadata keys.
7. `POST /v1/sync/todoist` enqueues `sync.todoist` and returns `job_id`.
8. `GET /v1/sync/todoist/status` returns consistent totals for mapped/pending/error.

Implementation note:
- Mock Todoist adapter methods; do not make network calls in tests.

## Acceptance Criteria
1. No JSON decode failure on Todoist `204` update responses.
2. Create failures for previously unmapped tasks are visible in sync status.
3. Unmapped `done` tasks are closed remotely in same sync run.
4. Failure events include retry metadata fields.
5. New Phase 5 tests pass locally.
6. Compile check passes:
- `python3 -m py_compile backend/common/todoist.py backend/worker/main.py backend/api/main.py backend/common/models.py`

## Done Criteria
- All acceptance criteria demonstrated in implementation notes and test output.
- Architect review passes.
- This revision spec is archived to `comms/tasks/archive/` after pass.
