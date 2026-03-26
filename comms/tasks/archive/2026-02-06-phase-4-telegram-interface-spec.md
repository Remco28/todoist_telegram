# Phase 4 Spec: Telegram Product Interface v1

## Rationale
The product is useful only when it is easy to use in real life. Phase 3 already gives us planning and query endpoints; Phase 4 should add a thin Telegram interface that maps chat messages and commands into those existing backend capabilities without changing core planning/memory logic.

## Objective
Implement a Telegram webhook interface that:
1. Accepts and verifies Telegram updates.
2. Routes key commands (`/today`, `/plan`, `/focus`, `/done`).
3. Treats non-command text as capture input (`capture/thought`).
4. Sends human-readable replies back to Telegram reliably.

## Scope (This Spec Only)
- Telegram webhook ingest endpoint.
- Telegram command parsing/routing.
- Bot reply delivery via Telegram HTTP API.
- Basic chat/user mapping and safe defaults.

Out of scope:
- Todoist sync behavior.
- Advanced conversational UX and multi-step dialogs.
- New planning algorithms or memory model changes.

## Files and Functions To Modify

### `backend/common/config.py`
Add Telegram settings:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET` (for optional secret header validation)
- `TELEGRAM_API_BASE` (default `https://api.telegram.org`)
- `TELEGRAM_COMMAND_TIMEOUT_SECONDS` (default `20`)
- `TELEGRAM_DEFAULT_SOURCE` (default `telegram`)

### New file: `backend/common/telegram.py`
Implement helper functions:
- `verify_telegram_secret(headers) -> bool`
- `parse_update(update_json) -> dict | None`
- `extract_command(text) -> (command, args)`
- `send_message(chat_id: str, text: str) -> dict`
- `format_today_plan(plan_payload) -> str`
- `format_plan_refresh_ack(job_id) -> str`

### `backend/api/schemas.py`
Add request models for webhook processing:
- `TelegramUpdateEnvelope` (minimal fields needed for validation)
- Optional internal response model for webhook ack (`{"status":"ok"}`).

### `backend/api/main.py`
Add endpoint:
- `POST /v1/integrations/telegram/webhook`

Behavior:
1. Validate secret header when configured.
2. Parse update; ignore non-message updates safely.
3. Resolve `chat_id` and `text`.
4. Command routing:
- `/today`: call existing plan retrieval path and send formatted plan.
- `/plan`: enqueue plan refresh and acknowledge job id.
- `/focus`: return top 1-3 from today plan.
- `/done <task_id>`: call existing task update path (`status=done`) and confirm.
5. Non-command text:
- route to existing capture flow as `source=telegram`, `chat_id=<telegram_chat_id>`.
- return short acknowledgement summarizing created/updated counts.
6. Always return webhook 200 with simple ack payload unless auth/secret check fails.

Implementation note:
- Reuse existing internal functions where practical; do not duplicate planning logic.
- Avoid making Telegram webhook endpoint depend on idempotency middleware.

## Required Command Semantics
- `/today`: read-only. Must not mutate state.
- `/plan`: write-enabled via queue enqueue only.
- `/focus`: read-only summary of immediate priorities.
- `/done <task_id>`:
- validate task id format is non-empty,
- update only within authenticated user scope derived from Telegram mapping,
- respond with success/failure text.

## User Scope and Mapping (Phase 4 Minimal)
- Map Telegram `chat_id` to backend `chat_id` as string identity.
- For v1 single-user mode, use default backend user (`usr_dev`) behind Telegram webhook.
- Keep mapping logic isolated so Phase 5+ can evolve to multi-user mapping table.

## Error Handling Requirements
- Provider/API failure: send concise retry-friendly message to Telegram.
- Unknown command: return supported command list.
- Empty text message: no-op with safe ack.
- Never expose stack traces or internal tokens in Telegram messages.

## Acceptance Criteria
1. Webhook endpoint accepts a valid Telegram message update and returns 200 ack.
2. `/today` sends formatted plan text based on `GET /v1/plan/get_today` equivalent output.
3. `/plan` enqueues refresh and sends acknowledgement containing job id.
4. `/focus` sends compact top-priority response (1-3 items).
5. `/done <task_id>` updates task status to done and confirms result.
6. Plain message (non-command) is captured via existing capture flow and acknowledged.
7. Invalid/unknown command paths are user-friendly and non-crashing.
8. Compile check passes:
- `python3 -m py_compile backend/api/main.py backend/common/telegram.py backend/api/schemas.py`

## Developer Handoff Notes
- Keep Telegram integration thin and adapter-like.
- Prefer deterministic formatting over LLM for command responses.
- Log `IMPL IN_PROGRESS` and `IMPL DONE` in `comms/log.md`.

## Done Criteria
- All acceptance criteria above demonstrated in implementation notes.
- Architect review passes.
- This spec is archived to `comms/tasks/archive/`.
