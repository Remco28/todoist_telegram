# Phase 15A Spec: Sync, Time, and Ops Hardening

## Rationale
Before deeper behavior work, we should remove avoidable operational and correctness risk in existing runtime paths. This gives a stable base for the larger Phase 15B/15C changes.

## Objectives
1. Make Todoist sync incremental instead of full-scan per run.
2. Standardize runtime timestamp generation to one UTC helper.
3. Ensure memory compaction does not delete inbox rows still referenced by open drafts.
4. Add retention safety checks in DB backup cleanup.

## In Scope
- `backend/worker/main.py`
- `backend/api/main.py`
- `ops/backup_db.sh`
- Tests for each changed behavior.

## Out of Scope
- Telegram UX changes.
- Planner prompt redesign.
- Large endpoint refactors.

## Required Changes

### 1) Incremental Todoist Sync
File: `backend/worker/main.py`
- Update `handle_todoist_sync` selection logic so it does not process every non-archived task each run.
- Process only tasks needing sync, derived from:
  - no mapping,
  - mapping exists but `sync_state != "synced"`,
  - local task changed since mapping `last_synced_at`.
- Preserve existing recovery behavior when `todoist_task_id` is null.

Acceptance checks:
- Repeated sync with no local changes should produce near-zero task-level API calls.
- Changed tasks still sync correctly.

### 2) UTC Time Consistency
Files: `backend/worker/main.py`, `backend/api/main.py`
- Replace ad-hoc `datetime.utcnow()` runtime calls with project UTC helper (`utc_now()`) in touched runtime flows.
- Keep timezone-aware comparisons only.
- Do not change DB schema in this step.

Acceptance checks:
- No naive/aware datetime comparison errors in Telegram/token/worker paths.
- Existing tests continue passing.

### 3) Memory Compaction Safety for Draft References
File: `backend/worker/main.py`
- In `handle_memory_compact`, include `ActionDraft.source_inbox_item_id` as a protected reference source.
- Skip deletion of inbox rows referenced by either:
  - `Task.source_inbox_item_id`, or
  - active/recent draft references.

Acceptance checks:
- Compaction never removes an inbox row still referenced by an actionable draft.

### 4) Backup Retention Guardrail
File: `ops/backup_db.sh`
- Before deletion pass, add a sanity guard:
  - verify target directory resolves correctly,
  - verify candidate set is bounded and path-local,
  - skip delete if guard fails.
- Keep existing retention semantics unchanged when guard passes.

Acceptance checks:
- Normal retention still deletes expired backups.
- Misconfigured path does not trigger broad delete.

## Tests Required
1. Add/extend worker tests for incremental sync candidate selection.
2. Add compaction test covering draft-referenced inbox rows.
3. Add backup script safety test (or shell-test style validation) for guard behavior.
4. Run full backend tests after changes.

## Exit Criteria
- Sync no longer full-scans unchanged task sets.
- UTC runtime usage is consistent in modified paths.
- Compaction preserves draft-linked inbox records.
- Backup cleanup has guardrails against unsafe delete scenarios.
