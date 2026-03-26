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
- Explicit app-owned session state was added for follow-up continuity.
- `due_today` is now distinct from the broader `/today` agenda.
- `due_next_week` now has its own deterministic Telegram view instead of falling back to the generic query-answer formatter.
- Planner hierarchy behavior was tightened so deferred parents and unscheduled subtasks behave more sensibly.
- Telegram applied-change acknowledgements now support `Show more` and `Show subtasks`.
- Maintenance API idempotency storage now JSON-encodes route responses, which fixes `/app` status changes that committed successfully but returned `Internal Server Error`.
- Retired `/plan`, `/focus`, and `/ask` command behavior was removed from the live Telegram command path.
- Completed historical specs were archived so `comms/tasks/` only contains the active rebuild spec.

## Current Operational Reality
- Full backend test suite was green at the last cleanup pass.
- Redeploy API for Telegram/runtime-only changes.
- Redeploy worker only when background reminder/session summary behavior changes.

## Current Watchouts
- Do not let deterministic rescue logic grow back into heuristic-first interpretation.
- Be careful with hierarchy presentation in Telegram views.
- Keep repo context small; use `project-manifest.md`, `docs/WORKING_SET.md`, and this file before the big log.
