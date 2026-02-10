# Phase 5 Revision 2: Sync Recovery and Test Stability

## Rationale
Revision 1 fixed key items, but acceptance still fails on one correctness bug and one test-harness stability issue. This revision is intentionally narrow and only addresses the remaining blockers.

## Remaining Blockers
- Create-failure mappings with `todoist_task_id = null` are treated as mapped on retry, so sync never re-attempts create.
- New Phase 5 tests are not stable in this environment (fixture setup timeout via async event-loop path).
- Out-of-scope model/migration type churn was introduced and should be reverted for scope control.

## Required Changes

### 1) Fix Retry Recovery for Failed Creates
File:
- `backend/worker/main.py`

Requirements:
- A mapping row is only "mapped" for downstream update/close when `todoist_task_id` is non-null and non-empty.
- If mapping exists but `todoist_task_id` is null (or sentinel pending state), treat it as "needs create" and call `create_task(...)`.
- After successful create:
  - set real `todoist_task_id`,
  - set `sync_state = "synced"`,
  - clear `last_error`,
  - set `last_synced_at` and `last_attempt_at`.
- For local `done` tasks in this recovery path: create then close in same run.

Acceptance check:
- A task that failed initial create (error row with null/pending remote id) successfully recovers on later run and ends `synced` with real remote id.

### 2) Restore Stable Test Design (No Async Fixture Loop Dependency)
Files:
- `backend/tests/conftest.py`
- `backend/tests/test_todoist_sync.py`
- `backend/pyproject.toml`
- `backend/requirements.txt` (only if needed)

Requirements:
- Remove dependence on `pytest_asyncio` async fixtures for Phase 5 tests.
- Match the stable Phase 4 strategy:
  - sync test functions,
  - `asyncio.run(...)` around `httpx.AsyncClient(ASGITransport(...))` calls,
  - avoid event-loop fixture injection.
- Ensure plugin config does not reintroduce loop/plugin conflicts.

Acceptance check:
- `cd backend && pytest -q tests/test_todoist_sync.py` completes without timeout/hang.
- `cd backend && pytest -q` remains green and non-hanging.

### 3) Revert Out-of-Scope Schema Churn
Files:
- `backend/common/models.py`
- `backend/migrations/versions/5638dfedf9dc_initial_schema.py`

Requirements:
- Revert unrelated JSON/JSONB or other broad schema changes introduced in Revision 1 unless directly required for Phase 5 blocker fixes.
- Keep only necessary Phase 5 schema updates:
  - `todoist_task_map` fields needed for sync/status,
  - migration(s) for those fields.

Acceptance check:
- Diff scope is limited to Phase 5 sync behavior, status fields, and test stability changes.

## Test Coverage Requirements
Ensure tests explicitly cover:
1. failed-create mapping recovery on next run (null/pending remote id -> create success),
2. recovery path for `done` task does create+close,
3. status endpoint reflects recovery transition from error to synced.

## Acceptance Criteria
1. Failed-create rows recover to synced on retry (no permanent "update with null remote id" failure loop).
2. Phase 5 tests run reliably in this environment with no event-loop fixture hang.
3. Full suite remains passing.
4. Compile check passes:
- `python3 -m py_compile backend/worker/main.py backend/api/main.py backend/common/models.py`

## Done Criteria
- Acceptance criteria demonstrated in implementation notes and local test output.
- Architect review passes.
- This revision spec is archived to `comms/tasks/archive/` after pass.
