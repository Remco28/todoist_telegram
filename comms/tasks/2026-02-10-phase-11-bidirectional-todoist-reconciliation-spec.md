# Phase 11 Spec: Bidirectional Todoist Reconciliation v1

## Rationale
Phase 5 created reliable downstream sync (local -> Todoist), but remote-side edits can still drift from local state. The simplest durable fix is to add a deterministic pull/reconcile path that updates local records from Todoist using existing mapping rows and explicit conflict rules.

## Objective
Implement bidirectional synchronization by reconciling Todoist remote changes back into local task state with deterministic, auditable behavior.

## Scope (This Spec Only)
- Add Todoist pull adapter methods.
- Add reconciliation worker topic and handler.
- Add API trigger endpoint for reconciliation.
- Add deterministic conflict policy for status/title/notes/priority/due_date.
- Add reconciliation observability events and status visibility.

Out of scope:
- New UI surfaces.
- Multi-user collaboration model changes.
- Replacing local source-of-truth policy.

## Conflict Policy (Authoritative Rules)
Use mapping table (`todoist_task_map`) as join key.

1. Completion (`done`) state:
- If Todoist task is completed/closed, local task must be set to `done`.
- If local is already `done`, no-op.

2. Archived/deleted remote tasks:
- If remote task is not found for a mapped `todoist_task_id`, mark mapping `sync_state="error"` and emit drift event.
- Do not auto-delete local task in v1.

3. Mutable fields for open tasks (`title`, `notes`, `priority`, `due_date`):
- If local task is `done`, ignore remote field edits.
- Otherwise apply remote fields to local when different, set `updated_at`, and emit reconciliation event.

4. Local-only tasks (no mapping):
- Reconciliation job does not create local tasks from arbitrary remote tasks in v1.
- Reconcile only mapped tasks for deterministic safety.

## Files and Functions To Modify

### `backend/common/todoist.py`
Add remote read methods:
- `get_task(todoist_task_id: str) -> Optional[Dict[str, Any]]`
- `list_tasks() -> List[Dict[str, Any]]` (optional for future, required only if needed by implementation)

Behavior:
- Return `None` for 404 on `get_task` (do not raise for not-found).
- Raise for non-404 non-2xx errors.

### `backend/common/config.py`
Add reconciliation settings:
- `TODOIST_RECONCILE_BATCH_SIZE` (default `200`)
- `TODOIST_RECONCILE_WINDOW_MINUTES` (default `60`)

### `backend/worker/main.py`
Add new topic support:
- `sync.todoist.reconcile`

Add handler:
- `handle_todoist_reconcile(job_id: str, payload: dict, job_data: dict)`

Required behavior:
1. Load mapped rows for `user_id` in bounded batches.
2. For each mapping with non-null remote id, fetch remote task via adapter.
3. Apply conflict policy above to local task row.
4. Update `TodoistTaskMap` metadata:
- `last_attempt_at` always.
- `last_synced_at` on successful remote read/apply.
- `sync_state` to `synced` on success, `error` on failed reconcile.
- `last_error` populated on failure.
5. Emit `EventLog` records:
- `todoist_reconcile_applied`
- `todoist_reconcile_remote_missing`
- `todoist_reconcile_task_failed`
- `todoist_reconcile_completed`
6. If any row fails, raise at end to preserve existing worker retry semantics.

### `backend/api/main.py`
Add endpoint:
- `POST /v1/sync/todoist/reconcile`

Behavior:
- Auth + idempotency required (same pattern as sync trigger endpoint).
- Enqueue job topic `sync.todoist.reconcile` with `user_id`.
- Return `{status:"ok", enqueued:true, job_id:"..."}`.

Extend existing status endpoint:
- `GET /v1/sync/todoist/status`
- Include reconciliation metadata fields:
  - `last_reconcile_at`
  - `reconcile_error_count`

### `backend/api/schemas.py`
Extend `TodoistSyncStatusResponse` to include:
- `last_reconcile_at: Optional[str]`
- `reconcile_error_count: int`

### `backend/tests/test_todoist_sync.py`
Extend tests:
1. Reconcile applies remote completion to local task.
2. Reconcile updates mutable open-task fields from remote.
3. Reconcile handles remote missing task deterministically (mapping error + event).
4. Reconcile endpoint enqueues `sync.todoist.reconcile`.
5. Status endpoint includes new reconcile fields.

### `docs/ARCHITECTURE_V1.md`
Update sync section to include pull/reconcile loop and deterministic conflict rules.

### `docs/PHASES.md` and `docs/EXECUTION_PLAN.md`
Update status after spec publish:
- Mark Phase 10 complete.
- Mark Phase 11 in progress.
- Update immediate next session plan for reconciliation implementation.

## Required Behavior
1. Remote Todoist changes for mapped tasks are reconciled locally with deterministic policy.
2. Reconciliation is auditable (events + status fields).
3. Existing downstream sync remains intact.

## Acceptance Criteria
1. New reconcile job topic and handler implemented and reachable from API trigger.
2. Reconcile policy is deterministic and covered by tests for done/mutable/missing cases.
3. Reconcile failures are visible via mapping/error fields and EventLog entries.
4. `GET /v1/sync/todoist/status` exposes reconciliation indicators.
5. Full backend test suite remains green.

## Implementation Handoff Packet
- Implement in this order: adapter reads -> worker reconcile handler -> API trigger/status fields -> tests -> docs.
- Keep reconciliation strictly mapping-based in v1 (no free import of unmatched remote tasks).
- Reuse existing worker retry/DLQ semantics; do not add a second retry framework.
- Log `IMPL IN_PROGRESS` and `IMPL DONE` in `comms/log.md`.

## Done Criteria
- Acceptance criteria demonstrated with test output.
- Architect review passes.
- Spec archived to `comms/tasks/archive/` after pass.
