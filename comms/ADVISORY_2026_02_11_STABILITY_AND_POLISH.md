# ADVISORY NOTES: Stability and Polish (Phase 14+)
**Date:** 2026-02-11
**Role:** TECHADVISOR

## Overview
The system is in production and functioning well across 14 phases of development. This review focuses on reducing technical debt, improving operational efficiency, and polishing existing components for long-term maintainability.

## Findings & Recommendations

### 1. Todoist Sync Efficiency (Performance)
- **Finding:** `handle_todoist_sync` in `worker/main.py` currently fetches and iterates over *all* non-archived tasks for a user on every sync trigger. As the number of tasks grows, this will become increasingly slow and expensive in terms of DB and API IO.
- **Action:** Update the sync query to only fetch tasks where `updated_at > last_synced_at` (using a join or subquery with `TodoistTaskMap`). This ensures we only process changed items.

### 2. Telegram Webhook Complexity (Maintainability)
- **Finding:** `telegram_webhook` in `api/main.py` has grown into a "God function" (~600 lines) handling callback queries, command routing, and complex natural language draft/confirm flows.
- **Action:** Refactor the webhook into a routing layer that delegates to specific handlers (e.g., `handle_callback_query`, `handle_message`, `handle_draft_interaction`). This will improve readability and make it easier to test individual components.

### 3. Redundant Heuristics (Efficiency)
- **Finding:** There is significant overlap between the `action_plan` LLM operation and manual heuristics like `_resolve_completion_actions` and `_derive_bulk_complete_actions`. 
- **Action:** As the planner's quality matures, we should consolidate these. Move towards the planner being the source of truth for "intent", and use deterministic code primarily for validation and transactional execution.

### 4. Code Consistency (Polish)
- **Finding:** Inconsistent use of `datetime.utcnow()` vs. `utc_now()` and `datetime.now(timezone.utc)`. 
- **Action:** Standardize on a single utility for getting current UTC time (e.g., the `utc_now()` helper already present in some files).

### 5. Memory Compaction Safety (Reliability)
- **Finding:** `handle_memory_compact` skips `inbox_items` referenced by `Task`, but does not explicitly check `ActionDraft` references. While drafts are short-lived, a long-running compaction job could theoretically collide with a very recent draft.
- **Action:** Add a check for `ActionDraft` references in the compaction logic, or simply rely on the fact that `TRANSCRIPT_RETENTION_DAYS` (30) is vastly larger than the draft TTL (30 mins).

## Next Steps
I will begin implementing some of these "polish" items, starting with the Todoist sync optimization and the consistent timestamping.
