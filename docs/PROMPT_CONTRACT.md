# Prompt Contract

## Purpose
Keep model behavior consistent, auditable, and token-efficient while the product shifts to a local-first `work_item` model.

## Contract Layers
1. System policy
2. Operation prompt
3. Retrieved context
4. User input

## Operation Types
- `telegram_turn`: classify the current conversational turn
- `action_plan`: convert conversational input into structured proposed actions
- `action_critic`: review proposed actions for safety and quality
- `query`: answer a read-only question from current stored state
- `plan`: generate or rewrite planning output
- `summarize`: compress recent activity into durable memory

Optional future operation:
- `subtask_suggest`: suggest subtasks for an explicitly requested parent item

## Core Output Expectations
### `telegram_turn`
- Must classify:
- `smalltalk`
- `query`
- `action`
- `confirmation`
- `clarification_answer`
- `unknown`
- May include deterministic view requests like `today`, `urgent`, or `open_items`
- May include draft actions like `confirm`, `discard`, or `edit`

### `action_plan`
- Must return strict JSON
- Must use structured actions against the local domain model
- Must prefer existing candidate ids supplied by the backend when referencing existing work items
- Must avoid inventing arbitrary ids
- Must prefer the `tasks[]` payload with `kind=project|task|subtask` for normal work-item writes
- If the user describes a goal or problem, it should normally be modeled as a `project` work item, not a separate durable entity type
- May create:
- projects
- tasks
- subtasks
- reminders
- links

### `action_critic`
- Must catch:
- missing targets
- contradictory updates
- overly broad writes
- duplicate children/subtasks
- poor quality decomposition

### `subtask_suggest`
- Must only be used when the user explicitly asks for task breakdown
- Must prefer concrete, user-informed subtasks over generic filler
- Must keep suggestions compact and actionable

## Local-First Rules
- The model interprets semantics; the backend validates and writes.
- The model never emits raw SQL or direct DB instructions.
- The model should choose existing ids only from backend-provided candidate sets.
- If the target is ambiguous, the model should ask for clarification rather than guessing.
- Subtasks are explicit, not automatic default behavior.
- The prompt contract should assume a unified `work_item` model, not separate task/goal/problem products.

## Validation and Retry
- Parse and validate outputs against schema.
- Retry once or twice when the model returns malformed JSON.
- If still invalid, fail safely and log it.
- Fallback behavior may recover from formatting/schema problems only.
- Fallback behavior must not recreate phrase-based mutating intent logic.
- If a rescue path is needed for production reliability, keep it grounded in explicit visible context or deterministic normalization, not general language understanding.

## Versioning
- Every prompt template has a `prompt_version`
- Persist:
- provider
- model
- prompt version
- token usage
- latency
- status

## Cost and Efficiency Controls
- Keep the system policy compact and stable.
- Prefer bounded context over transcript replay.
- Include only relevant work items, aliases, reminders, people, areas, and recent context.
- Let deterministic code handle validation, persistence, and history creation.
- Use model calls for interpretation, decomposition, planning, and ambiguity handling.
