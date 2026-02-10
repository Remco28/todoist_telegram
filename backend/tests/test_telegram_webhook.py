"""Phase 4 Telegram webhook tests (spec cases 1-9) with stable boundaries.

These tests validate:
- webhook auth/ingest behavior
- command parsing/routing
- command semantics via handle_telegram_command
- non-command capture integration path
"""
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from api.main import handle_telegram_command
from api.schemas import AppliedChanges

WEBHOOK_URL = "/v1/integrations/telegram/webhook"
VALID_SECRET = "test_secret"


def _tg_update(text, chat_id="12345"):
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": int(chat_id), "type": "private", "username": "testuser"},
            "text": text,
            "date": int(datetime.utcnow().timestamp()),
        },
    }


def _headers(secret=VALID_SECRET):
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret
    return headers


def _post(asgi_app, url, **kwargs):
    async def _call():
        transport = ASGITransport(app=asgi_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(url, **kwargs)
    return asyncio.run(_call())


def test_webhook_rejects_invalid_secret(app_no_db):
    resp = _post(
        app_no_db,
        WEBHOOK_URL,
        json=_tg_update("hello"),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 403

    resp = _post(
        app_no_db,
        WEBHOOK_URL,
        json=_tg_update("hello"),
        headers=_headers("wrong_secret"),
    )
    assert resp.status_code == 403


def test_webhook_ignores_non_message_update(app_no_db):
    resp = _post(
        app_no_db,
        WEBHOOK_URL,
        json={"update_id": 2, "callback_query": {"id": "abc"}},
        headers=_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_command_today_routes_successfully(app_no_db):
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main.handle_telegram_command", new_callable=AsyncMock
    ) as mocked:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("/today"), headers=_headers())
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        mocked.assert_awaited_once()
        call = mocked.await_args.args
        assert call[0] == "/today"
        assert call[1] is None
        assert call[2] == "12345"
        assert call[3] == "usr_123"


def test_command_with_bot_suffix_is_supported(app_no_db):
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main.handle_telegram_command", new_callable=AsyncMock
    ) as mocked:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("/today@mybot"), headers=_headers())
        assert resp.status_code == 200
        mocked.assert_awaited_once()
        assert mocked.await_args.args[0] == "/today"


def test_non_command_text_uses_full_capture_pipeline(app_no_db, mock_extract, mock_send):
    mock_extract.extract_structured_updates.return_value = {
        "tasks": [{"title": "Task A"}],
        "goals": [{"title": "Goal A"}],
        "problems": [{"title": "Problem A"}],
        "links": [],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._apply_capture", new_callable=AsyncMock
    ) as apply_capture:
        apply_capture.return_value = (
            "inb_1",
            AppliedChanges(tasks_created=1, goals_created=1, problems_created=1),
        )
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("plain text"), headers=_headers())
        assert resp.status_code == 200
        apply_capture.assert_awaited_once()
        mock_send.assert_awaited_once()
        ack = mock_send.await_args.args[1]
        assert "1 task(s) created" in ack
        assert "1 goal(s) created" in ack
        assert "1 problem(s) created" in ack


def test_non_command_capture_dedup_updates_task_count(app_no_db, mock_send):
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._apply_capture", new_callable=AsyncMock
    ) as apply_capture:
        apply_capture.return_value = (
            "inb_2",
            AppliedChanges(tasks_updated=1),
        )
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("buy groceries"), headers=_headers())
        assert resp.status_code == 200
        mock_send.assert_awaited_once()
        ack = mock_send.await_args.args[1]
        assert "1 task(s) updated" in ack


def test_unlinked_chat_command_receives_link_guidance(app_no_db, mock_send):
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value=None), patch(
        "api.main.handle_telegram_command", new_callable=AsyncMock
    ) as mocked:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("/plan"), headers=_headers())
        assert resp.status_code == 200
        mocked.assert_not_awaited()
        mock_send.assert_awaited_once()
        assert "not linked yet" in mock_send.await_args.args[1].lower()


def test_start_command_consumes_token_and_links(app_no_db, mock_send):
    with patch("api.main._consume_telegram_link_token", new_callable=AsyncMock, return_value=True) as consume:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("/start abc123"), headers=_headers())
        assert resp.status_code == 200
        consume.assert_awaited_once()
        mock_send.assert_awaited_once()
        assert "linked successfully" in mock_send.await_args.args[1].lower()


def test_start_command_with_invalid_token_returns_guidance(app_no_db, mock_send):
    with patch("api.main._consume_telegram_link_token", new_callable=AsyncMock, return_value=False):
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("/start badtoken"), headers=_headers())
        assert resp.status_code == 200
        mock_send.assert_awaited_once()
        assert "link failed" in mock_send.await_args.args[1].lower()


def test_command_plan_enqueues_refresh(mock_redis, mock_send, mock_db):
    with patch("api.main.redis_client", mock_redis):
        asyncio.run(handle_telegram_command("/plan", None, "12345", "usr_abc", mock_db))
    mock_redis.rpush.assert_awaited_once()
    queue_name, raw_job = mock_redis.rpush.await_args.args
    assert queue_name == "default_queue"
    job = json.loads(raw_job)
    assert job["topic"] == "plan.refresh"
    assert "job_id" in job
    mock_send.assert_awaited_once()
    assert job["job_id"] in mock_send.await_args.args[1]


def test_command_focus_returns_top_three_max(mock_redis, mock_send, mock_db):
    mock_redis.get.return_value = json.dumps({
        "today_plan": [
            {"task_id": f"tsk_{i}", "title": f"Task {i}"} for i in range(1, 6)
        ]
    })
    with patch("api.main.redis_client", mock_redis):
        asyncio.run(handle_telegram_command("/focus", None, "12345", "usr_abc", mock_db))
    text = mock_send.await_args.args[1]
    assert "Task 1" in text
    assert "Task 2" in text
    assert "Task 3" in text
    assert "Task 4" not in text
    assert "Task 5" not in text


def test_command_done_updates_owned_task_only(mock_db, mock_send):
    result = AsyncMock()
    result.rowcount = 1
    mock_db.execute.return_value = result
    asyncio.run(handle_telegram_command("/done", "tsk_x", "12345", "usr_abc", mock_db))
    mock_db.commit.assert_awaited_once()
    assert "marked as done" in mock_send.await_args.args[1]


def test_command_done_rejects_non_owned_or_unknown(mock_db, mock_send):
    result = AsyncMock()
    result.rowcount = 0
    mock_db.execute.return_value = result
    asyncio.run(handle_telegram_command("/done", "tsk_other", "12345", "usr_abc", mock_db))
    mock_db.commit.assert_not_awaited()
    assert "not found" in mock_send.await_args.args[1].lower()
