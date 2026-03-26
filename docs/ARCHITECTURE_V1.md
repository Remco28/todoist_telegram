# Architecture

Note: the file path is legacy. The contents now describe the current local-first rework target.

## High-Level Components
- Telegram bot service
- Core API service
- Planner / reminder / memory worker
- Postgres
- Redis (optional but recommended for queueing, scheduling, and transient caches)
- Lightweight web UI
- LLM provider adapter layer

## Product North Star
The system should feel like a conversational executive assistant with a real memory and a real local state model, not like a Telegram front-end for another task manager.

## Product Surfaces
- Telegram: primary user interface.
- Web UI: secondary maintenance interface.
- Background worker: reminders, planning refresh, summarization, cleanup jobs.

## Core Interaction Contract
1. User sends natural language in Telegram.
2. Model interprets the turn:
- small talk
- query
- action
- confirmation
- clarification answer
3. Backend loads recent visible context, relevant work items, aliases, reminders, and pending draft state.
4. Backend asks the model for structured output, bounded by backend-provided context.
5. Backend validates the proposal.
6. If a write is ambiguous or risky, backend asks one concrete clarification question.
7. If a write is clear enough, backend shows a proposal and waits for confirmation.
8. Backend writes transactionally and records a reversible action batch.
9. Worker updates plan snapshots, reminders, and memory summaries.

## Core Domain Model
The central entity should be a unified `work_item`.

### `work_items`
- `id`
- `user_id`
- `kind`: `project | task | subtask`
- `parent_id`
- `title`
- `title_norm`
- `notes`
- `status`
- `priority`
- `due_at`
- `scheduled_for`
- `snooze_until`
- `estimated_minutes`
- `area_id`
- `owner_person_id` or linked people through join table
- `created_at`
- `updated_at`
- `completed_at`
- `archived_at`

### Hierarchy Rules
- Projects can have child tasks.
- Tasks can have child subtasks.
- Subtasks do not have children.
- Promotion is allowed:
- a `task` can become a `project`
- existing children can then attach under it

## Supporting Tables
### `work_item_aliases`
- Stores alternate user-facing references for matching and grounding.
- Examples:
- `the backpack thing`
- `register one`
- `Patrick payroll follow-up`

### `work_item_links`
- Typed relationships between work items.
- Examples:
- `blocks`
- `depends_on`
- `related_to`
- `part_of`

### `people`
- Named humans frequently referenced in tasks.
- Allows stronger grounding for follow-ups like "waiting on Patrick".

### `areas`
- Stable life/work buckets like `home`, `work`, `finance`, `health`.

### `reminders`
- Explicit reminder schedule separate from due dates.
- Supports nudges like:
- "remind me tomorrow at 9"
- "check next week if Patrick replied"

### `recent_context_items`
- Short-lived record of what the assistant recently showed or discussed.
- Important for:
- "that one"
- "the first task"
- "the register one"

### `plan_snapshots`
- Stored outputs of planner runs.
- Useful for:
- `/today`
- `/urgent`
- daily brief messages
- debugging plan quality over time

### `conversation_events`
- Raw Telegram/API messages plus metadata.
- Used for audit and memory summarization.

### `action_batches`
- Every confirmed write grouped into a batch.
- Stores:
- user message
- structured proposal
- applied entity ids
- before/after summary
- undo eligibility

### `work_item_versions`
- Append-only history of item changes.
- Supports:
- inspection
- rollback
- debugging bad model behavior

## Why This Model Helps The AI
The database should give the model more handles, not more mystery.

Useful structure:
- aliases
- hierarchy
- people
- areas
- reminders
- recent visibility
- version history

That means the model can reason against:
- exact work item ids
- parent/child relationships
- "things involving Patrick"
- "items in finance"
- "the project with the dinner subtasks"

instead of only fuzzy title text.

## Target Resolution Strategy
Intent interpretation is model-first.
Target resolution remains backend-supervised.

Recommended pattern:
1. Backend prepares a bounded candidate set of existing work items.
2. Model may return:
- a direct candidate id from that set
- or a clarification request
3. Backend rejects ids outside the allowed candidate set.
4. Backend applies writes only after schema and policy validation.

This gives the model semantic flexibility without giving it unlimited authority over the database.

## Heuristic Drift Guardrail
Small deterministic rescue paths are acceptable only when they are:
- grounded in explicit visible context
- limited to safe target recovery or date normalization
- easy to inspect and remove later

They are not acceptable as a replacement for model interpretation.

That means:
- do not rebuild broad phrase-based intent routing in code
- do not keep adding English-only command synonyms as the primary fix for conversation bugs
- prefer improving prompts, grounding, session state, and candidate sets first
- keep deterministic code focused on validation, grounding, normalization, and writes

## Write Pipeline
1. Store raw message in `conversation_events`.
2. Build grounding:
- relevant work items
- aliases
- recent visible items
- linked people and areas
- pending draft state
3. Call turn interpreter.
4. If write intent, call planner / structured action generator.
5. Validate action payload.
6. Resolve or confirm target ids from bounded candidates.
7. Create draft proposal.
8. On confirmation:
- write `work_items`
- write `work_item_versions`
- write `action_batches`
- update reminders / plan state
9. Emit audit log events.

## Subtask Generation
Subtask generation is explicit, not automatic by default.

Supported behavior:
- user creates or updates a parent item
- user explicitly asks:
- "create subtasks"
- "break this into subtasks"
- "turn this into a checklist"
- backend asks model for child suggestions
- backend shows parent + proposed children in one review draft

Rule:
- no silent auto-decomposition of tasks into subtasks

## Planner and Reminder Engine
The planner is local and works from `work_items`, reminders, and recent context.

Planner outputs:
- `today`
- `urgent`
- blocked items
- waiting-on items
- daily brief
- weekly review

Reminder engine responsibilities:
- due reminders
- scheduled reminders
- follow-up reminders
- recurring review prompts

## Telegram Command Philosophy
Commands are optional shortcuts, not the main UX.

Visible menu should stay minimal:
- `/today`
- `/urgent`
- `/start` if still needed for linking

Everything else should work conversationally.

## Web UI Scope
The web UI is not the main product.
It exists to support:
- browsing projects/tasks/subtasks
- editing structured fields
- cleaning up duplicates
- inspecting action history
- undoing recent changes
- reviewing reminders and plan snapshots

It should not become a heavy productivity dashboard.

## Reliability and Recovery
- Postgres is the durable source of truth.
- Every write should produce an action batch and version history.
- Archive over delete where possible.
- Undo should be a first-class operator feature.
- Backups are mandatory.
- Restore drills are mandatory.
- Reminders and plans should be rebuildable from core state.

## Todoist
Todoist is not part of the target architecture.

During transition:
- legacy Todoist code may remain in the repo temporarily
- it should be treated as deprecated
- new product design should not depend on it

## Migration Direction
1. Introduce unified `work_items` and supporting tables.
2. Move Telegram query/write/planning flows onto the new model.
3. Add web UI over the new schema.
4. Export any legacy rows worth keeping, then discard the old maintenance surface.
5. Remove Todoist sync/reconcile and legacy runtime/schema dependencies.
