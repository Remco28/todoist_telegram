# Phase 6 Spec: Hardening and Scale Readiness v1

## Rationale
Phases 1-5 delivered core product behavior (capture, memory, planning, Telegram, Todoist sync).  
Phase 6 should make the system operationally reliable on VPS production by improving observability, failure visibility, and recovery posture.

## Objective
Implement baseline production hardening so we can detect, diagnose, and recover from failures quickly without changing product behavior.

## Scope (This Spec Only)
- Metrics and health visibility for API and worker.
- Structured operational event logging for critical jobs.
- Backup/restore runbook + executable backup script.
- Production guardrails for job retries and dead-letter handling visibility.

Out of scope:
- New user-facing product features.
- Multi-region deployment.
- Full BI dashboard stack.

## Files and Functions To Modify

### `backend/api/main.py`
Add lightweight operational endpoints:
- `GET /health/metrics`:
  - queue depth snapshot,
  - recent failure counters,
  - last successful run timestamps for key job topics (`memory.summarize`, `plan.refresh`, `sync.todoist`).
- Keep auth requirement (same bearer scheme).

### `backend/worker/main.py`
Enhance observability and failure signaling:
- Emit deterministic `EventLog` entries for:
  - retry scheduled,
  - moved to DLQ,
  - successful topic completion summary.
- Include minimal metadata:
  - `topic`, `job_id`, `attempt`, `max_attempts`, `queue`.

### `backend/common/config.py`
Add hardening settings with safe defaults:
- `OPERATIONS_METRICS_WINDOW_HOURS` (default 24),
- `WORKER_ALERT_FAILURE_THRESHOLD` (default 5),
- `BACKUP_RETENTION_DAYS` (default 14).

### New file: `ops/backup_db.sh`
Provide project-local backup script:
- Dumps DB (or sqlite file copy in local mode) to `ops/backups/`.
- Timestamped filename.
- Retention cleanup based on `BACKUP_RETENTION_DAYS`.
- Non-destructive and safe shell behavior (`set -euo pipefail`).

### New file: `ops/RESTORE_RUNBOOK.md`
Document restore drill steps:
- Preconditions,
- restore command sequence,
- verification checklist,
- rollback notes.

### `docs/README.md` and `docs/EXECUTION_PLAN.md`
Update status and Phase 6 progress notes.

## Required Behavior
1. Operations endpoint returns valid JSON with key operational indicators.
2. Worker emits explicit retry and DLQ events for failing jobs.
3. Backup script can be run manually without external/global setup.
4. Restore runbook is clear enough for a first-time operator.

## Acceptance Criteria
1. `GET /health/metrics` returns:
- queue depth,
- retry/DLQ counters for last window,
- last-success timestamps per core topic.
2. When a job fails and retries, `event_log` contains a retry event with metadata.
3. When max attempts exceeded, `event_log` contains DLQ event with metadata.
4. `ops/backup_db.sh` runs successfully in local dev and creates timestamped backup artifact.
5. Backup retention cleanup removes expired files only.
6. Docs updated to mark Phase 6 in progress.
7. Compile/lint sanity passes:
- `python3 -m py_compile backend/api/main.py backend/worker/main.py backend/common/config.py`

## Developer Handoff Notes
- Keep this phase operationally focused; avoid product-surface expansion.
- Favor deterministic, parseable event payloads.
- All operational artifacts must stay project-local (no global CLI assumptions).
- Log `IMPL IN_PROGRESS` and `IMPL DONE` in `comms/log.md`.

## Done Criteria
- Acceptance criteria demonstrated in implementation notes and command output.
- Architect review passes.
- Spec archived to `comms/tasks/archive/` after pass.
