import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from api.main import app, get_db
from common.models import (
    ConversationDirection,
    ConversationEvent,
    ActionBatch,
    ActionBatchStatus,
    EntityType,
    EventLog,
    RecentContextItem,
    Reminder,
    ReminderKind,
    ReminderStatus,
    ReminderVersion,
    TelegramUserMap,
    VersionOperation,
    WorkItem,
    WorkItemKind,
    WorkItemStatus,
)
from common.planner import build_plan_payload
from worker.main import handle_reminder_dispatch


class _FakeResult:
    def __init__(self, *, items=None, one_or_none=None, scalar=None):
        self._items = items or []
        self._one_or_none = one_or_none
        self._scalar = scalar
        self.rowcount = 1

    def scalars(self):
        return self

    def all(self):
        return self._items

    def scalar_one_or_none(self):
        return self._one_or_none

    def scalar(self):
        return self._scalar


def _session_factory(fake_db):
    @asynccontextmanager
    async def _ctx():
        yield fake_db

    return lambda: _ctx()


def _get(app_instance, url):
    async def _call():
        transport = ASGITransport(app=app_instance)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(url, headers={"Authorization": "Bearer test_token"})

    return asyncio.run(_call())


def _post(app_instance, url, payload, idem="idem-reminder-create"):
    async def _call():
        transport = ASGITransport(app=app_instance)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                url,
                json=payload,
                headers={"Authorization": "Bearer test_token", "Idempotency-Key": idem},
            )

    return asyncio.run(_call())


def _patch(app_instance, url, payload, idem="idem-reminder-update"):
    async def _call():
        transport = ASGITransport(app=app_instance)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.patch(
                url,
                json=payload,
                headers={"Authorization": "Bearer test_token", "Idempotency-Key": idem},
            )

    return asyncio.run(_call())


