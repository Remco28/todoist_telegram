# Phase 4 Test Spec: Telegram Webhook (Compact)

## Objective
Add automated tests that lock down Phase 4 Telegram behavior so regressions are caught quickly.

## Scope
- Webhook auth/ingest behavior.
- Command parsing/routing behavior.
- Non-command capture behavior parity with core capture pipeline.
- Telegram HTML safety in formatted responses.

Out of scope:
- Telegram network integration tests against real Telegram.
- End-to-end deployment tests in Coolify.

## Files To Add
- `backend/tests/test_telegram_webhook.py`
- `backend/tests/test_telegram_formatting.py`

If a different test structure already exists, place these tests in the existing equivalent locations.

## Test Harness Requirements
- Use `pytest`.
- Mock outbound Telegram send function (`common.telegram.send_message`) so no real network calls occur.
- Mock extraction adapter (`adapter.extract_structured_updates`) where needed.
- Use isolated DB + Redis test fixtures consistent with current backend test setup.

## Required Test Cases
1. `webhook_rejects_invalid_secret`
- Given `TELEGRAM_WEBHOOK_SECRET` is set.
- When header `X-Telegram-Bot-Api-Secret-Token` is missing or wrong.
- Then `POST /v1/integrations/telegram/webhook` returns `403`.

2. `webhook_ignores_non_message_update`
- Given a Telegram update without `message.text`.
- Then endpoint returns `200` with `{"status":"ignored"}`.

3. `command_today_routes_successfully`
- Given a valid `/today` message.
- Then `send_message` is called once with formatted plan output.
- Then webhook returns `200` and does not write capture entities.

4. `command_with_bot_suffix_is_supported`
- Given `/today@mybot`.
- Then it routes exactly like `/today` (not unknown command).

5. `command_plan_enqueues_refresh`
- Given `/plan`.
- Then a `plan.refresh` job is pushed to `default_queue`.
- Then acknowledgment includes a job id.

6. `command_focus_returns_top_three_max`
- Given a plan payload containing 5 items.
- Then formatted focus response contains only 3 items.

7. `command_done_updates_owned_task_only`
- Given existing task `tsk_x` for `usr_dev`.
- When `/done tsk_x`.
- Then task status becomes `done` and `completed_at` is set.
- Given unknown/non-owned task id.
- Then response is failure message and no mutation occurs.

8. `non_command_text_uses_full_capture_pipeline`
- Given extraction returns tasks, goals, problems, links.
- When webhook receives plain text.
- Then all entity types are processed through shared capture logic.
- Then summary job `memory.summarize` is enqueued.
- Then ack reflects created/updated counts.

9. `non_command_capture_dedup_updates_task_count`
- Given existing open task with same normalized title.
- Then capture increments `tasks_updated` and does not create duplicate task.

10. `formatters_escape_html_content`
- Given titles/reasons containing `<`, `>`, `&`.
- Then formatting output contains escaped text and does not leak raw HTML markup from user content.

## Acceptance Criteria
1. All tests pass locally.
2. Compile check passes:
- `python3 -m py_compile backend/api/main.py backend/common/telegram.py backend/api/schemas.py backend/common/config.py`
3. Test run command and summary are included in implementation notes.

## Done Criteria
- Tests merged with clear names matching the cases above.
- No real external HTTP calls in test execution.
- This spec is archived after architect review pass.
