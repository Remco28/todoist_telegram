import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from common.models import (
    ActionBatch,
    WorkItem,
    WorkItemKind,
    WorkItemLink,
    WorkItemStatus,
    WorkItemVersion,
)


class _FakeResult:
    def __init__(self, *, items=None, one_or_none=None, rowcount=1):
        self._items = items or []
        self._one_or_none = one_or_none
        self.rowcount = rowcount

    def scalars(self):
        return self

    def all(self):
        return self._items

    def scalar_one_or_none(self):
        return self._one_or_none


def _get(app, url):
    async def _call():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(url, headers={"Authorization": "Bearer test_token"})

    return asyncio.run(_call())


def _post(app, url, payload):
    async def _call():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": "Bearer test_token",
                    "Idempotency-Key": "idem-work-item-create",
                },
            )

    return asyncio.run(_call())


def _patch(app, url, payload):
    async def _call():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.patch(
                url,
                json=payload,
                headers={
                    "Authorization": "Bearer test_token",
                    "Idempotency-Key": "idem-work-item-update",
                },
            )

    return asyncio.run(_call())


def test_list_work_items_returns_canonical_local_first_payload(app_no_db, mock_db):
    item = WorkItem(
        id="tsk_local_1",
        user_id="usr_dev",
        kind=WorkItemKind.task,
        title="Review payroll checklist",
        title_norm="review payroll checklist",
        status=WorkItemStatus.open,
        priority=3,
        created_at=datetime(2026, 3, 25, 16, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 25, 16, 5, tzinfo=timezone.utc),
    )
    mock_db.execute.side_effect = [_FakeResult(items=[item])]

    response = _get(app_no_db, "/v1/work_items")

    assert response.status_code == 200
    body = response.json()
    assert body == [
        {
            "id": "tsk_local_1",
            "user_id": "usr_dev",
            "kind": "task",
            "parent_id": None,
            "area_id": None,
            "title": "Review payroll checklist",
            "title_norm": "review payroll checklist",
            "notes": None,
            "attributes_json": {},
            "status": "open",
            "priority": 3,
            "due_at": None,
            "scheduled_for": None,
            "snooze_until": None,
            "estimated_minutes": None,
            "created_at": "2026-03-25T16:00:00+00:00",
            "updated_at": "2026-03-25T16:05:00+00:00",
            "completed_at": None,
            "archived_at": None,
        }
    ]


def test_create_work_item_records_history_without_legacy_mirroring(app_no_db, mock_db):
    mock_db.execute.side_effect = [_FakeResult(one_or_none=None)]

    with patch("api.main.save_idempotency", new=AsyncMock()):
        response = _post(
            app_no_db,
            "/v1/work_items",
            {
                "kind": "task",
                "title": "Plan health insurance follow-up",
                "status": "open",
                "priority": 2,
                "due_at": "2026-03-28",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "task"
    assert body["title"] == "Plan health insurance follow-up"
    assert body["due_at"] == "2026-03-28T12:00:00+00:00"
    added = [call.args[0] for call in mock_db.add.call_args_list]
    assert any(isinstance(item, ActionBatch) for item in added)
    assert any(isinstance(item, WorkItemVersion) for item in added)


def test_update_work_item_records_action_batch_and_version(app_no_db, mock_db):
    item = WorkItem(
        id="tsk_local_2",
        user_id="usr_dev",
        kind=WorkItemKind.task,
        title="Review payroll checklist",
        title_norm="review payroll checklist",
        status=WorkItemStatus.open,
        created_at=datetime(2026, 3, 25, 16, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 25, 16, 5, tzinfo=timezone.utc),
    )
    mock_db.execute.side_effect = [_FakeResult(one_or_none=None), _FakeResult(one_or_none=item)]

    with patch("api.main.save_idempotency", new=AsyncMock()):
        response = _patch(
            app_no_db,
            "/v1/work_items/tsk_local_2",
            {
                "status": "done",
                "notes": "Handled in person.",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "done"
    added = [call.args[0] for call in mock_db.add.call_args_list]
    assert any(isinstance(entry, ActionBatch) for entry in added)
    version = next(entry for entry in added if isinstance(entry, WorkItemVersion))
    assert version.operation.value == "complete"


def test_goal_compatibility_endpoint_is_unregistered(app_no_db):
    response = _get(app_no_db, "/v1/goals")

    assert response.status_code == 404


def test_problem_compatibility_endpoint_is_unregistered(app_no_db):
    response = _get(app_no_db, "/v1/problems")

    assert response.status_code == 404


def test_task_compatibility_endpoint_is_unregistered(app_no_db):
    response = _get(app_no_db, "/v1/tasks")

    assert response.status_code == 404


def test_update_goal_compatibility_endpoint_is_unregistered(app_no_db):
    response = _patch(
        app_no_db,
        "/v1/goals/gol_alpha",
        {
            "status": "paused",
        },
    )

    assert response.status_code == 404


def test_update_problem_compatibility_endpoint_is_unregistered(app_no_db):
    response = _patch(
        app_no_db,
        "/v1/problems/prb_alpha",
        {
            "status": "resolved",
        },
    )

    assert response.status_code == 404


def test_update_task_compatibility_endpoint_is_unregistered(app_no_db):
    response = _patch(
        app_no_db,
        "/v1/tasks/tsk_alpha",
        {
            "status": "done",
        },
    )

    assert response.status_code == 404


def test_create_link_creates_work_item_link_when_both_entities_exist(app_no_db, mock_db):
    from_item = WorkItem(
        id="tsk_alpha",
        user_id="usr_dev",
        kind=WorkItemKind.task,
        title="Finish apartment quote review",
        title_norm="finish apartment quote review",
        status=WorkItemStatus.open,
        created_at=datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc),
    )
    to_item = WorkItem(
        id="gol_alpha",
        user_id="usr_dev",
        kind=WorkItemKind.project,
        title="Finish apartment renovation",
        title_norm="finish apartment renovation",
        status=WorkItemStatus.open,
        created_at=datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc),
    )
    mock_db.execute.side_effect = [_FakeResult(one_or_none=None), _FakeResult(items=[from_item, to_item])]

    with patch("api.main.save_idempotency", new=AsyncMock()):
        response = _post(
            app_no_db,
            "/v1/links",
            {
                "from_entity_type": "task",
                "from_entity_id": "tsk_alpha",
                "to_entity_type": "goal",
                "to_entity_id": "gol_alpha",
                "link_type": "supports_goal",
            },
        )

    assert response.status_code == 200
    added_rows = [call.args[0] for call in mock_db.add.call_args_list]
    assert any(isinstance(row, WorkItemLink) and row.link_type.value == "part_of" for row in added_rows)
