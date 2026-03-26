# Resume Guide

Use this when a new AI instance or developer needs to resume work quickly without loading the full repository history.

## Read In This Order
1. `project-manifest.md`
2. `docs/WORKING_SET.md`
3. `docs/PROJECT_DIRECTION.md`
4. `docs/EXECUTION_PLAN.md`
5. `docs/PROMPT_CONTRACT.md`
6. `docs/MEMORY_AND_SESSION_POLICY.md`
7. `comms/RECENT.md`

Only read `comms/log.md` if chronology or change archaeology is the actual task.

## Current Product Reality
- Telegram is the primary interface.
- `/app` is a lightweight maintenance surface, not a second primary product.
- Postgres is the source of truth.
- The product is local-first; Todoist is no longer part of the live runtime.
- The conversation path is model-first.
- Deterministic code is still allowed for validation, grounding, safety, and bounded rescue.

## Current Repo Reality
- `backend/api/`: route and orchestration/runtime helpers
- `backend/common/`: shared domain logic, adapters, planner, Telegram formatting
- `backend/worker/`: reminders, summaries, background jobs
- `docs/`: canonical product/architecture/runtime docs
- `comms/tasks/`: active spec only
- `comms/tasks/archive/`: completed specs
- `archive/`: old material kept for reference, not active implementation guidance

## What Not To Do By Default
- Do not read the full `comms/log.md` unless you need exact chronology.
- Do not treat archived specs as active work.
- Do not reintroduce heuristic-first Telegram interpretation.
- Do not widen the web UI into a second main product without an explicit product decision.

## Current Active Behavioral Themes
- `/today` is the broader ranked agenda.
- Natural-language “what is due today?” maps to the stricter due-today view.
- Hierarchy matters: projects/tasks/subtasks should not flatten confusingly in views.
- Recent visible context and session state are important for follow-up resolution.
- Long Telegram change acks can now expose `Show more` and `Show subtasks`.

## Fast Sanity Checks
- `pytest -q backend`
- Telegram smoke:
  - `/today`
  - `What is due today?`
  - `move second one to tomorrow`
  - a reminder follow-up like `we handled that already`
  - a project/subtask flow like `create subtasks for me`

## If You Need More Context
- Product intent: `docs/PROJECT_DIRECTION.md`
- Active implementation state: `docs/EXECUTION_PLAN.md`
- Prompt/model contract: `docs/PROMPT_CONTRACT.md`
- Session and memory rules: `docs/MEMORY_AND_SESSION_POLICY.md`
- Latest concise handoff summary: `comms/RECENT.md`