def test_create_reminder_endpoint_returns_local_reminder_payload(app_no_db, mock_db):
    with patch("api.main.save_idempotency", new=AsyncMock()):
        response = _post(
            app_no_db,
            "/v1/reminders",
            {
                "title": "Follow up with Patrick",
                "remind_at": "2026-03-26T09:30:00+00:00",
                "kind": "follow_up",
                "message": "Check whether he sent the payroll email.",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Follow up with Patrick"
    assert body["kind"] == "follow_up"
    assert body["status"] == "pending"
    assert body["remind_at"] == "2026-03-26T09:30:00+00:00"
    added = [call.args[0] for call in mock_db.add.call_args_list]
    assert any(isinstance(entry, ActionBatch) for entry in added)
    assert any(isinstance(entry, ReminderVersion) and entry.operation == VersionOperation.create for entry in added)


def test_create_reminder_normalizes_recurrence_and_promotes_kind(app_no_db, mock_db):
    with patch("api.main.save_idempotency", new=AsyncMock()):
        response = _post(
            app_no_db,
            "/v1/reminders",
            {
                "title": "Check payroll inbox",
                "remind_at": "2026-03-26T09:30:00+00:00",
                "recurrence_rule": "every weekday",
            },
            idem="idem-reminder-recurrence-create",
        )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "recurring"
    assert body["recurrence_rule"] == "weekdays"


def test_create_reminder_rejects_unsupported_recurrence_rule(app_no_db, mock_db):
    response = _post(
        app_no_db,
        "/v1/reminders",
        {
            "title": "Bad recurrence",
            "remind_at": "2026-03-26T09:30:00+00:00",
            "recurrence_rule": "yearly-ish",
        },
        idem="idem-reminder-recurrence-invalid",
    )

    assert response.status_code == 400
    assert "Unsupported recurrence_rule" in response.text


def test_list_reminders_filters_and_returns_payload(app_no_db, mock_db):
    reminder = Reminder(
        id="rem_1",
        user_id="usr_dev",
        title="Check apartment quote",
        kind=ReminderKind.one_off,
        status=ReminderStatus.pending,
        remind_at=datetime(2026, 3, 26, 14, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc),
    )
    mock_db.execute.side_effect = [_FakeResult(items=[reminder])]

    response = _get(app_no_db, "/v1/reminders?status=pending")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "rem_1"
    assert body[0]["status"] == "pending"


def test_list_reminders_includes_linked_work_item_title(app_no_db, mock_db):
    reminder = Reminder(
        id="rem_1",
        user_id="usr_dev",
        title="Check apartment quote",
        work_item_id="wki_1",
        kind=ReminderKind.one_off,
        status=ReminderStatus.pending,
        remind_at=datetime(2026, 3, 26, 14, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc),
    )
    work_item = WorkItem(
        id="wki_1",
        user_id="usr_dev",
        kind=WorkItemKind.task,
        title="Apartment renovation",
        title_norm="apartment renovation",
        status=WorkItemStatus.open,
    )
    mock_db.execute.side_effect = [_FakeResult(items=[reminder]), _FakeResult(items=[work_item])]

    response = _get(app_no_db, "/v1/reminders?status=pending")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["work_item_title"] == "Apartment renovation"


def test_update_reminder_endpoint_rewrites_status_and_time(app_no_db, mock_db):
    reminder = Reminder(
        id="rem_2",
        user_id="usr_dev",
        title="Call accountant",
        kind=ReminderKind.one_off,
        status=ReminderStatus.pending,
        remind_at=datetime(2026, 3, 26, 14, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc),
    )
    mock_db.execute.side_effect = [_FakeResult(one_or_none=None), _FakeResult(one_or_none=reminder)]

    with patch("api.main.save_idempotency", new=AsyncMock()):
        response = _patch(
            app_no_db,
            "/v1/reminders/rem_2",
            {
                "status": "completed",
                "remind_at": "2026-03-27T10:15:00+00:00",
                "message": "Handled on the phone",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["message"] == "Handled on the phone"
    assert body["remind_at"] == "2026-03-27T10:15:00+00:00"
    added = [call.args[0] for call in mock_db.add.call_args_list]
    assert any(isinstance(entry, ActionBatch) for entry in added)
    assert any(isinstance(entry, ReminderVersion) and entry.operation == VersionOperation.update for entry in added)


def test_update_reminder_clears_recurrence_and_demotes_kind(app_no_db, mock_db):
    reminder = Reminder(
        id="rem_2",
        user_id="usr_dev",
        title="Call accountant",
        kind=ReminderKind.recurring,
        status=ReminderStatus.pending,
        remind_at=datetime(2026, 3, 26, 14, 0, tzinfo=timezone.utc),
        recurrence_rule="weekly",
        created_at=datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc),
    )
    mock_db.execute.side_effect = [_FakeResult(one_or_none=None), _FakeResult(one_or_none=reminder)]

    with patch("api.main.save_idempotency", new=AsyncMock()):
        response = _patch(
            app_no_db,
            "/v1/reminders/rem_2",
            {
                "recurrence_rule": None,
            },
            idem="idem-reminder-clear-recurrence",
        )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "one_off"
    assert body["recurrence_rule"] is None


def test_snooze_reminder_endpoint_moves_reminder_forward_and_reopens_it(app_no_db, mock_db):
    reminder = Reminder(
        id="rem_2",
        user_id="usr_dev",
        title="Call accountant",
        kind=ReminderKind.one_off,
        status=ReminderStatus.sent,
        remind_at=datetime(2026, 3, 26, 14, 0, tzinfo=timezone.utc),
        last_sent_at=datetime(2026, 3, 26, 14, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc),
    )
    mock_db.execute.side_effect = [_FakeResult(one_or_none=None), _FakeResult(one_or_none=reminder)]

    with patch("api.main.utc_now", return_value=datetime(2026, 3, 26, 15, 0, tzinfo=timezone.utc)), patch(
        "api.main.save_idempotency", new=AsyncMock()
    ):
        response = _post(
            app_no_db,
            "/v1/reminders/rem_2/snooze",
            {"preset": "1h"},
            idem="idem-reminder-snooze",
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["remind_at"] == "2026-03-26T16:00:00+00:00"
    added = [call.args[0] for call in mock_db.add.call_args_list]
    assert any(isinstance(entry, ActionBatch) for entry in added)
    assert any(isinstance(entry, ReminderVersion) and entry.operation == VersionOperation.update for entry in added)


def test_snooze_reminder_rejects_unsupported_preset(app_no_db, mock_db):
    reminder = Reminder(
        id="rem_2",
        user_id="usr_dev",
        title="Call accountant",
        kind=ReminderKind.one_off,
        status=ReminderStatus.pending,
        remind_at=datetime(2026, 3, 26, 14, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc),
    )
    mock_db.execute.side_effect = [_FakeResult(one_or_none=None), _FakeResult(one_or_none=reminder)]

    response = _post(
        app_no_db,
        "/v1/reminders/rem_2/snooze",
        {"preset": "someday"},
        idem="idem-reminder-snooze-invalid",
    )

    assert response.status_code == 400
    assert "Unsupported snooze preset" in response.text


def test_list_reminder_versions_returns_recent_versions(app_no_db, mock_db):
    version = ReminderVersion(
        id="rmv_1",
        user_id="usr_dev",
        reminder_id="rem_1",
        action_batch_id="abt_1",
        operation=VersionOperation.update,
        before_json={"status": "pending"},
        after_json={"status": "completed"},
        created_at=datetime(2026, 3, 25, 15, 0, tzinfo=timezone.utc),
    )
    mock_db.execute.side_effect = [_FakeResult(items=[version])]

    response = _get(app_no_db, "/v1/reminders/rem_1/versions")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "rmv_1",
            "user_id": "usr_dev",
            "reminder_id": "rem_1",
            "action_batch_id": "abt_1",
            "operation": "update",
            "before_json": {"status": "pending"},
            "after_json": {"status": "completed"},
            "created_at": "2026-03-25T15:00:00+00:00",
        }
    ]


def test_undo_action_batch_restores_reminder_snapshot(app_no_db, mock_db):
    batch = ActionBatch(
        id="abt_reminder",
        user_id="usr_dev",
        source_message="Complete reminder",
        status=ActionBatchStatus.applied,
        proposal_json={"reminders": [{"target_reminder_id": "rem_1"}]},
        applied_item_ids_json=["rem_1"],
        undo_window_expires_at=datetime(2026, 3, 26, 18, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 25, 18, 0, tzinfo=timezone.utc),
    )
    version = ReminderVersion(
        id="rmv_restore",
        user_id="usr_dev",
        reminder_id="rem_1",
        action_batch_id="abt_reminder",
        operation=VersionOperation.update,
        before_json={
            "title": "Call accountant",
            "status": "pending",
            "kind": "one_off",
            "remind_at": "2026-03-26T14:00:00+00:00",
        },
        after_json={
            "title": "Call accountant",
            "status": "completed",
            "kind": "one_off",
            "remind_at": "2026-03-26T14:00:00+00:00",
        },
        created_at=datetime(2026, 3, 25, 18, 1, tzinfo=timezone.utc),
    )
    reminder = Reminder(
        id="rem_1",
        user_id="usr_dev",
        title="Call accountant",
        kind=ReminderKind.one_off,
        status=ReminderStatus.completed,
        remind_at=datetime(2026, 3, 26, 14, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 3, 25, 18, 0, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 25, 18, 0, tzinfo=timezone.utc),
    )
    mock_db.execute.side_effect = [
        _FakeResult(one_or_none=None),
        _FakeResult(one_or_none=batch),
        _FakeResult(items=[]),
        _FakeResult(items=[version]),
        _FakeResult(one_or_none=reminder),
    ]

    with patch("api.main.save_idempotency", new=AsyncMock()):
        response = _post(app_no_db, "/v1/history/action_batches/abt_reminder/undo", {}, idem="idem-reminder-undo")

    assert response.status_code == 200
    body = response.json()
    assert body["reverted_batch_id"] == "abt_reminder"
    assert body["restored_item_ids"] == ["rem_1"]
    assert reminder.status == ReminderStatus.pending
    added = [call.args[0] for call in mock_db.add.call_args_list]
    assert any(isinstance(entry, ReminderVersion) and entry.operation == VersionOperation.restore for entry in added)


def test_dispatch_due_reminders_endpoint_enqueues_worker_job(app_no_db, mock_redis):
    async def _override_get_db():
        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(return_value=_FakeResult(one_or_none=None))
        yield fake_db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with patch("api.main.redis_client", mock_redis), patch("api.main.save_idempotency", new=AsyncMock()):
            response = _post(app_no_db, "/v1/reminders/dispatch_due", {}, idem="idem-reminder-dispatch")
        assert response.status_code == 200
        assert response.json()["enqueued"] is True
        _, raw = mock_redis.rpush.await_args.args
        assert '"topic": "reminders.dispatch"' in raw
    finally:
        app.dependency_overrides.clear()


def test_handle_reminder_dispatch_sends_due_pending_reminders():
    async def _run():
        reminder = Reminder(
            id="rem_due",
            user_id="usr_dev",
            title="Follow up with Patrick",
            message="Check whether he replied.",
            kind=ReminderKind.follow_up,
            status=ReminderStatus.pending,
            remind_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mapping = TelegramUserMap(
            id="tgm_1",
            chat_id="791013684",
            user_id="usr_dev",
            telegram_username="frank",
            linked_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(
            side_effect=[
                _FakeResult(items=[reminder]),
                _FakeResult(one_or_none=mapping),
            ]
        )
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)), patch(
            "worker.main.send_message", new=AsyncMock(return_value={"ok": True})
        ) as send:
            await handle_reminder_dispatch("job_reminders", {"user_id": "usr_dev"})

        send.assert_awaited_once()
        assert send.await_args.args[0] == "791013684"
        assert "Follow up with Patrick" in send.await_args.args[1]
        assert reminder.status == ReminderStatus.sent
        event_types = [call.args[0].event_type for call in fake_db.add.call_args_list if isinstance(call.args[0], EventLog)]
        assert "reminder_dispatched" in event_types
        assert "reminder_dispatch_completed" in event_types
        conversation_events = [call.args[0] for call in fake_db.add.call_args_list if isinstance(call.args[0], ConversationEvent)]
        assert len(conversation_events) == 1
        assert conversation_events[0].direction == ConversationDirection.outbound
        assert conversation_events[0].chat_id == "791013684"
        context_items = [call.args[0] for call in fake_db.add.call_args_list if isinstance(call.args[0], RecentContextItem)]
        assert len(context_items) == 1
        assert context_items[0].entity_type == EntityType.reminder
        assert context_items[0].entity_id == "rem_due"

    asyncio.run(_run())


def test_handle_reminder_dispatch_reschedules_recurring_reminder():
    async def _run():
        reminder = Reminder(
            id="rem_weekly",
            user_id="usr_dev",
            title="Review payroll inbox",
            message="Look for Patrick's update.",
            kind=ReminderKind.recurring,
            status=ReminderStatus.pending,
            remind_at=datetime(2026, 3, 25, 15, 0, tzinfo=timezone.utc),
            recurrence_rule="weekly",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        mapping = TelegramUserMap(
            id="tgm_1",
            chat_id="791013684",
            user_id="usr_dev",
            telegram_username="frank",
            linked_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(
            side_effect=[
                _FakeResult(items=[reminder]),
                _FakeResult(one_or_none=mapping),
            ]
        )
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)), patch(
            "worker.main.send_message", new=AsyncMock(return_value={"ok": True})
        ) as send:
            await handle_reminder_dispatch("job_reminders", {"user_id": "usr_dev"})

        send.assert_awaited_once()
        assert reminder.status == ReminderStatus.pending
        assert reminder.remind_at == datetime(2026, 4, 1, 15, 0, tzinfo=timezone.utc)
        event_payloads = [
            call.args[0].payload_json
            for call in fake_db.add.call_args_list
            if isinstance(call.args[0], EventLog) and call.args[0].event_type == "reminder_dispatched"
        ]
        assert event_payloads[0]["recurrence_rule"] == "weekly"
        assert event_payloads[0]["next_remind_at"] == "2026-04-01T15:00:00+00:00"

    asyncio.run(_run())


def test_handle_reminder_dispatch_skips_when_no_linked_chat():
    async def _run():
        reminder = Reminder(
            id="rem_due",
            user_id="usr_dev",
            title="Pay insurance bill",
            kind=ReminderKind.one_off,
            status=ReminderStatus.pending,
            remind_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        fake_db = AsyncMock()
        fake_db.execute = AsyncMock(
            side_effect=[
                _FakeResult(items=[reminder]),
                _FakeResult(one_or_none=None),
            ]
        )
        fake_db.commit = AsyncMock()
        fake_db.add = MagicMock()

        with patch("worker.main.AsyncSessionLocal", _session_factory(fake_db)), patch(
            "worker.main.send_message", new=AsyncMock(return_value={"ok": True})
        ) as send:
            await handle_reminder_dispatch("job_reminders", {"user_id": "usr_dev"})

        send.assert_not_awaited()
        assert reminder.status == ReminderStatus.pending
        event_types = [call.args[0].event_type for call in fake_db.add.call_args_list if isinstance(call.args[0], EventLog)]
        assert "reminder_dispatch_skipped_no_chat" in event_types
        assert "reminder_dispatch_completed" in event_types

    asyncio.run(_run())


def test_build_plan_payload_includes_due_reminders_for_today():
    now = datetime(2026, 3, 25, 14, 0, tzinfo=timezone.utc)
    payload = build_plan_payload(
        {
            "tasks": [],
            "links": [],
            "reminders": [
                Reminder(
                    id="rem_due",
                    user_id="usr_dev",
                    title="Follow up with Patrick",
                    kind=ReminderKind.follow_up,
                    status=ReminderStatus.pending,
                    remind_at=datetime(2026, 3, 25, 16, 0, tzinfo=timezone.utc),
                    created_at=now,
                    updated_at=now,
                ),
                Reminder(
                    id="rem_future",
                    user_id="usr_dev",
                    title="Call accountant tomorrow",
                    kind=ReminderKind.one_off,
                    status=ReminderStatus.pending,
                    remind_at=datetime(2026, 3, 26, 16, 0, tzinfo=timezone.utc),
                    created_at=now,
                    updated_at=now,
                ),
            ],
        },
        now,
    )
    assert payload["due_reminders"] == [
        {
            "reminder_id": "rem_due",
            "title": "Follow up with Patrick",
            "message": None,
            "remind_at": "2026-03-25T16:00:00Z",
            "work_item_id": None,
        }
    ]


def test_build_plan_payload_excludes_future_dated_tasks_from_today_plan():
    now = datetime(2026, 3, 26, 4, 0, tzinfo=timezone.utc)
    payload = build_plan_payload(
        {
            "tasks": [
                WorkItem(
                    id="tsk_future",
                    user_id="usr_dev",
                    kind=WorkItemKind.task,
                    title="Submit Worker's Compensation form for employee",
                    title_norm="submit workers compensation form for employee",
                    status=WorkItemStatus.open,
                    due_at=datetime(2026, 3, 31, 14, 0, tzinfo=timezone.utc),
                    updated_at=now,
                ),
                WorkItem(
                    id="tsk_open",
                    user_id="usr_dev",
                    kind=WorkItemKind.task,
                    title="Process photos from the last tournament",
                    title_norm="process photos from the last tournament",
                    status=WorkItemStatus.open,
                    updated_at=now,
                ),
            ],
            "links": [],
            "reminders": [],
        },
        now,
    )
    task_ids = [item["task_id"] for item in payload["today_plan"]]
    assert "tsk_open" in task_ids
    assert "tsk_future" not in task_ids


def test_build_plan_payload_excludes_subtask_when_parent_is_deferred():
    now = datetime(2026, 3, 26, 4, 0, tzinfo=timezone.utc)
    payload = build_plan_payload(
        {
            "tasks": [
                WorkItem(
                    id="tsk_parent",
                    user_id="usr_dev",
                    kind=WorkItemKind.task,
                    title="Research 401k requirements",
                    title_norm="research 401k requirements",
                    status=WorkItemStatus.open,
                    due_at=datetime(2026, 3, 31, 14, 0, tzinfo=timezone.utc),
                    updated_at=now,
                ),
                WorkItem(
                    id="tsk_child",
                    user_id="usr_dev",
                    kind=WorkItemKind.subtask,
                    parent_id="tsk_parent",
                    title="Review Neil's list",
                    title_norm="review neil s list",
                    status=WorkItemStatus.open,
                    updated_at=now,
                ),
                WorkItem(
                    id="tsk_other",
                    user_id="usr_dev",
                    kind=WorkItemKind.task,
                    title="Process photos from the last tournament",
                    title_norm="process photos from the last tournament",
                    status=WorkItemStatus.open,
                    updated_at=now,
                ),
            ],
            "links": [],
            "reminders": [],
        },
        now,
    )
    task_ids = [item["task_id"] for item in payload["today_plan"]]
    assert "tsk_other" in task_ids
    assert "tsk_parent" not in task_ids
    assert "tsk_child" not in task_ids
