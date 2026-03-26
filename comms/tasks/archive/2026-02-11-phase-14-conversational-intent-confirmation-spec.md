# Phase 14 Implementation Spec: Conversational Intent Routing + Confirmation UX

## Context
Current Telegram behavior routes all non-command text into capture/write flow. This causes read-only questions (for example: "what tasks are not completed?") to be misinterpreted as write intent.

## Goal
Make Telegram operate as a true assistant for informal conversation:
- answer questions without writes,
- propose structured actions for actionable thoughts,
- only apply writes and Todoist sync after explicit user confirmation.
- rely primarily on LLM reasoning (planner + critic) instead of phrase-based deterministic intent mapping.

## Scope
- In scope:
  - Telegram intent routing for free-form text (`query` vs `action`).
  - Draft proposal lifecycle with confirmation commands.
  - `/ask` command as optional fallback (not required for normal conversation).
  - Immediate Todoist sync on confirmed action apply.
  - Audit events for proposal/confirmation/apply lifecycle.
- Out of scope:
  - Full natural-language editing UI beyond one-turn `edit` clarification.
  - Multi-user workspace features.

## Functional Contract
1. User sends free text in Telegram.
2. Backend classifies intent:
- `query`: run existing query path and return answer (no writes).
- `action`: build structured proposal (tasks/subtasks/notes/links/dates) with explicit action list.
3. Backend runs critic pass over proposal:
- check duplicates, contradictions, unresolved references, and risky bulk operations.
- if critic rejects, ask user clarification instead of applying.
4. Bot replies with proposal summary and asks:
- `yes` to apply,
- `edit <changes>` to revise,
- `no` to discard.
5. On `yes`:
- apply proposal transactionally,
- enqueue memory summarization,
- enqueue Todoist sync immediately,
- return success summary.
6. On `no`:
- discard draft and return acknowledgement.
7. UX rule:
- User should be able to chat naturally without command prefixes.
- `/ask` exists only as explicit fallback, not primary path.

## Data Model Additions
1. `action_drafts` table (new migration)
- `id` (string PK)
- `user_id` (indexed)
- `chat_id` (indexed)
- `source_inbox_item_id` (nullable FK)
- `status` enum: `draft|confirmed|discarded|expired`
- `proposal_json` (JSON/JSONB)
- `proposal_hash` (idempotency helper)
- `expires_at` (timestamp)
- `created_at`, `updated_at`
2. Optional `draft_events` can remain in `event_log` (no new table required).

## API/Internal Surface Changes
1. Telegram webhook logic
- Add route branch for `/ask <question>` -> `query_ask` flow.
- For non-command text, call new intent classifier operation.
2. Adapter boundary (provider-agnostic)
- Add method: `plan_actions(text, context) -> {intent, scope, actions, confidence, needs_confirmation}`.
- Add method: `critique_actions(text, context, proposal) -> {approved, issues, revised_actions?}`.
- Keep `extract_structured_updates` as compatibility path only during migration.
3. New internal helpers
- `create_action_draft(...)`
- `apply_action_draft(...)`
- `discard_action_draft(...)`
- `get_latest_open_draft(user_id, chat_id)`

## Telegram UX Rules
1. If a draft is open and user sends `yes`, apply it.
2. If a draft is open and user sends `no`, discard it.
3. If a draft is open and user sends `edit ...`, regenerate proposal using edit text + original message context.
4. If no draft is open and user sends `yes/no/edit`, reply with guidance.
5. If confidence is low (`< configurable threshold`), default to proposal flow (never silent write).
6. If planner output is empty/low-confidence, ask one clarification question before fallback heuristics.
7. Phrase-based fallbacks are emergency-only and must emit explicit audit event (`action_fallback_heuristic_used`).

## Sync Policy
- Confirmed actions trigger immediate `sync.todoist` enqueue.
- If sync fails, keep local writes and surface sync failure in response/logs (current system behavior).

## Observability Requirements
Emit `event_log` entries:
- `telegram_intent_classified`
- `telegram_action_planned`
- `telegram_action_critic_result`
- `action_draft_created`
- `action_draft_revised`
- `action_draft_confirmed`
- `action_draft_discarded`
- `action_draft_expired`
- `action_apply_completed`
- `action_apply_failed`

## Tests (Required)
1. Query path from Telegram free text produces answer with zero DB writes.
2. Action path creates draft and does not write tasks before confirmation.
3. `yes` applies draft and enqueues Todoist sync.
4. `no` discards draft and prevents writes.
5. `edit` replaces proposal and keeps single active draft per chat.
6. `/ask` command works even with no active draft (fallback path).
7. Expired draft cannot be applied and returns refresh guidance.
8. Planner+critic path handles broad language (example: "mark everything as done") by proposing scoped actions against grounded open tasks.
9. Heuristic fallback path is only used when planner/critic fail or return empty and is logged.

## Exit Criteria
- Telegram informal Q&A works without accidental writes.
- Action confirmation workflow is stable and auditable.
- Confirmed actions sync to Todoist immediately.
- Full test suite for new behaviors passes in CI/local.
