# Phase 2 Revision Spec (Revision 1)

## Rationale
The current Phase 2 implementation is close but fails core contract points: deterministic function structure, context ordering/proximity behavior, hard budget guarantees, and compaction safety. This revision is limited to those blockers.

## Objective
Make Phase 2 Memory Engine pass Architect review by fixing six identified gaps only.

## Sources of Truth
- `comms/tasks/2026-02-06-phase-2-memory-engine-spec.md`

## Files To Modify
- `backend/common/memory.py`
- `backend/worker/main.py`
- `backend/api/main.py` (only if endpoint wiring needed for new function interface)
- Optional: migration/model changes only if strictly needed for safe compaction policy

## Required Fixes

### 1) Compaction FK safety (critical)
- Update `memory.compact` logic to avoid deleting `inbox_items` that are referenced by `tasks.source_inbox_item_id`.
- Minimum acceptable approach:
  - delete only inbox rows older than retention cutoff **and** not referenced by any task.
- Log compaction stats with separate counts:
  - `eligible_old_rows`
  - `deleted_rows`
  - `skipped_referenced_rows`

### 2) Implement required deterministic memory function structure
In `backend/common/memory.py`, implement and use these functions explicitly:
- `select_hot_turns(...)`
- `select_warm_summaries(...)`
- `select_related_entities(...)`
- `enforce_budget(...)`
- `assemble_context(...)`

`assemble_context` must orchestrate these helpers (not inline all logic).

### 3) Enforce spec context order exactly
Build context in this order:
1. system policy
2. latest summary
3. hot turns
4. related entities
5. current query

Ensure returned `context` preserves this order.

### 4) Add link proximity to related-entity selection
`select_related_entities(...)` must consider link proximity, not recency-only.
Minimum acceptable v1 logic:
- start with recent tasks matching recency window,
- include directly linked goals/problems via `entity_links`,
- then fill remaining slots by recency.

### 5) Enforce hard budget guarantee
`enforce_budget(...)` must guarantee returned payload does not exceed `applied` budget.
If `policy + query` alone exceed budget:
- truncate query text deterministically to fit,
- keep policy present,
- set metadata flag like `budget_truncated_core=true`.

### 6) Compaction scoping clarity
Support explicit compaction scope in payload:
- if `payload.user_id` provided: compact for that user only
- else: global compaction (current behavior)
Include scope details in compaction event payload.

## Acceptance Criteria
1. `memory.compact` no longer risks FK violation with task-linked inbox rows.
2. `backend/common/memory.py` contains and uses all required helper functions.
3. Context ordering matches spec exactly.
4. Related entities include link-proximate records.
5. `estimated_used <= applied` always holds, including pathological long-query cases.
6. Compaction event log includes scope + detailed counters.
7. No regressions to existing Phase 1 endpoints.

## Evidence Required in `comms/log.md`
- one example where old referenced inbox row is skipped safely,
- one example context response proving order and budget compliance,
- one example showing linked entity inclusion,
- one compile check command result.

## Done Criteria
- All acceptance criteria pass.
- Architect review passes.
- This revision spec is moved to `comms/tasks/archive/`.
