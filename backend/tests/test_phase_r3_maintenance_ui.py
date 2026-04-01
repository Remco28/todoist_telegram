import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

from httpx import ASGITransport, AsyncClient
from common.models import Session


def _get(app, url):
    async def _call():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(url)

    return asyncio.run(_call())


def _get_auth(app, url, token="test_token"):
    async def _call():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(url, headers={"Authorization": f"Bearer {token}"})

    return asyncio.run(_call())


def test_maintenance_workbench_renders_without_auth_header(app_no_db):
    response = _get(app_no_db, "/app")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Local Assistant Workbench" in body
    assert "/v1/work_items" in body
    assert "/v1/reminders" in body
    assert "/v1/history/action_batches" in body
    assert "/v1/work_items/${itemId}/versions" in body
    assert "/v1/reminders/${reminderId}/versions" in body
    assert "/v1/reminders/${reminderId}/snooze" in body
    assert "/undo" in body
    assert "?token=&lt;your_api_token&gt;" in body
    assert "new-parent-id" in body
    assert "new-reminder-work-item-id" in body
    assert "sortWorkItemsForHierarchy" in body
    assert "under ${parentTitle}" in body
    assert "chat-id-input" in body
    assert "data-mode-toggle" in body
    assert "data-item-toggle" in body
    assert "search-filter" in body
    assert "due-filter" in body
    assert "today-panel" in body
    assert "today-plan-items" in body
    assert "toast-stack" in body
    assert "data-item-quick" in body
    assert "clear-today-button" in body
    assert "data-item-edit" in body
    assert "ui-work-item-update-" in body
    assert "data-reminder-edit" in body
    assert "ui-reminder-update-" in body


def test_maintenance_workbench_embeds_token_for_client_side_api_calls(app_no_db):
    response = _get(app_no_db, "/app?token=test_token")

    assert response.status_code == 200
    assert 'const initialToken = "test_token";' in response.text


def test_get_today_plan_uses_latest_session_when_chat_id_missing(app_no_db, mock_db):
    latest_session = Session(
        id="ses_latest",
        user_id="usr_dev",
        chat_id="tg_chat_1",
        started_at=datetime.now(timezone.utc),
        last_activity_at=datetime.now(timezone.utc),
    )
    latest_result = Mock()
    latest_result.scalar_one_or_none.return_value = latest_session
    mock_db.execute = AsyncMock(return_value=latest_result)
    payload = {
        "schema_version": "plan.v1",
        "plan_window": "today",
        "generated_at": "2026-04-01T12:00:00Z",
        "today_plan": [],
        "next_actions": [],
        "blocked_items": [],
        "due_reminders": [],
        "why_this_order": [],
    }

    with patch("api.main._load_today_plan_payload", new_callable=AsyncMock, return_value=(payload, False)) as load_payload:
        response = _get_auth(app_no_db, "/v1/plan/get_today")

    assert response.status_code == 200
    load_payload.assert_awaited_once_with(mock_db, "usr_dev", "tg_chat_1", require_fresh=True)
