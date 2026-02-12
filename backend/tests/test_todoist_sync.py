import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from api.main import app, get_db, get_todoist_sync_status
from common.models import Task, TaskStatus, TodoistTaskMap
from worker.main import handle_todoist_sync, handle_todoist_reconcile


class _FakeResult:
    def __init__(self, items=None, scalar=None, one_or_none=None):
        self._items = items if items is not None else []
        self._scalar = scalar
        self._one_or_none = one_or_none

    def scalars(self):
        return self

    def all(self):
        return self._items

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._one_or_none


def _session_factory(fake_db):
    @asynccontextmanager
    async def _ctx():
        yield fake_db

    return lambda: _ctx()


def test_sync_recovery_from_failed_create():
    async def _run():
        task = Task(id="t1", user_id="usr_dev", title="T1", title_norm="t1", status=TaskStatus.open)
        mapping = TodoistTaskMap(
            id="m1",
            user_id="usr_dev",
            local_task_id="t1",
            todoist_task_id=None,
            sync_state="error",
            last_error="create failed",
        )

        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(
            side_effect=[
                MagicMock(all=MagicMock(return_value=[(task, mapping)])),
            ]
        )
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        todoist = AsyncMock()
        todoist.create_task.return_value = {"id": "td_1"}
        todoist.update_task.return_value = {}
        todoist.close_task.return_value = True

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)), patch("worker.main.todoist_adapter", todoist):
            await handle_todoist_sync("job_1", {"user_id": "usr_dev"}, {"attempt": 1})

        assert mapping.todoist_task_id == "td_1"
        assert mapping.sync_state == "synced"
        assert mapping.last_error is None
        todoist.create_task.assert_awaited_once()
        todoist.update_task.assert_not_awaited()

    asyncio.run(_run())


def test_sync_recovery_done_task_creates_then_closes():
    async def _run():
        task = Task(id="t2", user_id="usr_dev", title="T2", title_norm="t2", status=TaskStatus.done)
        mapping = TodoistTaskMap(
            id="m2",
            user_id="usr_dev",
            local_task_id="t2",
            todoist_task_id=None,
            sync_state="error",
        )

        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(
            side_effect=[
                MagicMock(all=MagicMock(return_value=[(task, mapping)])),
            ]
        )
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        todoist = AsyncMock()
        todoist.create_task.return_value = {"id": "td_2"}
        todoist.close_task.return_value = True
        todoist.update_task.return_value = {}

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)), patch("worker.main.todoist_adapter", todoist):
            await handle_todoist_sync("job_2", {"user_id": "usr_dev"}, {"attempt": 1})

        assert mapping.todoist_task_id == "td_2"
        assert mapping.sync_state == "synced"
        todoist.create_task.assert_awaited_once()
        todoist.close_task.assert_awaited_once_with("td_2")

    asyncio.run(_run())


def test_sync_skips_unchanged_synced_tasks():
    async def _run():
        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(
            side_effect=[
                MagicMock(all=MagicMock(return_value=[])),
            ]
        )
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        todoist = AsyncMock()
        todoist.create_task.return_value = {"id": "td_new"}
        todoist.update_task.return_value = {}
        todoist.close_task.return_value = True

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)), patch("worker.main.todoist_adapter", todoist):
            await handle_todoist_sync("job_noop", {"user_id": "usr_dev"}, {"attempt": 1})

        todoist.create_task.assert_not_awaited()
        todoist.update_task.assert_not_awaited()
        todoist.close_task.assert_not_awaited()
        fake_db.commit.assert_awaited_once()

    asyncio.run(_run())


def test_trigger_endpoint_enqueues_sync_job(mock_redis):
    async def _run():
        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(return_value=_FakeResult(one_or_none=None))
        fake_db.commit = AsyncMock()
        fake_db.add = AsyncMock()

        async def _override_get_db():
            yield fake_db

        app.dependency_overrides[get_db] = _override_get_db
        try:
            with patch("api.main.redis_client", mock_redis), patch("api.main.save_idempotency", new_callable=AsyncMock):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post(
                        "/v1/sync/todoist",
                        headers={"Authorization": "Bearer test_token", "Idempotency-Key": "ik_todoist_sync"},
                    )
                    assert resp.status_code == 200
                    assert resp.json()["status"] == "ok"
                    assert "job_id" in resp.json()

            mock_redis.rpush.assert_awaited_once()
            _, raw = mock_redis.rpush.await_args.args
            assert '"topic": "sync.todoist"' in raw
        finally:
            app.dependency_overrides.clear()

    asyncio.run(_run())


def test_reconcile_endpoint_enqueues_reconcile_job(mock_redis):
    async def _run():
        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(return_value=_FakeResult(one_or_none=None))
        fake_db.commit = AsyncMock()
        fake_db.add = AsyncMock()

        async def _override_get_db():
            yield fake_db

        app.dependency_overrides[get_db] = _override_get_db
        try:
            with patch("api.main.redis_client", mock_redis), patch("api.main.save_idempotency", new_callable=AsyncMock):
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post(
                        "/v1/sync/todoist/reconcile",
                        headers={"Authorization": "Bearer test_token", "Idempotency-Key": "ik_todoist_reconcile"},
                    )
                    assert resp.status_code == 200
                    assert resp.json()["status"] == "ok"
                    assert resp.json()["enqueued"] is True
                    assert "job_id" in resp.json()

            mock_redis.rpush.assert_awaited_once()
            _, raw = mock_redis.rpush.await_args.args
            assert '"topic": "sync.todoist.reconcile"' in raw
        finally:
            app.dependency_overrides.clear()

    asyncio.run(_run())


