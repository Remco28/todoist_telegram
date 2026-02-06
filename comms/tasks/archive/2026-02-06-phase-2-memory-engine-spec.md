# Phase 2 Spec: Memory Engine v1 (Summaries + Context Assembly)

## Rationale
The core truth is simple: the system can only reason well if it can retrieve the right context in a bounded token budget. Phase 1 gave us durable state capture; Phase 2 must convert that state into reliable, compact, and auditable memory for read/query and future planning. This is the minimum step that unlocks higher-quality answers without transcript bloat.

## Objective
Implement a deterministic memory context builder and summary refresh pipeline that:
1. Produces durable session summaries.
2. Assembles token-bounded context for query operations.
3. Preserves provenance from summaries back to source records.

## User Stories
- As the user, when I ask a question about my projects/tasks, the system should answer using recent and relevant memory instead of replaying full chat history.
- As the user, when memory is summarized, I need confidence the summary can be traced back to actual source events.
- As the operator, I need strict token-budget controls to keep costs predictable.

## Scope (This Spec Only)
- Memory summary generation hardening.
- Context assembly service for query mode.
- Retention/compaction jobs for raw transcript windows.
- New read-only endpoint for context preview/testing.

Out of scope:
- Telegram UX changes.
- Todoist sync changes.
- Full planning engine scoring/ranking.

## Files and Functions To Modify

### `backend/common/models.py`
- Ensure `memory_summaries.facts_json` and `memory_summaries.source_event_ids` are used consistently.
- Add model(s) only if needed for transcript compaction metadata.

### `backend/worker/main.py`
- Extend `memory.summarize` job to:
  - include source `event_log` IDs in `source_event_ids`.
  - write structured facts into `facts_json`.
- Add new topic handler: `memory.compact`.

### `backend/common/config.py`
Add settings:
- `MEMORY_CONTEXT_MAX_TOKENS` (default `3000`)
- `MEMORY_HOT_TURNS_LIMIT` (default `8`)
- `MEMORY_RELATED_ENTITIES_LIMIT` (default `25`)
- `TRANSCRIPT_RETENTION_DAYS` (default `30`)

### `backend/api/main.py`
- Add read-only endpoint: `GET /v1/memory/context`.
- Endpoint params:
  - `chat_id` (required)
  - `query` (required)
  - `max_tokens` (optional, capped by config)
- Return composed context envelope (for verification/observability).

### New file: `backend/common/memory.py`
Implement core deterministic functions:
- `assemble_context(user_id: str, chat_id: str, query: str, max_tokens: int) -> dict`
- `select_hot_turns(...)`
- `select_warm_summaries(...)`
- `select_related_entities(...)`
- `enforce_budget(...)`

## Required Behavior

### 1) Summary Provenance
For every `memory.summarize` completion:
- `memory_summaries.summary_text` must be written.
- `memory_summaries.facts_json` must contain extracted facts array/object.
- `memory_summaries.source_event_ids` must contain event IDs used as source.
- `event_log` entry `memory_summary_created` must include summary ID + source count.

### 2) Context Assembly Algorithm (Deterministic First)
`assemble_context` must build context in this order:
1. System memory policy snippet (fixed).
2. Most recent session summary for `user_id + chat_id`.
3. Hot turns from latest inbox window (bounded by `MEMORY_HOT_TURNS_LIMIT`).
4. Related entities (tasks/goals/problems) by recency + link proximity.
5. Current user query.

Then enforce budget:
- Keep policy + query always.
- Trim hot turns first.
- Trim related entities next.
- Never exceed `max_tokens` after trimming.

### 3) Token Budget Estimation
Use deterministic approximate estimator (character/word heuristic is acceptable in this phase). Do not call LLM just for counting.

### 4) Retention and Compaction
Add `memory.compact` worker behavior:
- Identify `inbox_items` older than `TRANSCRIPT_RETENTION_DAYS`.
- Retain structured entities and summaries.
- Remove or archive old raw turns according to existing DB policy.
- Write compaction stats to `event_log`.

### 5) Read-Only Context Preview Endpoint
`GET /v1/memory/context` returns:
- `budget`: `{requested, applied, estimated_used}`
- `sources`: counts by layer (`hot_turns`, `summaries`, `entities`)
- `context`: assembled payload (safe to inspect)
No writes beyond optional observability log entry.

## Pseudocode (Core)
```text
assemble_context(user_id, chat_id, query, max_tokens):
  cfg_max = min(max_tokens, MEMORY_CONTEXT_MAX_TOKENS)
  policy = fixed_policy_snippet()
  summary = latest_summary(user_id, chat_id)
  hot = select_hot_turns(user_id, chat_id, MEMORY_HOT_TURNS_LIMIT)
  entities = select_related_entities(user_id, query, MEMORY_RELATED_ENTITIES_LIMIT)

  draft = [policy, summary, hot, entities, query]
  while estimate_tokens(draft) > cfg_max:
    if hot not empty: trim hot oldest-first
    elif entities not empty: trim entities lowest-relevance-first
    else: break

  return envelope(draft, budget_meta, source_counts)
```

## Acceptance Criteria
1. `memory.summarize` writes `summary_text`, `facts_json`, and `source_event_ids`.
2. `GET /v1/memory/context` responds with bounded context and budget metadata.
3. Returned `estimated_used <= applied budget` in normal conditions.
4. Compaction job logs a `memory_compaction_completed` event with counts.
5. No existing Phase 1 endpoint behavior regresses.

## Developer Handoff Notes
- Keep this phase deterministic-first; LLM generation remains in summarization only.
- Avoid schema churn unless absolutely required.
- If new migration is required, include one migration file and update Alembic cleanly.

## Done Criteria
- All acceptance criteria above are demonstrated in `comms/log.md` with `IMPL DONE` evidence.
- Architect review passes and this spec is moved to `comms/tasks/archive/`.
