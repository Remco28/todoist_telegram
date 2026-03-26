# Local-First Telegram Rebuild Spec

Date: 2026-03-25
Owner: Architect
Status: Ready

## Objective
Rebuild the product around a local-first, Telegram-native execution system with a lightweight web UI and no dependency on Todoist.

## Product Definition
The app is a personal operating system for one user:
- Telegram is the primary interface.
- A small web UI supports editing, cleanup, browsing, and undo.
- Postgres is the source of truth.
- The model interprets conversational input.
- The backend validates, writes, versions, and logs.

## Core Product Behaviors
- Natural conversational capture and updates in Telegram.
- Read-only questions answered from local structured state.
- Confirmation-first writes for ambiguous or meaningful changes.
- Projects, tasks, and subtasks with shallow hierarchy.
- Explicit reminder support.
- Daily planning and urgent views.
- Explicit subtask generation when the user asks for it.
- Action history and undo.

## Non-Goals
- Todoist sync or reconciliation.
- Collaboration features.
- Heavy dashboard product.
- Deep workflow-automation marketplace.

## Target Data Model
### Primary entity
- `work_items`
  - `kind`: `project | task | subtask`
  - `parent_id`
  - `title`, `notes`
  - `status`
  - `priority`
  - `due_at`
  - `scheduled_for`
  - `snooze_until`
  - `estimated_minutes`
  - `area_id`
  - timestamps

### Supporting entities
- `work_item_aliases`
- `work_item_links`
- `people`
- `areas`
- `reminders`
- `plan_snapshots`
- `recent_context_items`
- `conversation_events`
- `action_batches`
- `work_item_versions`

## Migration Strategy
1. Introduce the new schema alongside the legacy schema.
2. Map legacy `tasks`, `goals`, and `problems` into `work_items`.
3. Move Telegram write/query/plan logic onto the new schema.
4. Add the lightweight web UI over the new model.
5. Remove Todoist and the legacy schema paths once the new path is stable.

## Implementation Workstreams
### Workstream A: Schema and History
- Add `work_items` and supporting tables.
- Add action batches and versioning first, before broad write-path migration.

### Workstream B: Telegram Runtime
- Move conversational writes to `work_items`.
- Keep model-first routing.
- Use bounded candidate resolution and clarification flow.

### Workstream C: Planner and Reminders
- Rebuild `/today` and `/urgent`.
- Add reminder scheduler and delivery.
- Add plan snapshots and daily brief flow.

### Workstream D: Web UI
- Browse hierarchy.
- Edit work item fields.
- Review action history.
- Undo recent changes.

### Workstream E: Cleanup
- Remove Todoist worker paths.
- Remove legacy schema/runtime paths.
- Remove docs and ops assumptions that only exist for Todoist.

## Acceptance Criteria
- Local DB is the only source of truth.
- Telegram is sufficient for normal daily use.
- Web UI is sufficient for review/edit/cleanup/undo.
- Projects/tasks/subtasks work cleanly.
- Subtask generation is explicit, not automatic default behavior.
- Reminders and planning are local.
- Every confirmed write is versioned and reversible.
- Todoist is no longer part of runtime behavior or core docs.

## Notes
- The current v1 implementation was useful to validate Telegram-first behavior, confirmation UX, and planning concepts.
- This rework intentionally keeps those strengths while removing the architectural constraints that came from treating Todoist as a product dependency.
