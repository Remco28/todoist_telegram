import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from common.models import ActionBatch, ActionBatchStatus, VersionOperation, WorkItemVersion
from common.models import WorkItem, WorkItemKind, WorkItemStatus


class _FakeResult:
    def __init__(self, *, items=None, one_or_none=None):
        self._items = items or []
        self._one_or_none = one_or_none

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


def _post(app, url):
    async def _call():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                url,
                json={},
                headers={
                    "Authorization": "Bearer test_token",
                    "Idempotency-Key": "idem-undo-history",
                },
            )

    return asyncio.run(_call())


def test_list_action_batches_returns_recent_history_payload(app_no_db, mock_db):
    batch = ActionBatch(
        id="abt_1",
        user_id="usr_dev",
        conversation_event_id="cev_1",
        source_message="Mark the backpack reminder done.",
        status=ActionBatchStatus.applied,
        proposal_json={"tasks": [{"title": "Remind Amy about the backpack"}]},
        applied_item_ids_json=["tsk_backpack"],
        before_summary="1 task open",
        after_summary="Marked backpack reminder done",
        created_at=datetime(2026, 3, 25, 18, 0, tzinfo=timezone.utc),
    )
    mock_db.execute.side_effect = [_FakeResult(items=[batch])]

    response = _get(app_no_db, "/v1/history/action_batches")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "abt_1",
            "user_id": "usr_dev",
            "conversation_event_id": "cev_1",
            "source_message": "Mark the backpack reminder done.",
            "status": "applied",
            "proposal_json": {"tasks": [{"title": "Remind Amy about the backpack"}]},
            "applied_item_ids": ["tsk_backpack"],
            "before_summary": "1 task open",
            "after_summary": "Marked backpack reminder done",
            "undo_window_expires_at": None,
            "reverted_at": None,
            "created_at": "2026-03-25T18:00:00+00:00",
        }
    ]


def test_list_work_item_versions_returns_versions_for_item(app_no_db, mock_db):
    version = WorkItemVersion(
        id="wiv_1",
        user_id="usr_dev",
        work_item_id="tsk_1",
        action_batch_id="abt_1",
        operation=VersionOperation.update,
        before_json={"status": "open"},
        after_json={"status": "done"},
        created_at=datetime(2026, 3, 25, 18, 5, tzinfo=timezone.utc),
    )
    mock_db.execute.side_effect = [_FakeResult(items=[version])]

    response = _get(app_no_db, "/v1/work_items/tsk_1/versions")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "wiv_1",
            "user_id": "usr_dev",
            "work_item_id": "tsk_1",
            "action_batch_id": "abt_1",
            "operation": "update",
            "before_json": {"status": "open"},
            "after_json": {"status": "done"},
            "created_at": "2026-03-25T18:05:00+00:00",
        }
    ]


def test_undo_action_batch_restores_work_item_and_records_revert_batch(app_no_db, mock_db):
    batch = ActionBatch(
        id="abt_undo_me",
        user_id="usr_dev",
        source_message="Complete backpack reminder",
        status=ActionBatchStatus.applied,
        proposal_json={"tasks": [{"target_task_id": "tsk_1", "action": "complete"}]},
        applied_item_ids_json=["tsk_1"],
        undo_window_expires_at=datetime(2026, 3, 26, 18, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 25, 18, 0, tzinfo=timezone.utc),
    )
    version = WorkItemVersion(
        id="wiv_undo_me",
        user_id="usr_dev",
        work_item_id="tsk_1",
        action_batch_id="abt_undo_me",
        operation=VersionOperation.complete,
        before_json={"title": "Remind Amy about the backpack", "status": "open", "title_norm": "remind amy about the backpack"},
        after_json={"title": "Remind Amy about the backpack", "status": "done", "title_norm": "remind amy about the backpack"},
        created_at=datetime(2026, 3, 25, 18, 1, tzinfo=timezone.utc),
    )
    item = WorkItem(
        id="tsk_1",
        user_id="usr_dev",
        kind=WorkItemKind.task,
        title="Remind Amy about the backpack",
        title_norm="remind amy about the backpack",
        status=WorkItemStatus.done,
        completed_at=datetime(2026, 3, 25, 18, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 25, 17, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 25, 18, 1, tzinfo=timezone.utc),
    )
    mock_db.execute.side_effect = [
        _FakeResult(one_or_none=None),
        _FakeResult(one_or_none=batch),
        _FakeResult(items=[version]),
        _FakeResult(one_or_none=item),
    ]

    with patch("api.main.save_idempotency", new=AsyncMock()):
        response = _post(app_no_db, "/v1/history/action_batches/abt_undo_me/undo")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["reverted_batch_id"] == "abt_undo_me"
    assert body["restored_item_ids"] == ["tsk_1"]
    assert item.status == WorkItemStatus.open
    assert batch.status == ActionBatchStatus.reverted
    assert batch.reverted_at is not None
    added = [call.args[0] for call in mock_db.add.call_args_list]
    undo_batch = next(entry for entry in added if isinstance(entry, ActionBatch) and entry.id != "abt_undo_me")
    assert undo_batch.status == ActionBatchStatus.reverted
    assert any(isinstance(entry, WorkItemVersion) and entry.operation == VersionOperation.restore for entry in added)