def test_reconcile_applies_remote_completion_to_local_task():
    async def _run():
        task = Task(id="t_recon_done", user_id="usr_dev", title="T", title_norm="t", status=TaskStatus.open)
        mapping = TodoistTaskMap(
            id="m_recon_done",
            user_id="usr_dev",
            local_task_id=task.id,
            todoist_task_id="td_done",
            sync_state="synced",
        )

        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(
            side_effect=[
                _FakeResult(items=[mapping]),            # mappings batch 1
                _FakeResult(one_or_none=task),           # task by local id
                _FakeResult(items=[]),                   # mappings batch 2 (stop)
            ]
        )
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        todoist = AsyncMock()
        todoist.get_task.return_value = {"id": "td_done", "is_completed": True}

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)), patch("worker.main.todoist_adapter", todoist):
            await handle_todoist_reconcile("job_recon_done", {"user_id": "usr_dev"}, {"attempt": 1})

        assert task.status == TaskStatus.done
        assert mapping.sync_state == "synced"
        assert mapping.last_error is None
        todoist.get_task.assert_awaited_once_with("td_done")

    asyncio.run(_run())


def test_reconcile_applies_mutable_fields_for_open_tasks():
    async def _run():
        task = Task(
            id="t_recon_open",
            user_id="usr_dev",
            title="Old title",
            title_norm="old title",
            status=TaskStatus.open,
            notes="Old notes",
            priority=3,
            due_date=None,
        )
        mapping = TodoistTaskMap(
            id="m_recon_open",
            user_id="usr_dev",
            local_task_id=task.id,
            todoist_task_id="td_open",
            sync_state="synced",
        )

        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(
            side_effect=[
                _FakeResult(items=[mapping]),            # mappings batch 1
                _FakeResult(one_or_none=task),           # task by local id
                _FakeResult(items=[]),                   # mappings batch 2 (stop)
            ]
        )
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        todoist = AsyncMock()
        todoist.get_task.return_value = {
            "id": "td_open",
            "is_completed": False,
            "content": "New title",
            "description": "New notes",
            "priority": 4,
            "due": {"date": "2026-02-15"},
        }

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)), patch("worker.main.todoist_adapter", todoist):
            await handle_todoist_reconcile("job_recon_open", {"user_id": "usr_dev"}, {"attempt": 1})

        assert task.title == "New title"
        assert task.notes == "New notes"
        assert task.priority == 1  # local maps from remote (5 - 4)
        assert task.due_date is not None
        assert mapping.sync_state == "synced"
        assert mapping.last_error is None

    asyncio.run(_run())


def test_reconcile_remote_missing_marks_mapping_error_and_event():
    async def _run():
        task = Task(id="t_recon_missing", user_id="usr_dev", title="T", title_norm="t", status=TaskStatus.open)
        mapping = TodoistTaskMap(
            id="m_recon_missing",
            user_id="usr_dev",
            local_task_id=task.id,
            todoist_task_id="td_missing",
            sync_state="synced",
        )

        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(
            side_effect=[
                _FakeResult(items=[mapping]),   # mappings batch 1
                _FakeResult(items=[]),          # mappings batch 2 (stop)
            ]
        )
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        todoist = AsyncMock()
        todoist.get_task.return_value = None

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)), patch("worker.main.todoist_adapter", todoist):
            await handle_todoist_reconcile("job_recon_missing", {"user_id": "usr_dev"}, {"attempt": 1})

        assert mapping.sync_state == "error"
        assert mapping.last_error == "remote_task_missing"
        event_types = [call.args[0].event_type for call in fake_db.add.call_args_list]
        assert "todoist_reconcile_remote_missing" in event_types
        assert "todoist_reconcile_completed" in event_types

    asyncio.run(_run())


def test_status_endpoint_shape_and_transition_expectation():
    async def _run():
        fake_db = AsyncMock()
        # total, pending, error, last_synced, last_attempt, last_reconcile, reconcile_errors
        fake_db.execute = AsyncMock(
            side_effect=[
                _FakeResult(scalar=1),
                _FakeResult(scalar=0),
                _FakeResult(scalar=1),
                _FakeResult(scalar=None),
                _FakeResult(scalar=datetime(2026, 2, 10, 1, 2, 3)),
                _FakeResult(scalar=None),
                _FakeResult(scalar=2),
            ]
        )

        before = await get_todoist_sync_status(user_id="usr_dev", db=fake_db)
        assert before.total_mapped == 1
        assert before.error_count == 1
        assert before.last_synced_at is None
        assert before.last_attempt_at is not None
        assert before.last_reconcile_at is None
        assert before.reconcile_error_count == 2

        fake_db_2 = AsyncMock()
        fake_db_2.execute = AsyncMock(
            side_effect=[
                _FakeResult(scalar=1),
                _FakeResult(scalar=0),
                _FakeResult(scalar=0),
                _FakeResult(scalar=datetime(2026, 2, 10, 2, 3, 4)),
                _FakeResult(scalar=datetime(2026, 2, 10, 2, 3, 4)),
                _FakeResult(scalar=datetime(2026, 2, 10, 2, 5, 4)),
                _FakeResult(scalar=0),
            ]
        )
        after = await get_todoist_sync_status(user_id="usr_dev", db=fake_db_2)
        assert after.total_mapped == 1
        assert after.error_count == 0
        assert after.last_synced_at is not None
        assert after.last_attempt_at is not None
        assert after.last_reconcile_at is not None
        assert after.reconcile_error_count == 0

    asyncio.run(_run())
