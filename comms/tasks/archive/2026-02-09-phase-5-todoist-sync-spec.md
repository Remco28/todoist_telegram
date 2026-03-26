# Phase 5 Spec: Todoist Downstream Sync v1

## Rationale
Phase 4 gives us a usable Telegram interface and stable backend structure.  
Phase 5 should push selected local tasks downstream to Todoist with auditable, retry-safe behavior.

## Objective
Implement a one-way sync path (local -> Todoist) that:
1. Creates Todoist tasks for eligible local tasks.
2. Updates existing Todoist tasks when mapped local tasks change.
3. Records sync status, retries, and errors for observability.

## Scope (This Spec Only)
- Mapping/persistence for local task ID to Todoist task ID.
- Worker job handler for `sync.todoist`.
- Minimal Todoist adapter calls for create/update.
- Sync trigger endpoint and status visibility.

Out of scope:
- Two-way sync (Todoist -> local).
- Full conflict merge UI.
- Project/section synchronization beyond basic mapping fields.

## Source-of-Truth Policy (v1)
- Local DB is source of truth for task title/status/priority/due_date.
- Todoist is downstream target only.
- Local `done` maps to Todoist completion call.

## Files and Functions To Modify

### `backend/common/models.py`
Add a new model:
- `TodoistTaskMap`
  - `id`
  - `user_id`
  - `local_task_id` (FK to `tasks.id`)
  - `todoist_task_id`
  - `sync_state` (`pending|synced|error`)
  - `last_synced_at`
  - `last_error`
  - unique index on `(user_id, local_task_id)`
  - unique index on `(user_id, todoist_task_id)`

### `backend/migrations/versions/*`
Add Alembic migration for `todoist_task_map` table and indexes.

### New file: `backend/common/todoist.py`
Create minimal adapter helpers:
- `create_task(payload) -> dict`
- `update_task(todoist_task_id, payload) -> dict`
- `close_task(todoist_task_id) -> dict`
Requirements:
- request timeout
- explicit error handling
- no token leakage in logs

### `backend/worker/main.py`
Implement `topic == "sync.todoist"` handler:
- Fetch eligible tasks (`open|blocked|done` non-archived).
- For unmapped tasks: create in Todoist then insert mapping row.
- For mapped tasks: update/close as needed.
- On failure: write `EventLog` and mapping `sync_state=error`, include retry metadata.

### `backend/api/main.py`
Add sync trigger/status endpoints:
- `POST /v1/sync/todoist` -> enqueue `sync.todoist` job for user/chat scope.
- `GET /v1/sync/todoist/status` -> return recent sync summary and error counts.

## Required Behavior
1. Sync job is idempotent across reruns (no duplicate Todoist tasks for same local task).
2. Failures are retryable; permanent failures are visible in status endpoint.
3. Successful sync updates `last_synced_at` and clears `last_error`.
4. Mapping rows are the sole reference for downstream update/close operations.

## Error Handling Requirements
- Network/provider failures: retry with backoff via existing worker retry logic.
- Validation errors: mark mapping `error` and log deterministic reason.
- Unknown task state: skip and log warning event (no crash).

## Acceptance Criteria
1. New local task syncs to Todoist once and creates stable mapping row.
2. Local task updates propagate to existing mapped Todoist task.
3. Local task marked `done` triggers Todoist close call.
4. Re-running sync on already-synced unchanged tasks is no-op safe.
5. `POST /v1/sync/todoist` enqueues job and returns job id.
6. `GET /v1/sync/todoist/status` returns recent state + error visibility.
7. Compile check passes:
- `python3 -m py_compile backend/api/main.py backend/worker/main.py backend/common/todoist.py backend/common/models.py`

## Developer Handoff Notes
- Keep downstream adapter strict and small; all policy lives in worker.
- Prefer deterministic field mapping over model-generated text.
- Log `IMPL IN_PROGRESS` and `IMPL DONE` in `comms/log.md`.

## Done Criteria
- Acceptance criteria demonstrated in implementation notes.
- Architect review passes.
- This spec is archived to `comms/tasks/archive/`.
