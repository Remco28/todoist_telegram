# Phase 17 Spec: Telegram UX Clarity and Operator QoL

## Objective
Improve the product quality-of-life gaps that make the system harder to trust or operate, without changing the planner/executor safety model or adding a new client surface.

## Rationale
The current backend already knows more than the UI exposes. The main failure mode is not missing data, but lossy presentation:
1. The Telegram draft preview hides the exact operation behind bare titles.
2. The command UX asks users for identifiers the UI does not naturally expose.
3. Operational status endpoints answer "how many failed" but not "what failed."

The simplest durable fix is to expose existing structured information more faithfully:
- show exact verbs and field deltas in Telegram,
- let commands operate on what the user can already see,
- return actionable status detail instead of raw counters alone.

## Scope

### 1) Make Draft Preview and Apply Ack Explicit
- File(s):
  - `backend/api/main.py`
  - `backend/common/telegram.py`
  - `backend/tests/test_telegram_webhook.py`
  - `backend/tests/test_telegram_formatting.py`
- Required behavior:
  - `_format_action_draft_preview` must stop rendering a flat `Tasks` list.
  - Group task proposals by action:
    - `Create new task`
    - `Update existing task`
    - `Mark complete`
    - `Archive`
  - Preserve separate sections for goals/problems/links only when they are present.
  - Each task row must use action-led wording; bare title alone is not sufficient.
  - For update actions, include only the concrete fields that will change when present:
    - status
    - due date
    - notes
    - priority
    - impact score
    - urgency score
  - If `target_task_id` is present, the wording must make clear that this is a mutation of an existing task rather than a create.
  - Replace the count-only success acknowledgement with an itemized applied summary, capped to a reasonable Telegram-safe size (for example first 6 named changes plus overflow count).
  - Keep HTML-safe formatting and the existing Yes/Edit/No inline keyboard.
- UX guardrails:
  - Never render a completion or update intent as a create-sounding bare reminder title.
  - Do not show raw internal ids in normal preview/apply text unless needed for explicit user guidance.
- Acceptance checks:
  - A mixed create/update/complete extraction preview is clearly grouped by action.
  - Post-apply acknowledgement names changed tasks instead of only returning totals.
  - Existing callback/button flow remains unchanged.

### 2) Make `/plan`, `/today`, and `/focus` Truthful and Fresh
- File(s):
  - `backend/common/telegram.py`
  - `backend/api/main.py`
  - `backend/tests/test_telegram_webhook.py`
  - `backend/tests/test_telegram_formatting.py`
- Required behavior:
  - `format_plan_refresh_ack` must not promise a push update unless one is actually implemented in this slice.
  - Add a freshness line to `/today` and `/focus` output using `generated_at` from the plan payload.
  - The freshness cue may be relative or absolute, but it must be concise and human-readable in Telegram.
  - Preserve compact mobile formatting; do not turn plan views into long prose.
- Decision:
  - Do not add asynchronous Telegram completion push in this slice.
  - Change the `/plan` acknowledgement copy to match actual behavior.
- Acceptance checks:
  - `/plan` response is truthful.
  - `/today` and `/focus` show how current the rendered plan is.
  - Existing plan/query behavior does not regress.

### 3) Make `/done` Operable From Visible Context
- File(s):
  - `backend/api/main.py`
  - `README.md`
  - `backend/tests/test_telegram_webhook.py`
- Required behavior:
  - Keep existing `/done <task_id>` support.
  - Add `/done <number>` support where the number is a 1-based ordinal into the most recent task list surfaced to that chat by `/today` or `/focus`.
  - `/today` and `/focus` must persist the displayed task ids in display order using the existing recent-context mechanism.
  - On ordinal completion success, respond with the resolved task title, not only the id.
  - On invalid or out-of-range ordinals, return clear guidance and do not mutate anything.
- Guardrails:
  - Do not add fuzzy title matching in this slice.
  - Only ordinals grounded in recently surfaced task context may resolve implicitly.
- Acceptance checks:
  - `/done 2` after `/focus` completes the second shown task.
  - `/done 99` returns guidance and performs no mutation.
  - `/done tsk_123` remains supported.

### 4) Make Todoist Status and Metrics Actionable
- File(s):
  - `backend/api/main.py`
  - `backend/api/schemas.py`
  - `backend/tests/test_todoist_sync.py`
- Required behavior:
  - Extend `TodoistSyncStatusResponse` with a bounded `recent_errors` list (cap 5).
  - Each recent error item must include enough context to act:
    - event type
    - local task id
    - remote Todoist id when present
    - short reason/error
    - occurred-at timestamp
  - Populate from recent sync/reconcile failure events:
    - `todoist_sync_task_failed`
    - `todoist_reconcile_task_failed`
    - `todoist_reconcile_remote_missing`
  - Keep all existing aggregate fields.
  - Add `sync.todoist.reconcile` to `health/metrics` tracked topics.
- Acceptance checks:
  - Status endpoint remains backward-compatible for current fields.
  - When failures exist, status response includes recent actionable examples instead of only counts.
  - Health metrics expose reconcile last-success visibility.

## Out of Scope
- New browser UI or non-Telegram client surface.
- Fuzzy task-title completion commands.
- Planner/extractor behavior redesign.
- Queue architecture rewrite.
- Full module decomposition of `backend/api/main.py` in this slice.

## Implementation Order
1. Draft preview and apply acknowledgement clarity.
2. `/plan` truthful copy and `/today`/`/focus` freshness line.
3. recent-context persistence for `/today` and `/focus`, then `/done <number>`.
4. Todoist status/metrics enrichment.
5. README command doc update and regression pass.

## Test Plan
- Formatter tests for:
  - grouped draft preview,
  - itemized apply acknowledgement,
  - freshness line rendering.
- Webhook/command tests for:
  - `/done` by ordinal after `/focus`,
  - invalid ordinal no-op,
  - truthful `/plan` acknowledgement text,
  - mixed create/update/complete preview rendering.
- Sync status tests for:
  - recent error serialization,
  - reconcile visibility in health metrics.

## Definition of Done
- A user can tell exactly what a pending Telegram proposal will do before tapping Yes.
- A user can complete a just-shown task without knowing an internal task id.
- `/plan` copy matches real behavior.
- Todoist status answers "what failed" in addition to "how many failed."
- `README.md` reflects the updated Telegram command behavior.
- `comms/log.md` updated with `SPEC READY`.
