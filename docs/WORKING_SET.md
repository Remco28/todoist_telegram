# Working Set

This is the smallest useful default context for active work on the project.

## Canonical Docs
- `README.md`
- `docs/PROJECT_DIRECTION.md`
- `docs/EXECUTION_PLAN.md`
- `docs/PROMPT_CONTRACT.md`
- `docs/MEMORY_AND_SESSION_POLICY.md`
- `docs/RESUME_GUIDE.md`

## Canonical Runtime Areas
- `backend/api/telegram_draft_flow.py`
- `backend/api/telegram_orchestration.py`
- `backend/api/telegram_views.py`
- `backend/api/capture_apply.py`
- `backend/api/draft_runtime.py`
- `backend/api/grounding_runtime.py`
- `backend/api/reference_resolution.py`
- `backend/common/adapter.py`
- `backend/common/planner.py`
- `backend/common/telegram.py`
- `backend/common/session_state.py`
- `backend/common/models.py`

## Product Constraints To Preserve
- Telegram interpretation stays model-first.
- Deterministic logic is allowed only for grounding, validation, safety, and narrow recovery.
- Local Postgres is the source of truth.
- `/app` stays a maintenance surface.
- Avoid broadening slash-command UX.
- Avoid reading append-only history files by default.

## Typical Active Work
- Telegram conversational behavior
- Planner/read-view behavior
- Reminder behavior
- Session grounding and follow-up resolution
- Maintenance UI cleanup/polish

## Default Files To Ignore Unless Needed
- `comms/log.md` as a whole
- `comms/tasks/archive/`
- `archive/legacy_docs/`
- old migration rationale once the migration itself is not the problem

## Current Known Useful Surfaces
- `/today`
- `/urgent`
- natural-language due-today questions
- `/web`
- Telegram inline confirm/edit/no buttons
- Telegram inline `Show more` / `Show subtasks` on long applied-change acknowledgements
