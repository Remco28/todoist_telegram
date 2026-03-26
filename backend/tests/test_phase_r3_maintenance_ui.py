import asyncio

from httpx import ASGITransport, AsyncClient


def _get(app, url):
    async def _call():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(url)

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
    assert "data-item-edit" in body
    assert "ui-work-item-edit-" in body
    assert "data-reminder-edit" in body
    assert "ui-reminder-edit-" in body


def test_maintenance_workbench_embeds_token_for_client_side_api_calls(app_no_db):
    response = _get(app_no_db, "/app?token=test_token")

    assert response.status_code == 200
    assert 'const initialToken = "test_token";' in response.text
