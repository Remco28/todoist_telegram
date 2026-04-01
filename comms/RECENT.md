# Recent State

This file is the short handoff summary for the latest meaningful project state.

## Current Product Shape
- Local-first Telegram-native assistant
- Postgres source of truth
- `/app` for maintenance only
- Projects, tasks, subtasks, reminders, undo/history all live

## Current Architecture Shape
- Telegram routing is model-first
- Session state is app-owned and persisted
- Grounding uses recent visible context plus entity resolution
- Writes are versioned and undoable through action batches

## Recent Important Changes
- Planner task-id typos are now repaired against grounded task titles before the critic runs. That keeps obvious title/ID mismatches like a one-character `target_task_id` typo from turning into bogus clarification prompts when the intended task is already unambiguous in recent or displayed context.
- Telegram query routing now has a first-class overdue path instead of shoving overdue wording into `due_today` or generic query answers. There is a deterministic `overdue` view for explicit overdue/past-due questions, and the deterministic `due_today` view can now include overdue tasks/reminders when the user explicitly asks for both in one message.
- Task reference resolution now accepts a single strong grounding-only overlap when there is no competing task candidate. This tightens the mixed query+action path for turns like “Do I have any overdue tasks? Also, make the 401k registration high priority.” where the action clause only has one distinctive overlap term (`401k`) and the planner/extractor may still come back empty.
- Telegram now does a bounded second model extraction for clearly multi-line or 3+ segment action messages when planner actions undercount the user's requested changes, and it also does a clause-wise fallback recovery when both planner and extract come back empty for a multi-clause message. That improves multi-action follow-ups like “move wash car to next week” + “delete the Telegram Todo app task” without reverting to heuristic-first intent routing. Delete/archive follow-ups also now recover cleanly from empty extraction, and stale `goal/problem -> create project` planner conversions no longer override archive intent for project-shaped work items.
- Telegram action recovery is now mutation-aware instead of entity-count-aware for bounded supported fields. Priority changes (`high priority`, `urgent`, `low priority`) can now be recovered alongside due-date changes, and the recovery layer no longer treats one partially updated task as “good enough” when a clause asked for multiple field-level mutations.
- Telegram can now handle a bounded mixed turn with one query clause plus one or more action clauses in the same message by answering the query first and then staging the action changes. This is intentionally narrow and does not try to become a general-purpose multi-mode parser.
- Reminder display text in Telegram no longer appends `local`, suppresses duplicate reminder body text, and labels real reminder body text as `Details:` for better readability.
- Explicit app-owned session state was added for follow-up continuity.
- `due_today` is now distinct from the broader `/today` agenda.
- `due_next_week` now has its own deterministic Telegram view instead of falling back to the generic query-answer formatter.
- Telegram due-line indentation now uses real non-breaking spaces, not literal `&nbsp;` text.
- Draft reminder previews now read like human instructions (`Remind me today at 7:00 PM ...`) and the proposal/apply headers are slimmer (`Review changes` / `Done`).
- Planner hierarchy behavior was tightened so deferred parents and unscheduled subtasks behave more sensibly.
- Telegram applied-change acknowledgements now support `Show more` and `Show subtasks`.
- Displayed Telegram ordinal follow-ups now recognize `#<n>` forms like `#4 is done.` against the current `/today` list.
- Explicit `next week` / `next <weekday>` phrases now override incorrect planner due dates in Telegram drafts, so `next Tuesday` resolves to the next calendar week's Tuesday rather than the nearest occurrence.
- Reminder schedule clarification replies now preserve the pending reminder draft, so replies like `Later today` fill `remind_at` on the original reminder instead of drifting into unrelated task updates.
- Reminder schedule clarification replies now also support short relative durations like `in 20 minutes` and `in 2 hours` via bounded local parsing, without depending on the model to restate the reminder correctly.
- The `/app` workbench now has a default `User` mode plus a hidden `Maintenance` mode, collapsible project/task/subtask hierarchy, resilient partial refresh behavior, and a `Load today plan` path that can infer the latest Telegram chat context when no `chat_id` is entered.
- Maintenance API idempotency storage now JSON-encodes route responses, which fixes `/app` status changes that committed successfully but returned `Internal Server Error`.
- Retired `/plan`, `/focus`, and `/ask` command behavior was removed from the live Telegram command path.
- Completed historical specs were archived so `comms/tasks/` only contains the active rebuild spec.

## Current Operational Reality
- Full backend test suite is green at `228 passed, 1 skipped`.
- Redeploy API for Telegram/runtime-only changes.
- Redeploy worker only when background reminder/session summary behavior changes.

## Current Watchouts
- Do not let deterministic rescue logic grow back into heuristic-first interpretation.
- Be careful with hierarchy presentation in Telegram views.
- Keep repo context small; use `project-manifest.md`, `docs/WORKING_SET.md`, and this file before the big log.
