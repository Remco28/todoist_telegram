"""Phase 4 Telegram webhook tests (spec cases 1-9) with stable boundaries.

These tests validate:
- webhook auth/ingest behavior
- command parsing/routing
- command semantics via handle_telegram_command
- non-command capture integration path
"""
import asyncio
import json
from datetime import datetime, date, timezone
from typing import Optional
from unittest.mock import AsyncMock, Mock, patch

from httpx import ASGITransport, AsyncClient

from api.main import (
    handle_telegram_command,
    _apply_capture,
    _build_extraction_grounding,
    _best_reminder_reference_candidate,
    _best_task_reference_candidate,
    _confirm_action_draft,
    _draft_set_awaiting_edit_input,
    _draft_set_proposal_message_id,
    _format_action_draft_preview,
    _remember_recent_reminders,
    _reminder_reference_candidates,
    _validate_extraction_payload,
)
from api.schemas import AppliedChanges, QueryResponseV1
from common.config import settings
from common.legacy_models import Task, TaskStatus
from common.models import (
    ActionBatch,
    ConversationEvent,
    EntityType,
    RecentContextItem,
    Reminder,
    ReminderKind,
    ReminderStatus,
    ReminderVersion,
    WorkItem,
    WorkItemKind,
    WorkItemStatus,
    WorkItemVersion,
)

WEBHOOK_URL = "/v1/integrations/telegram/webhook"
VALID_SECRET = "test_secret"


def _tg_update(text, chat_id="12345"):
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": int(chat_id), "type": "private", "username": "testuser"},
            "text": text,
            "date": int(datetime.now(timezone.utc).timestamp()),
        },
    }

def _tg_callback_update(data, chat_id="12345"):
    return {
        "update_id": 2,
        "callback_query": {
            "id": "cbq_1",
            "from": {"id": 42, "username": "testuser"},
            "message": {"message_id": 9, "chat": {"id": int(chat_id), "type": "private"}},
            "data": data,
        },
    }


def _headers(secret=VALID_SECRET):
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret
    return headers


def _fake_draft(
    *,
    draft_id: str = "drf_1",
    chat_id: str = "12345",
    source_message: str = "draft source",
    proposal_json: Optional[dict] = None,
):
    return type(
        "Draft",
        (),
        {
            "id": draft_id,
            "chat_id": chat_id,
            "source_message": source_message,
            "proposal_json": proposal_json or {"tasks": [], "goals": [], "problems": [], "links": [], "reminders": []},
            "updated_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc),
        },
    )()


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


def test_webhook_ignores_disallowed_sender(app_no_db, mock_send):
    old_chat_ids = settings.TELEGRAM_ALLOWED_CHAT_IDS
    old_usernames = settings.TELEGRAM_ALLOWED_USERNAMES
    settings.TELEGRAM_ALLOWED_CHAT_IDS = "999999"
    settings.TELEGRAM_ALLOWED_USERNAMES = "allowed_user"
    try:
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("hello", chat_id="12345"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
        mock_send.assert_not_awaited()
    finally:
        settings.TELEGRAM_ALLOWED_CHAT_IDS = old_chat_ids
        settings.TELEGRAM_ALLOWED_USERNAMES = old_usernames


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


def test_greeting_message_returns_brief_reply(app_no_db, mock_send, mock_extract):
    mock_extract.interpret_telegram_turn.return_value = {
        "speech_act": "smalltalk",
        "assistant_reply": "Hi.",
        "confidence": 0.9,
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock
    ) as build_grounding:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("Hello"), headers=_headers())
        assert resp.status_code == 200
        build_grounding.assert_not_awaited()
    text = mock_send.await_args.args[1]
    assert text.startswith("Hi.")
    assert "Answer" not in text
    assert "Current open tasks include" not in text


def test_natural_language_today_query_uses_planner_view(app_no_db, mock_send, mock_db, mock_extract):
    mock_extract.interpret_telegram_turn.return_value = {
        "speech_act": "query",
        "view_name": "today",
        "confidence": 0.9,
    }
    state = {
        "tasks": [
            Task(
                id="tsk_today_1",
                user_id="usr_123",
                title="Complete urgent Worker's Compensation form",
                title_norm="complete urgent workers compensation form",
                status=TaskStatus.open,
                updated_at=datetime(2026, 3, 19, 8, 0, 0),
            )
        ],
        "goals": [],
        "links": [],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.collect_planning_state", new_callable=AsyncMock, return_value=state
    ), patch(
        "api.main._remember_displayed_tasks", new_callable=AsyncMock
    ) as remember, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock
    ) as build_grounding:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("What do I have to do today?"), headers=_headers())
        assert resp.status_code == 200
        build_grounding.assert_not_awaited()
    text = mock_send.await_args.args[1]
    assert "Your Today Plan" in text
    assert "Complete urgent Worker" in text
    remember.assert_awaited_once_with(mock_db, "usr_123", "12345", ["tsk_today_1"], "today")


def test_natural_language_due_today_query_uses_deterministic_due_today_view(app_no_db, mock_extract):
    mock_extract.interpret_telegram_turn.return_value = {
        "speech_act": "query",
        "view_name": "due_today",
        "confidence": 0.9,
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main._send_due_today_view", new_callable=AsyncMock
    ) as send_due_today, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock
    ) as build_grounding:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("What is due today?"), headers=_headers())
        assert resp.status_code == 200
        send_due_today.assert_awaited_once()
        build_grounding.assert_not_awaited()


def test_natural_language_due_next_week_query_uses_deterministic_view(app_no_db, mock_extract):
    mock_extract.interpret_telegram_turn.return_value = {
        "speech_act": "query",
        "view_name": "due_next_week",
        "confidence": 0.9,
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main._send_due_next_week_view", new_callable=AsyncMock
    ) as send_due_next_week, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock
    ) as build_grounding:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("What is due next week?"), headers=_headers())
        assert resp.status_code == 200
        send_due_next_week.assert_awaited_once()
        build_grounding.assert_not_awaited()


def test_multiline_for_today_list_prefers_action_capture_over_today_view(app_no_db, mock_extract):
    mock_extract.interpret_telegram_turn.return_value = {
        "speech_act": "query",
        "view_name": "today",
        "confidence": 0.87,
    }
    mock_extract.plan_actions.return_value = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.93,
        "needs_confirmation": True,
        "actions": [
            {"entity_type": "task", "action": "create", "title": "Pack for tournament"},
            {"entity_type": "task", "action": "create", "title": "Get Amy the tax documents"},
            {"entity_type": "task", "action": "create", "title": "Wash my car"},
        ],
    }
    message = "For today:\n\nPack for tournament\n\nGet Amy the tax documents\n\nWash my car"
    grounding = {
        "tasks": [],
        "goals": [],
        "problems": [],
        "links": [],
        "reminders": [],
        "current_date_local": "2026-03-26",
        "timezone": "America/New_York",
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ) as build_grounding, patch(
        "api.main._send_today_plan_view", new_callable=AsyncMock
    ) as send_today, patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=_fake_draft()
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update(message), headers=_headers())
        assert resp.status_code == 200
        send_today.assert_not_awaited()
        assert build_grounding.await_count == 1
        create_draft.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert [task["title"] for task in extraction["tasks"]] == [
            "Pack for tournament",
            "Get Amy the tax documents",
            "Wash my car",
        ]
        send_preview.assert_awaited_once()


def test_build_extraction_grounding_keeps_displayed_parent_project(mock_db):
    now = datetime(2026, 3, 26, 5, 0, tzinfo=timezone.utc)
    project = WorkItem(
        id="prj_webapps",
        user_id="usr_123",
        kind=WorkItemKind.project,
        title="Web apps optimization checklist for Hetzner server",
        title_norm="web apps optimization checklist for hetzner server",
        status=WorkItemStatus.open,
        updated_at=now,
    )
    recent_ctx = RecentContextItem(
        id="rci_1",
        user_id="usr_123",
        chat_id="12345",
        entity_type=EntityType.work_item,
        entity_id="prj_webapps",
        reason="task_display:today:batch123:1",
        surfaced_at=now,
        expires_at=now,
    )

    task_result = Mock()
    task_scalars = Mock()
    task_scalars.all.return_value = [project]
    task_result.scalars.return_value = task_scalars

    recent_result = Mock()
    recent_scalars = Mock()
    recent_scalars.all.return_value = [recent_ctx]
    recent_result.scalars.return_value = recent_scalars

    recent_task_result = Mock()
    recent_task_scalars = Mock()
    recent_task_scalars.all.return_value = [project]
    recent_task_result.scalars.return_value = recent_task_scalars

    reminder_recent_result = Mock()
    reminder_recent_scalars = Mock()
    reminder_recent_scalars.all.return_value = []
    reminder_recent_result.scalars.return_value = reminder_recent_scalars

    reminder_result = Mock()
    reminder_scalars = Mock()
    reminder_scalars.all.return_value = []
    reminder_result.scalars.return_value = reminder_scalars

    mock_db.execute.side_effect = [
        task_result,
        recent_result,
        recent_task_result,
        reminder_recent_result,
        reminder_result,
    ]

    grounding = asyncio.run(
        _build_extraction_grounding(
            db=mock_db,
            user_id="usr_123",
            chat_id="12345",
            message="move the web apps optimization to tomorrow",
        )
    )

    assert any(item["id"] == "prj_webapps" for item in grounding["tasks"])
    assert grounding["displayed_task_refs"] == [
        {
            "ordinal": 1,
            "id": "prj_webapps",
            "title": "Web apps optimization checklist for Hetzner server",
            "status": "open",
            "view_name": "today",
            "parent_title": None,
        }
    ]


def test_natural_language_open_tasks_query_uses_deterministic_view(app_no_db, mock_extract):
    mock_extract.interpret_telegram_turn.return_value = {
        "speech_act": "query",
        "view_name": "open_tasks",
        "confidence": 0.9,
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main._send_open_task_view", new_callable=AsyncMock
    ) as send_open, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock
    ) as build_grounding:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("List open tasks"), headers=_headers())
        assert resp.status_code == 200
        send_open.assert_awaited_once()
        build_grounding.assert_not_awaited()


def test_non_command_text_low_confidence_requests_clarification(app_no_db, mock_extract, mock_send):
    mock_extract.extract_structured_updates.return_value = {
        "tasks": [{"title": "Task A"}],
        "goals": [{"title": "Goal A"}],
        "problems": [{"title": "Problem A"}],
        "links": [],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding",
        new_callable=AsyncMock,
        return_value={"tasks": [{"id": "tsk_2", "title": "Buy paint rollers", "status": "open"}]},
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main._apply_capture", new_callable=AsyncMock
    ) as apply_capture:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("plain text"), headers=_headers())
        assert resp.status_code == 200
        create_draft.assert_not_awaited()
        apply_capture.assert_not_awaited()
        mock_send.assert_awaited_once()
        assert "i need one clarification before applying changes" in mock_send.await_args.args[1].lower()


def test_non_command_capture_dedup_updates_task_count(app_no_db, mock_send):
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding",
        new_callable=AsyncMock,
        return_value={"tasks": [{"id": "tsk_2", "title": "Buy paint rollers", "status": "open"}]},
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main._apply_capture", new_callable=AsyncMock
    ) as apply_capture:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("buy groceries"), headers=_headers())
        assert resp.status_code == 200
        create_draft.assert_not_awaited()
        apply_capture.assert_not_awaited()
        mock_send.assert_awaited_once()
        assert "did not find clear actions" in mock_send.await_args.args[1].lower()


def test_non_command_bulk_done_without_actionable_plan_requests_clarification(app_no_db, mock_extract, mock_send):
    mock_extract.plan_actions.return_value = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.6,
        "needs_confirmation": True,
        "actions": [],
    }
    mock_extract.extract_structured_updates.return_value = {
        "tasks": [
            {"title": "Replace bathroom fan", "action": "complete"},
            {"title": "Buy paint rollers", "action": "complete"},
        ],
        "goals": [],
        "problems": [],
        "links": [],
    }
    grounding = {
        "tasks": [
            {"id": "tsk_1", "title": "Replace bathroom fan", "status": "open"},
            {"id": "tsk_2", "title": "Buy paint rollers", "status": "blocked"},
            {"id": "tsk_3", "title": "Old finished task", "status": "done"},
        ]
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ):
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("Let's mark everything as done."), headers=_headers())
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {"title": "Replace bathroom fan", "action": "complete", "status": "done", "target_task_id": "tsk_1"},
            {"title": "Buy paint rollers", "action": "complete", "status": "done", "target_task_id": "tsk_2"},
        ]


def test_non_command_reference_completion_without_actionable_plan_requests_clarification(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.6,
        "needs_confirmation": True,
        "actions": [],
    }
    grounding = {
        "tasks": [
            {"id": "tsk_1", "title": "Do French homework", "status": "open"},
            {"id": "tsk_2", "title": "Memorize a script", "status": "open"},
            {"id": "tsk_3", "title": "Read a chapter and annotate it", "status": "open"},
        ],
        "recent_task_refs": [
            {"id": "tsk_1", "title": "Do French homework", "status": "open"},
            {"id": "tsk_2", "title": "Memorize a script", "status": "open"},
            {"id": "tsk_3", "title": "Read a chapter and annotate it", "status": "open"},
            {"id": "tsk_4", "title": "Renew New York Public library card", "status": "open"},
            {"id": "tsk_5", "title": "Take Amy's car for a car wash", "status": "open"},
        ],
    }
    fake_draft = _fake_draft(
        source_message="Reading the chapter, memorizing the script, and the french homework are all done. Mark them as complete.",
        proposal_json={"tasks": [], "goals": [], "problems": [], "links": []},
    )
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={
            "tasks": [
                {"title": "Read a chapter and annotate it", "action": "complete"},
                {"title": "Memorize a script", "action": "complete"},
                {"title": "Do French homework", "action": "complete"},
            ],
            "goals": [],
            "problems": [],
            "links": [],
        },
    ) as extract_fallback:
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Reading the chapter, memorizing the script, and the french homework are all done. Mark them as complete."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert {task["target_task_id"] for task in extraction["tasks"]} == {"tsk_1", "tsk_2", "tsk_3"}


def test_non_command_uses_planner_actions_as_primary_path(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.88,
        "needs_confirmation": True,
        "actions": [
            {
                "entity_type": "task",
                "action": "create",
                "title": "Call contractor",
                "notes": "Ask for itemized quote",
                "priority": 2,
                "impact_score": 4,
                "urgency_score": 3,
                "due_date": "2026-02-12",
            },
            {"entity_type": "task", "action": "complete", "title": "Buy paint rollers", "target_task_id": "tsk_2"},
        ],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding",
        new_callable=AsyncMock,
        return_value={"tasks": [{"id": "tsk_2", "title": "Buy paint rollers", "status": "open"}]},
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates", new_callable=AsyncMock
    ) as extract_fallback:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("Renovation update"), headers=_headers())
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        extract_fallback.assert_not_awaited()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert len(extraction["tasks"]) == 2
        assert extraction["tasks"][0]["title"] == "Call contractor"
        assert extraction["tasks"][0]["notes"] == "Ask for itemized quote"
        assert extraction["tasks"][0]["impact_score"] == 4
        assert extraction["tasks"][0]["urgency_score"] == 3
        assert extraction["tasks"][0]["due_date"] == "2026-02-12"
        assert extraction["tasks"][1]["action"] == "complete"


def test_non_command_marketplace_text_does_not_trigger_completion_mode(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.98,
        "needs_confirmation": True,
        "actions": [
            {
                "entity_type": "task",
                "action": "create",
                "title": "Give away cigars on Facebook Marketplace",
                "notes": "Set price to free; not urgent.",
            }
        ],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value={"tasks": []}
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ):
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update(
                "give away my cigars. facebook marketplace or something. set price to free. it's taking up space. it's not urgent. i want it done eventually..."
            ),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert len(extraction["tasks"]) == 1
        assert extraction["tasks"][0]["action"] == "create"
        assert extraction["tasks"][0]["title"] == "Give away cigars on Facebook Marketplace"


def test_non_command_unresolved_mutation_requests_clarification(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.93,
        "needs_confirmation": True,
        "actions": [{"entity_type": "task", "action": "update", "title": "Respond to Gil tonight"}],
    }
    fake_draft = _fake_draft(
        source_message="Update my reminder for Gil",
        proposal_json={"tasks": [{"title": "Respond to Gil tonight", "action": "update"}], "goals": [], "problems": [], "links": []},
    )
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value={"tasks": []}
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main._apply_capture", new_callable=AsyncMock
    ) as apply_capture:
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Update my reminder for Gil"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        apply_capture.assert_not_awaited()
        assert mock_send.await_count >= 1
        msg = mock_send.await_args_list[-1].args[1]
        assert "I need one clarification before applying changes" in msg
        assert "Which existing task do you mean" in msg


def test_non_command_planner_invalid_uses_extract_fallback(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.4,
        "needs_confirmation": True,
        "actions": [],
    }
    extracted = {
        "tasks": [{"title": "Follow up with accountant", "action": "create"}],
        "goals": [],
        "problems": [],
        "links": [],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value={"tasks": []}
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates", new_callable=AsyncMock, return_value=extracted
    ) as extract_fallback:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("Add a reminder to call accountant"), headers=_headers())
        assert resp.status_code == 200
        create_draft.assert_not_awaited()
        extract_fallback.assert_awaited_once()
        assert "i need one clarification before applying changes" in mock_send.await_args.args[1].lower()


def test_non_command_planner_unusable_actions_uses_extract_fallback(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.92,
        "needs_confirmation": True,
        "actions": [{"entity_type": "task", "action": "create", "target_task_id": "tsk_missing_title"}],
    }
    extracted = {
        "tasks": [{"title": "Return Nico's library books to NYPL", "action": "create", "due_date": "2026-02-12"}],
        "goals": [],
        "problems": [],
        "links": [],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value={"tasks": []}
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates", new_callable=AsyncMock, return_value=extracted
    ) as extract_fallback:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("Return Nico's library books to NYPL tomorrow"), headers=_headers())
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        extract_fallback.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"][0]["title"] == "Return Nico's library books to NYPL"


def test_extract_fallback_skips_planner_critic_and_stages_valid_task_update(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.95,
        "needs_confirmation": True,
        "actions": [{"entity_type": "task", "action": "update", "target_task_id": "tsk_missing_title"}],
    }
    extracted = {
        "tasks": [
            {
                "title": "Set up Doris's new workstation",
                "action": "update",
                "target_task_id": "tsk_doris",
                "due_date": "2026-04-01",
            }
        ],
        "goals": [],
        "problems": [],
        "links": [],
    }
    fake_draft = _fake_draft(
        source_message="Please change that to Wednesday instead.",
        proposal_json={"tasks": [], "goals": [], "problems": [], "links": []},
    )
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding",
        new_callable=AsyncMock,
        return_value={
            "tasks": [{"id": "tsk_doris", "title": "Set up Doris's new workstation", "status": "open"}],
            "recent_task_refs": [{"id": "tsk_doris", "title": "Set up Doris's new workstation", "status": "open"}],
        },
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions",
        new_callable=AsyncMock,
        return_value={"approved": False, "issues": ["Bad planner proposal"]},
    ) as critique_actions, patch(
        "api.main.adapter.extract_structured_updates", new_callable=AsyncMock, return_value=extracted
    ) as extract_fallback:
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Please change that to Wednesday instead."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        extract_fallback.assert_awaited_once()
        critique_actions.assert_not_awaited()
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "Set up Doris's new workstation",
                "action": "update",
                "target_task_id": "tsk_doris",
                "due_date": "2026-04-01",
            }
        ]


def test_extract_fallback_recovers_due_date_update_from_recent_today_task(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.99,
        "needs_confirmation": True,
        "actions": [{"entity_type": "task", "action": "update", "target_task_id": "tsk_missing_title"}],
    }
    fake_draft = _fake_draft(
        source_message="can you move the photo processing task to tomorrow?",
        proposal_json={"tasks": [], "goals": [], "problems": [], "links": []},
    )
    grounding = {
        "tasks": [
            {"id": "tsk_photos", "title": "Process photos from the last tournament", "status": "open"},
            {"id": "tsk_other", "title": "Review Neil's list", "status": "open"},
        ],
        "recent_task_refs": [
            {"id": "tsk_photos", "title": "Process photos from the last tournament", "status": "open"},
            {"id": "tsk_other", "title": "Review Neil's list", "status": "open"},
        ],
        "displayed_task_refs": [
            {"ordinal": 1, "id": "tsk_photos", "title": "Process photos from the last tournament", "status": "open", "view_name": "today"},
            {"ordinal": 5, "id": "tsk_other", "title": "Review Neil's list", "status": "open", "view_name": "today"},
        ],
    }
    with patch("api.main._local_today", return_value=date(2026, 3, 25)), patch(
        "api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"
    ), patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock
    ) as critique_actions, patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={"tasks": [], "goals": [], "problems": [], "links": [], "reminders": []},
    ) as extract_fallback:
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("can you move the photo processing task to tomorrow?"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        extract_fallback.assert_awaited_once()
        critique_actions.assert_not_awaited()
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "Process photos from the last tournament",
                "action": "update",
                "target_task_id": "tsk_photos",
                "due_date": "2026-03-26",
            }
        ]


def test_extract_fallback_recovers_due_date_update_from_displayed_parent_project(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.99,
        "needs_confirmation": True,
        "actions": [{"entity_type": "task", "action": "update", "target_task_id": "tsk_missing_title"}],
    }
    fake_draft = _fake_draft(
        source_message="move the web apps optimization to tomorrow",
        proposal_json={"tasks": [], "goals": [], "problems": [], "links": []},
    )
    grounding = {
        "tasks": [
            {
                "id": "prj_webapps",
                "title": "Web apps optimization checklist for Hetzner server",
                "status": "open",
            },
        ],
        "recent_task_refs": [
            {
                "id": "prj_webapps",
                "title": "Web apps optimization checklist for Hetzner server",
                "status": "open",
            },
        ],
        "displayed_task_refs": [
            {
                "ordinal": 3,
                "id": "prj_webapps",
                "title": "Web apps optimization checklist for Hetzner server",
                "status": "open",
                "view_name": "today",
            },
        ],
    }
    with patch("api.main._local_today", return_value=date(2026, 3, 26)), patch(
        "api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"
    ), patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock
    ) as critique_actions, patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={"tasks": [], "goals": [], "problems": [], "links": [], "reminders": []},
    ) as extract_fallback:
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("move the web apps optimization to tomorrow"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        extract_fallback.assert_awaited_once()
        critique_actions.assert_not_awaited()
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "Web apps optimization checklist for Hetzner server",
                "action": "update",
                "target_task_id": "prj_webapps",
                "due_date": "2026-03-27",
            }
        ]


def test_extract_fallback_recovers_due_date_update_from_displayed_ordinal_reference(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.99,
        "needs_confirmation": True,
        "actions": [{"entity_type": "task", "action": "update", "target_task_id": "tsk_missing_title"}],
    }
    fake_draft = _fake_draft(
        source_message="move second one to tomorrow",
        proposal_json={"tasks": [], "goals": [], "problems": [], "links": []},
    )
    grounding = {
        "tasks": [
            {"id": "wki_401k", "title": "Finish registering the 401k account", "status": "open"},
            {"id": "tsk_photos", "title": "Process photos from the last tournament", "status": "open"},
        ],
        "recent_task_refs": [
            {"id": "wki_401k", "title": "Finish registering the 401k account", "status": "open"},
            {"id": "tsk_photos", "title": "Process photos from the last tournament", "status": "open"},
        ],
        "displayed_task_refs": [
            {"ordinal": 1, "id": "wki_401k", "title": "Finish registering the 401k account", "status": "open", "view_name": "today"},
            {"ordinal": 2, "id": "tsk_photos", "title": "Process photos from the last tournament", "status": "open", "view_name": "today"},
        ],
    }
    with patch("api.main._local_today", return_value=date(2026, 3, 26)), patch(
        "api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"
    ), patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock
    ) as critique_actions, patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={"tasks": [], "goals": [], "problems": [], "links": [], "reminders": []},
    ) as extract_fallback:
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("move second one to tomorrow"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        extract_fallback.assert_awaited_once()
        critique_actions.assert_not_awaited()
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "Process photos from the last tournament",
                "action": "update",
                "target_task_id": "tsk_photos",
                "due_date": "2026-03-27",
            }
        ]


def test_extract_fallback_recovers_completion_from_recent_visible_task_statement(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 1.0,
        "needs_confirmation": True,
        "actions": [{"entity_type": "task", "action": "complete", "target_task_id": "tsk_missing_title"}],
    }
    fake_draft = _fake_draft(
        source_message="I got Amy the tax documents, done!",
        proposal_json={"tasks": [], "goals": [], "problems": [], "links": []},
    )
    grounding = {
        "tasks": [
            {"id": "tsk_amy_docs", "title": "Get Amy the tax documents", "status": "open"},
            {"id": "tsk_other", "title": "Pack for tournament", "status": "open"},
        ],
        "recent_task_refs": [
            {"id": "tsk_amy_docs", "title": "Get Amy the tax documents", "status": "open"},
            {"id": "tsk_other", "title": "Pack for tournament", "status": "open"},
        ],
        "displayed_task_refs": [
            {"ordinal": 3, "id": "tsk_amy_docs", "title": "Get Amy the tax documents", "status": "open", "view_name": "today"},
            {"ordinal": 4, "id": "tsk_other", "title": "Pack for tournament", "status": "open", "view_name": "today"},
        ],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ) as create_draft, patch(
        "api.main._apply_capture", new_callable=AsyncMock
    ) as apply_capture, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock
    ) as critique_actions, patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={"tasks": [], "goals": [], "problems": [], "links": [], "reminders": []},
    ) as extract_fallback:
        apply_capture.return_value = ("inb_amy", AppliedChanges(tasks_updated=1))
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("I got Amy the tax documents, done!"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        extract_fallback.assert_awaited_once()
        critique_actions.assert_not_awaited()
        create_draft.assert_not_awaited()
        send_preview.assert_not_awaited()
        apply_capture.assert_awaited_once()
        extraction = apply_capture.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "Get Amy the tax documents",
                "action": "complete",
                "status": "done",
                "target_task_id": "tsk_amy_docs",
            }
        ]


def test_extract_fallback_recovers_same_day_due_alignment_from_recent_reference(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.99,
        "needs_confirmation": True,
        "actions": [{"entity_type": "task", "action": "complete", "target_task_id": "tsk_vanguard"}],
    }
    fake_draft = _fake_draft(
        source_message="That should be done the same day as the Vanguard account.",
        proposal_json={"tasks": [], "goals": [], "problems": [], "links": []},
    )
    grounding = {
        "tasks": [
            {"id": "tsk_roth", "title": "Deposit money into Roth IRA account", "status": "open", "due_date": "2026-03-31"},
            {
                "id": "tsk_vanguard",
                "title": "Sign up for a Vanguard investment account and transfer from E Trade to it",
                "status": "open",
                "due_date": "2026-03-31",
            },
        ],
        "recent_task_refs": [
            {"id": "tsk_roth", "title": "Deposit money into Roth IRA account", "status": "open"},
            {
                "id": "tsk_vanguard",
                "title": "Sign up for a Vanguard investment account and transfer from E Trade to it",
                "status": "open",
            },
        ],
        "displayed_task_refs": [],
        "session_state": {
            "active_entity_refs": [
                {
                    "entity_type": "work_item",
                    "entity_id": "tsk_roth",
                    "title": "Deposit money into Roth IRA account",
                    "status": "open",
                    "source": "apply",
                }
            ]
        },
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock
    ) as critique_actions, patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={"tasks": [], "goals": [], "problems": [], "links": [], "reminders": []},
    ) as extract_fallback:
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("That should be done the same day as the Vanguard account."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        extract_fallback.assert_awaited_once()
        critique_actions.assert_not_awaited()
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "Deposit money into Roth IRA account",
                "action": "update",
                "target_task_id": "tsk_roth",
                "due_date": "2026-03-31",
            }
        ]


def test_non_command_unusable_critic_revisions_do_not_clobber_planner_extraction(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.92,
        "needs_confirmation": True,
        "actions": [{"entity_type": "task", "action": "create", "title": "Return Nico's library books to NYPL"}],
    }
    critic = {
        "approved": True,
        "issues": [],
        "revised_actions": [{"entity_type": "task", "action": "create", "target_task_id": "tsk_missing_title"}],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value={"tasks": []}
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value=critic
    ), patch(
        "api.main.adapter.extract_structured_updates", new_callable=AsyncMock
    ) as extract_fallback:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("Return Nico's library books to NYPL tomorrow"), headers=_headers())
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        extract_fallback.assert_not_awaited()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"][0]["title"] == "Return Nico's library books to NYPL"


def test_non_command_planner_valid_does_not_use_intent_fallbacks(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.9,
        "needs_confirmation": True,
        "actions": [{"entity_type": "task", "action": "create", "title": "Plan weekend"}],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value={"tasks": []}
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main._apply_intent_fallbacks"
    ) as apply_fallbacks:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("Plan my weekend"), headers=_headers())
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        apply_fallbacks.assert_not_called()


def test_completion_request_filters_out_non_completion_planner_actions(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.6,
        "needs_confirmation": True,
        "actions": [
            {"entity_type": "task", "action": "complete", "title": "Do French homework"},
        ],
    }
    grounding = {
        "tasks": [
            {"id": "tsk_1", "title": "Do French homework", "status": "open"},
            {"id": "tsk_2", "title": "Memorize a script", "status": "open"},
            {"id": "tsk_3", "title": "Read a chapter and annotate it", "status": "open"},
        ],
        "recent_task_refs": [
            {"id": "tsk_1", "title": "Do French homework", "status": "open"},
            {"id": "tsk_2", "title": "Memorize a script", "status": "open"},
            {"id": "tsk_3", "title": "Read a chapter and annotate it", "status": "open"},
        ],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={"tasks": [], "goals": [], "problems": [], "links": []},
    ) as extract_fallback:
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("The French homework, memorize script, and reading a chapter are all done. Mark them complete."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["goals"] == []
        assert extraction["problems"] == []
        assert extraction["links"] == []
        ids = {t["target_task_id"] for t in extraction["tasks"]}
        assert ids == {"tsk_1"}
        titles = {t["title"] for t in extraction["tasks"]}
        assert "Do 100 pushups" not in titles
        extract_fallback.assert_not_awaited()


def test_completion_request_with_empty_fallback_returns_generic_clarification(app_no_db, mock_send):
    planned = {"intent": "action", "scope": "single", "confidence": 0.8, "needs_confirmation": True, "actions": []}
    grounding = {
        "tasks": [
            {"id": "tsk_1", "title": "Do French homework", "status": "done"},
            {"id": "tsk_2", "title": "Memorize a script", "status": "done"},
        ],
        "recent_task_refs": [
            {"id": "tsk_1", "title": "Do French homework", "status": "done"},
            {"id": "tsk_2", "title": "Memorize a script", "status": "done"},
        ],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": False, "issues": ["already done"]}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={"tasks": [], "goals": [], "problems": [], "links": []},
        ):
            resp = _post(
                app_no_db,
                WEBHOOK_URL,
                json=_tg_update("French homework and memorize script are done. Mark them complete."),
                headers=_headers(),
            )
            assert resp.status_code == 200
            create_draft.assert_not_awaited()
            assert "did not find clear actions to apply yet" in mock_send.await_args.args[1].lower()


def test_soft_completion_statement_with_explicit_recent_match_creates_review_draft(app_no_db, mock_send):
    planned = {"intent": "action", "scope": "single", "confidence": 0.6, "needs_confirmation": True, "actions": []}
    grounding = {
        "tasks": [
            {"id": "tsk_kbd", "title": "Clean mechanical keyboard", "status": "open"},
            {"id": "tsk_other", "title": "Do 100 burpees", "status": "open"},
        ],
        "recent_task_refs": [
            {"id": "tsk_kbd", "title": "Clean mechanical keyboard", "status": "open"},
            {"id": "tsk_other", "title": "Do 100 burpees", "status": "open"},
        ],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={
            "tasks": [{"title": "Clean mechanical keyboard", "action": "complete"}],
            "goals": [],
            "problems": [],
            "links": [],
        },
    ):
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("I cleaned the keyboard already."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "Clean mechanical keyboard",
                "action": "complete",
                "status": "done",
                "target_task_id": "tsk_kbd",
            }
        ]


def test_named_completion_statement_from_recent_today_item_creates_review_draft(app_no_db, mock_send):
    planned = {"intent": "query", "scope": "single", "confidence": 0.1, "needs_confirmation": True, "actions": []}
    grounding = {
        "tasks": [
            {"id": "tsk_dinner", "title": "Plan Tuesday dinner: menu and get groceries", "status": "open"},
            {"id": "tsk_other", "title": "Order a new battery for the old forklift", "status": "open"},
        ],
        "recent_task_refs": [
            {"id": "tsk_dinner", "title": "Plan Tuesday dinner: menu and get groceries", "status": "open"},
            {"id": "tsk_other", "title": "Order a new battery for the old forklift", "status": "open"},
        ],
        "displayed_task_refs": [
            {"ordinal": 5, "id": "tsk_dinner", "title": "Plan Tuesday dinner: menu and get groceries", "status": "open", "view_name": "today"},
        ],
    }
    fake_draft = _fake_draft(
        source_message="The Tuesday dinner plan is done. Finished that a while back.",
        proposal_json={"tasks": [], "goals": [], "problems": [], "links": []},
    )
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={
            "tasks": [{"title": "Plan Tuesday dinner: menu and get groceries", "action": "complete"}],
            "goals": [],
            "problems": [],
            "links": [],
        },
    ):
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("The Tuesday dinner plan is done. Finished that a while back."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "Plan Tuesday dinner: menu and get groceries",
                "action": "complete",
                "status": "done",
                "target_task_id": "tsk_dinner",
            }
        ]


def test_completion_high_confidence_with_recent_matches_autopilots(app_no_db, mock_send):
    planned = {"intent": "action", "scope": "single", "confidence": 0.95, "needs_confirmation": True, "actions": []}
    grounding = {
        "tasks": [
            {"id": "tsk_1", "title": "Do French homework", "status": "open"},
            {"id": "tsk_2", "title": "Memorize a script", "status": "open"},
        ],
        "recent_task_refs": [
            {"id": "tsk_1", "title": "Do French homework", "status": "open"},
            {"id": "tsk_2", "title": "Memorize a script", "status": "open"},
        ],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._apply_capture", new_callable=AsyncMock
    ) as apply_capture, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={
            "tasks": [
                {"title": "Do French homework", "action": "complete"},
                {"title": "Memorize a script", "action": "complete"},
            ],
            "goals": [],
            "problems": [],
            "links": [],
        },
    ):
        apply_capture.return_value = ("inb_1", AppliedChanges(tasks_updated=2))
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Mark French homework and memorize script as complete."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_not_awaited()
        apply_capture.assert_awaited_once()
        applied_extraction = apply_capture.await_args.kwargs["extraction"]
        assert applied_extraction["tasks"] == [
            {
                "title": "Do French homework",
                "action": "complete",
                "status": "done",
                "target_task_id": "tsk_1",
            },
            {
                "title": "Memorize a script",
                "action": "complete",
                "status": "done",
                "target_task_id": "tsk_2",
            },
        ]
        assert "updated" in mock_send.await_args.args[1].lower()


def test_create_intent_autopilot_uses_model_provided_create_action(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.95,
        "needs_confirmation": False,
        "actions": [{"entity_type": "task", "action": "create", "title": "Watch a Mark Wahlberg movie", "due_date": "2026-02-13"}],
    }
    grounding = {
        "tasks": [{"id": "tsk_existing", "title": "Do 100 burpees", "status": "open"}],
        "recent_task_refs": [{"id": "tsk_existing", "title": "Do 100 burpees", "status": "open"}],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._apply_capture", new_callable=AsyncMock
    ) as apply_capture, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={"tasks": [{"title": "Do 100 burpees", "action": "update"}], "goals": [], "problems": [], "links": []},
    ):
        apply_capture.return_value = ("inb_1", AppliedChanges(tasks_created=1))
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("add a Mark Wahlberg movie to my list. I want to watch it tomorrow night."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_not_awaited()
        apply_capture.assert_awaited_once()
        extraction = apply_capture.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {"title": "Watch a Mark Wahlberg movie", "action": "create", "due_date": "2026-02-13"}
        ]

def test_due_date_preserves_model_output_without_phrase_override(app_no_db, mock_send):
    planned = {"intent": "action", "scope": "single", "confidence": 0.8, "needs_confirmation": True, "actions": []}
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value={"tasks": []}
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={"tasks": [{"title": "Respond to Gil", "due_date": "2026-02-13"}], "goals": [], "problems": [], "links": []},
    ), patch("api.main._local_today", return_value=date(2026, 2, 12)):
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Respond to Gil by tonight. He wants to know about the payment from Tomas."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"][0]["due_date"] == "2026-02-13"


def test_tomorrow_night_does_not_force_today_due_date(app_no_db, mock_send):
    planned = {"intent": "action", "scope": "single", "confidence": 0.8, "needs_confirmation": True, "actions": []}
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value={"tasks": []}
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={"tasks": [{"title": "Watch movie", "due_date": "2026-02-13"}], "goals": [], "problems": [], "links": []},
    ), patch("api.main._local_today", return_value=date(2026, 2, 12)):
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Add movie night tomorrow night."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"][0]["due_date"] == "2026-02-13"


def test_low_confidence_actionable_plan_requests_clarification_instead_of_draft(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.3,
        "needs_confirmation": True,
        "actions": [{"entity_type": "task", "action": "create", "title": "Call landlord"}],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value={"tasks": []}
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main._apply_capture", new_callable=AsyncMock
    ) as apply_capture:
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Call landlord about leak"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_not_awaited()
        apply_capture.assert_not_awaited()
        assert "i need one clarification before applying changes" in mock_send.await_args.args[1].lower()
        assert "not fully confident" in mock_send.await_args.args[1].lower()


def test_displayed_task_delete_reference_creates_archive_draft(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.1,
        "needs_confirmation": True,
        "actions": [],
    }
    grounding = {
        "tasks": [
            {
                "id": "tsk_bad",
                "title": "Move worker's compensation form to today",
                "status": "open",
            }
        ],
        "recent_task_refs": [
            {
                "id": "tsk_bad",
                "title": "Move worker's compensation form to today",
                "status": "open",
            }
        ],
        "displayed_task_refs": [
            {
                "ordinal": 1,
                "id": "tsk_bad",
                "title": "Move worker's compensation form to today",
                "status": "open",
                "view_name": "today",
            }
        ],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={
            "tasks": [{"title": "worker's compensation form", "action": "archive", "status": "archived", "target_task_id": "tsk_bad"}],
            "goals": [],
            "problems": [],
            "links": [],
        },
    ):
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Delete the first task. Move worker's comp doesn't seem like a real task."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "worker's compensation form",
                "action": "archive",
                "status": "archived",
                "target_task_id": "tsk_bad",
            }
        ]


def test_named_project_delete_request_with_empty_extract_falls_back_to_archive(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.2,
        "needs_confirmation": True,
        "actions": [],
    }
    grounding = {
        "tasks": [
            {"id": "wki_proj", "title": "Telegram Todo app", "status": "open", "kind": "project"},
        ],
        "recent_task_refs": [
            {"id": "wki_proj", "title": "Telegram Todo app", "status": "open", "kind": "project"},
        ],
        "displayed_task_refs": [],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={"tasks": [], "goals": [], "problems": [], "links": []},
    ):
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("delete the telegram todo app project"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "Telegram Todo app",
                "action": "archive",
                "status": "archived",
                "target_task_id": "wki_proj",
            }
        ]


def test_goal_archive_planner_action_stays_archive_not_create(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.95,
        "needs_confirmation": True,
        "actions": [
            {
                "entity_type": "goal",
                "title": "Telegram Todo app",
                "action": "archive",
                "status": "archived",
                "target_task_id": "wki_proj",
            }
        ],
    }
    grounding = {
        "tasks": [
            {"id": "wki_proj", "title": "Telegram Todo app", "status": "open", "kind": "project"},
        ],
        "recent_task_refs": [
            {"id": "wki_proj", "title": "Telegram Todo app", "status": "open", "kind": "project"},
        ],
        "displayed_task_refs": [],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
    ) as extract_fallback:
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("delete the telegram todo app project"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        extract_fallback.assert_not_awaited()
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "Telegram Todo app",
                "kind": "project",
                "action": "archive",
                "status": "archived",
                "target_task_id": "wki_proj",
            }
        ]


def test_recent_named_references_create_multi_action_draft(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.1,
        "needs_confirmation": True,
        "actions": [],
    }
    grounding = {
        "tasks": [
            {"id": "tsk_burpee", "title": "Delete the burpee task", "status": "open"},
            {"id": "tsk_backpack", "title": "Remind Amy about the backpack", "status": "open"},
        ],
        "recent_task_refs": [
            {"id": "tsk_burpee", "title": "Delete the burpee task", "status": "open"},
            {"id": "tsk_backpack", "title": "Remind Amy about the backpack", "status": "open"},
        ],
        "displayed_task_refs": [],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={
            "tasks": [
                {"title": "Delete the burpee task", "action": "archive", "status": "archived", "target_task_id": "tsk_burpee"},
                {"title": "Remind Amy about the backpack", "action": "complete", "status": "done", "target_task_id": "tsk_backpack"},
            ],
            "goals": [],
            "problems": [],
            "links": [],
        },
    ):
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Let's delete the burpee task. Amy found the backpack already, mark that as done."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "Delete the burpee task",
                "action": "archive",
                "status": "archived",
                "target_task_id": "tsk_burpee",
            },
            {
                "title": "Remind Amy about the backpack",
                "action": "complete",
                "status": "done",
                "target_task_id": "tsk_backpack",
            },
        ]


def test_question_form_archive_request_overrides_query_intent(app_no_db, mock_send):
    planned = {
        "intent": "query",
        "scope": "single",
        "confidence": 0.7,
        "needs_confirmation": False,
        "actions": [],
    }
    grounding = {
        "tasks": [
            {"id": "tsk_burpee", "title": "Delete the burpee task", "status": "open"},
        ],
        "recent_task_refs": [
            {"id": "tsk_burpee", "title": "Delete the burpee task", "status": "open"},
        ],
        "displayed_task_refs": [],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main.query_ask", new_callable=AsyncMock
    ) as query_ask, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={
            "tasks": [{"title": "Delete the burpee task", "action": "archive", "status": "archived", "target_task_id": "tsk_burpee"}],
            "goals": [],
            "problems": [],
            "links": [],
        },
    ):
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Can you delete the burpee task?"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        query_ask.assert_not_awaited()
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "Delete the burpee task",
                "action": "archive",
                "status": "archived",
                "target_task_id": "tsk_burpee",
            }
        ]


def test_question_form_completion_request_overrides_query_intent(app_no_db, mock_send):
    planned = {
        "intent": "query",
        "scope": "single",
        "confidence": 0.6,
        "needs_confirmation": False,
        "actions": [],
    }
    grounding = {
        "tasks": [
            {"id": "tsk_backpack", "title": "Remind Amy about the backpack", "status": "open"},
        ],
        "recent_task_refs": [
            {"id": "tsk_backpack", "title": "Remind Amy about the backpack", "status": "open"},
        ],
        "displayed_task_refs": [],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main.query_ask", new_callable=AsyncMock
    ) as query_ask, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={
            "tasks": [{"title": "Remind Amy about the backpack", "action": "complete", "target_task_id": "tsk_backpack"}],
            "goals": [],
            "problems": [],
            "links": [],
        },
    ):
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Could you mark the backpack one done?"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        query_ask.assert_not_awaited()
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == [
            {
                "title": "Remind Amy about the backpack",
                "action": "complete",
                "status": "done",
                "target_task_id": "tsk_backpack",
            }
        ]


def test_ambiguous_targeted_update_asks_candidate_clarification(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.8,
        "needs_confirmation": True,
        "actions": [],
    }
    grounding = {
        "tasks": [
            {
                "id": "tsk_apartment_1",
                "title": "Reach out to Ben and Jason regarding the apartment renovation",
                "status": "open",
            },
            {
                "id": "tsk_apartment_2",
                "title": "Figure out the schedule for the apartment renovation",
                "status": "open",
            },
        ],
        "recent_task_refs": [
            {
                "id": "tsk_apartment_1",
                "title": "Reach out to Ben and Jason regarding the apartment renovation",
                "status": "open",
            },
            {
                "id": "tsk_apartment_2",
                "title": "Figure out the schedule for the apartment renovation",
                "status": "open",
            },
        ],
        "displayed_task_refs": [],
    }
    fake_draft = _fake_draft(
        source_message="Can you move the apartment task to tomorrow?",
        proposal_json={"tasks": [{"title": "Apartment renovation", "action": "update", "due_date": "2026-03-25"}], "goals": [], "problems": [], "links": []},
    )
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ) as create_draft, patch(
        "api.main._apply_capture", new_callable=AsyncMock
    ) as apply_capture, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates",
        new_callable=AsyncMock,
        return_value={
            "tasks": [{"title": "Apartment renovation", "action": "update", "due_date": "2026-03-25"}],
            "goals": [],
            "problems": [],
            "links": [],
        },
    ):
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Can you move the apartment task to tomorrow?"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        apply_capture.assert_not_awaited()
        text = mock_send.await_args.args[1]
        assert "Which task do you want to update?" in text
        assert "Reach out to Ben and Jason regarding the apartment renovation" in text
        assert "Figure out the schedule for the apartment renovation" in text


def test_unrelated_targeted_update_is_rewritten_to_create(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.95,
        "needs_confirmation": False,
        "actions": [
            {
                "entity_type": "task",
                "action": "update",
                "title": "Finish reading the audiobook about Christianity",
                "target_task_id": "tsk_gil",
            }
        ],
    }
    grounding = {
        "tasks": [
            {"id": "tsk_gil", "title": "Respond to Gil by tonight", "status": "open"},
        ],
        "recent_task_refs": [
            {"id": "tsk_gil", "title": "Respond to Gil by tonight", "status": "open"},
        ],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._apply_capture", new_callable=AsyncMock
    ) as apply_capture, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ):
        apply_capture.return_value = ("inb_1", AppliedChanges(tasks_created=1))
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Finish reading the audiobook about Christianity by tonight"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        if apply_capture.await_count:
            extraction = apply_capture.await_args.kwargs["extraction"]
        else:
            create_draft.assert_awaited_once()
            extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"][0]["action"] == "create"
        assert extraction["tasks"][0].get("target_task_id") is None


def test_non_command_critic_rejects_and_requests_clarification(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "all_open",
        "confidence": 0.91,
        "needs_confirmation": True,
        "actions": [{"entity_type": "task", "action": "complete", "title": "Anything"}],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock
    ) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value={"tasks": []}
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions",
        new_callable=AsyncMock,
        return_value={"approved": False, "issues": ["Missing target task references"]},
    ):
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("Please organize this plan"), headers=_headers())
        assert resp.status_code == 200
        create_draft.assert_not_awaited()
        assert "need one clarification" in mock_send.await_args.args[1].lower()


def test_non_command_question_routes_to_query_no_capture(app_no_db, mock_send, mock_extract):
    mock_extract.interpret_telegram_turn.return_value = {
        "speech_act": "query",
        "confidence": 0.9,
    }
    fake_session = type(
        "Session",
        (),
        {
            "id": "ses_1",
            "current_mode": "today",
            "active_entity_refs_json": [{"entity_type": "work_item", "entity_id": "tsk_1", "title": "Task A"}],
            "pending_draft_id": None,
            "pending_clarification_json": {},
            "summary_metadata_json": {},
        },
    )()
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main.query_ask", new_callable=AsyncMock
    ) as mocked_query, patch("api.main._apply_capture", new_callable=AsyncMock) as apply_capture, patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main._get_or_create_session", new_callable=AsyncMock, return_value=fake_session
    ), patch("api.main._create_action_draft", new_callable=AsyncMock) as create_draft, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value={"tasks": []}
    ), patch(
        "api.main.adapter.plan_actions",
        new_callable=AsyncMock,
        return_value={"intent": "query", "scope": "single", "actions": [], "confidence": 0.9, "needs_confirmation": False},
    ):
        mocked_query.return_value = QueryResponseV1(answer="You have 2 open tasks.", confidence=0.9)
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("What tasks are not completed?"), headers=_headers())
        assert resp.status_code == 200
        mocked_query.assert_awaited_once()
        apply_capture.assert_not_awaited()
        create_draft.assert_not_awaited()
        assert "2 open tasks" in mock_send.await_args.args[1]
        turn_context = mock_extract.interpret_telegram_turn.await_args.kwargs["context"]
        assert turn_context["session_state"]["session_id"] == "ses_1"
        assert turn_context["session_state"]["current_mode"] == "today"


def test_non_command_yes_applies_open_draft(app_no_db, mock_send, mock_extract):
    mock_extract.interpret_telegram_turn.return_value = {
        "speech_act": "confirmation",
        "draft_action": "confirm",
        "confidence": 0.9,
    }
    fake_draft = type("Draft", (), {"id": "drf_1", "source_message": "plan kitchen", "proposal_json": {"tasks": [{"title": "Task A"}]}})()
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ), patch("api.main._confirm_action_draft", new_callable=AsyncMock) as confirm_draft:
        confirm_draft.return_value = AppliedChanges(tasks_created=1)
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("yes"), headers=_headers())
        assert resp.status_code == 200
        confirm_draft.assert_awaited_once()
        assert "task(s) created" in mock_send.await_args.args[1].lower()


def test_confirm_action_draft_invalidates_today_plan_cache(mock_db):
    fake_draft = _fake_draft(
        source_message="move the photo processing task to tomorrow",
        proposal_json={"tasks": [{"title": "Process photos from the last tournament", "action": "update"}]},
    )
    fake_session = type(
        "SessionObj",
        (),
        {
            "id": "ses_1",
            "current_mode": "today",
            "active_entity_refs_json": [],
            "pending_draft_id": None,
            "pending_clarification_json": None,
            "summary_metadata_json": {},
        },
    )()
    with patch(
        "api.main._apply_capture",
        new_callable=AsyncMock,
        return_value=("inb_1", AppliedChanges(tasks_updated=1)),
    ) as apply_capture, patch(
        "api.main._invalidate_today_plan_cache",
        new_callable=AsyncMock,
    ) as invalidate_today, patch(
        "api.main._enqueue_summary_job",
        new_callable=AsyncMock,
    ) as enqueue_summary, patch(
        "api.main._get_or_create_session",
        new_callable=AsyncMock,
        return_value=fake_session,
    ), patch(
        "api.main._update_session_state",
        new_callable=AsyncMock,
    ):
        applied = asyncio.run(
            _confirm_action_draft(
                draft=fake_draft,
                user_id="usr_123",
                chat_id="12345",
                request_id="req_1",
                db=mock_db,
            )
        )

    apply_capture.assert_awaited_once()
    invalidate_today.assert_awaited_once_with("usr_123", "12345")
    enqueue_summary.assert_awaited_once_with(user_id="usr_123", chat_id="12345", inbox_item_id="inb_1")
    assert applied.tasks_updated == 1


def test_callback_confirm_applies_open_draft(app_no_db, mock_send):
    fake_draft = type("Draft", (), {"id": "drf_1", "source_message": "plan kitchen", "proposal_json": {"tasks": [{"title": "Task A"}]}})()
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ), patch(
        "api.main._confirm_action_draft", new_callable=AsyncMock, return_value=AppliedChanges(tasks_created=1)
    ) as confirm_draft, patch("api.main.answer_callback_query", new_callable=AsyncMock) as ack:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_callback_update("draft:confirm:drf_1"), headers=_headers())
        assert resp.status_code == 200
        ack.assert_awaited_once()
        confirm_draft.assert_awaited_once()
        assert "task(s) created" in mock_send.await_args.args[1].lower()


def test_callback_edit_prompts_for_edit_text(app_no_db, mock_send):
    fake_draft = type("Draft", (), {"id": "drf_1", "source_message": "plan kitchen", "proposal_json": {"tasks": [{"title": "Task A"}]}})()
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ), patch("api.main.answer_callback_query", new_callable=AsyncMock):
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_callback_update("draft:edit:drf_1"), headers=_headers())
        assert resp.status_code == 200
        assert "reply with your changes" in mock_send.await_args.args[1].lower()


def test_edit_button_then_plain_message_revises_draft(app_no_db, mock_send):
    fake_draft = type("Draft", (), {"id": "drf_1", "source_message": "plan kitchen", "proposal_json": {"tasks": [{"title": "Task A"}], "_meta": {"awaiting_edit_input": True}}})()
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ), patch(
        "api.main._revise_action_draft",
        new_callable=AsyncMock,
        return_value={"tasks": [{"title": "Task B"}], "goals": [], "problems": [], "links": []},
    ) as revise_draft:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("Change this to task B"), headers=_headers())
        assert resp.status_code == 200
        revise_draft.assert_awaited_once()
        assert "review changes" in mock_send.await_args.args[1].lower()


def test_clarification_reply_revises_pending_candidate_draft(app_no_db, mock_send):
    fake_draft = _fake_draft(
        source_message="Move the registration of 401k to next week. Make a note that Patrick's email is required.",
        proposal_json={
            "tasks": [{"title": "registration of 401k", "action": "update", "due_date": "2026-03-31"}],
            "goals": [],
            "problems": [],
            "links": [],
            "_meta": {
                "awaiting_edit_input": True,
                "clarification_state": {
                    "candidates": [
                        {"id": "tsk_census", "title": "Work on the 401k census", "status": "open"},
                        {"id": "tsk_register", "title": "Register for the 401k plan", "status": "open"},
                    ]
                },
            },
        },
    )
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ), patch(
        "api.main._revise_action_draft",
        new_callable=AsyncMock,
        return_value={
            "tasks": [
                {
                    "title": "Register for the 401k plan",
                    "action": "update",
                    "target_task_id": "tsk_register",
                    "due_date": "2026-03-31",
                    "notes": "Patrick's email is required.",
                }
            ],
            "goals": [],
            "problems": [],
            "links": [],
        },
    ) as revise_draft, patch(
        "api.main.query_ask", new_callable=AsyncMock
    ) as query_ask:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("The one that says register"), headers=_headers())
        assert resp.status_code == 200
        revise_draft.assert_awaited_once()
        query_ask.assert_not_awaited()
        assert "review changes" in mock_send.await_args.args[1].lower()


def test_revise_edits_existing_proposal_message_in_place(app_no_db, mock_send, mock_extract):
    mock_extract.interpret_telegram_turn.return_value = {
        "speech_act": "confirmation",
        "draft_action": "edit",
        "draft_edit_text": "rename to task B",
        "confidence": 0.9,
    }
    fake_draft = type(
        "Draft",
        (),
        {
            "id": "drf_1",
            "source_message": "plan kitchen",
            "proposal_json": {"tasks": [{"title": "Task A"}], "_meta": {"proposal_message_id": 321}},
            "updated_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc),
        },
    )()
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ), patch(
        "api.main._revise_action_draft",
        new_callable=AsyncMock,
        return_value={"tasks": [{"title": "Task B"}], "goals": [], "problems": [], "links": []},
    ), patch("api.main.edit_message", new_callable=AsyncMock, return_value={"ok": True}) as edit_msg:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("edit rename to task B"), headers=_headers())
        assert resp.status_code == 200
        edit_msg.assert_awaited_once()
        mock_send.assert_not_awaited()


def test_draft_meta_updates_use_new_json_object():
    draft = type(
        "Draft",
        (),
        {
            "proposal_json": {"tasks": [{"title": "Task A"}], "_meta": {"existing": True}},
        },
    )()
    original = draft.proposal_json

    _draft_set_awaiting_edit_input(draft, True)
    after_awaiting = draft.proposal_json
    assert after_awaiting is not original
    assert after_awaiting["_meta"]["existing"] is True
    assert after_awaiting["_meta"]["awaiting_edit_input"] is True

    _draft_set_proposal_message_id(draft, 123)
    after_message_id = draft.proposal_json
    assert after_message_id is not after_awaiting
    assert after_message_id["_meta"]["proposal_message_id"] == 123


def test_unlinked_chat_command_receives_link_guidance(app_no_db, mock_send):
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value=None), patch(
        "api.main.handle_telegram_command", new_callable=AsyncMock
    ) as mocked:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("/today"), headers=_headers())
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


def test_command_today_handles_live_plan_with_naive_task_timestamp(mock_redis, mock_send, mock_db):
    state = {
        "tasks": [
            Task(
                id="tsk_1",
                user_id="usr_abc",
                title="Review live /today behavior",
                title_norm="review live today behavior",
                status=TaskStatus.open,
                updated_at=datetime(2026, 3, 18, 12, 0, 0),
            )
        ],
        "goals": [],
        "links": [],
    }
    with patch("api.main.redis_client", mock_redis), patch(
        "api.main.collect_planning_state", new_callable=AsyncMock, return_value=state
    ), patch("api.main._remember_displayed_tasks", new_callable=AsyncMock) as remember:
        asyncio.run(handle_telegram_command("/today", None, "12345", "usr_abc", mock_db))
    text = mock_send.await_args.args[1]
    assert "Your Today Plan" in text
    assert "Review live /today behavior" in text
    assert "Updated " in text
    remember.assert_awaited_once_with(mock_db, "usr_abc", "12345", ["tsk_1"], "today")
    assert mock_db.commit.await_count >= 1


def test_command_today_rebuilds_live_when_cached_plan_is_stale(mock_redis, mock_send, mock_db):
    mock_redis.get.return_value = json.dumps(
        {
            "generated_at": "2026-03-19T07:00:00Z",
            "today_plan": [{"task_id": "tsk_old", "title": "Old cached task"}],
        }
    )
    state = {
        "tasks": [
            Task(
                id="tsk_live",
                user_id="usr_abc",
                title="Fresh live task",
                title_norm="fresh live task",
                status=TaskStatus.open,
                updated_at=datetime(2026, 3, 19, 11, 0, 0),
            )
        ],
        "goals": [],
        "links": [],
    }
    fixed_now = datetime(2026, 3, 19, 12, 15, 0, tzinfo=timezone.utc)
    with patch("api.main.redis_client", mock_redis), patch(
        "api.main.collect_planning_state", new_callable=AsyncMock, return_value=state
    ), patch("api.main.utc_now", return_value=fixed_now), patch(
        "api.main._remember_displayed_tasks", new_callable=AsyncMock
    ) as remember:
        asyncio.run(handle_telegram_command("/today", None, "12345", "usr_abc", mock_db))
    text = mock_send.await_args.args[1]
    assert "Fresh live task" in text
    assert "Old cached task" not in text
    mock_redis.setex.assert_awaited_once()
    remember.assert_awaited_once_with(mock_db, "usr_abc", "12345", ["tsk_live"], "today")


def test_command_urgent_lists_high_priority_tasks(mock_send, mock_db):
    result = Mock()
    scalars_result = Mock()
    scalars_result.all.return_value = [
        Task(
            id="tsk_urgent_1",
            user_id="usr_abc",
            title="Register for the 401k plan",
            title_norm="register for the 401k plan",
            status=TaskStatus.open,
            priority=1,
            due_date=date(2026, 3, 25),
        ),
        Task(
            id="tsk_urgent_2",
            user_id="usr_abc",
            title="Submit payroll correction",
            title_norm="submit payroll correction",
            status=TaskStatus.blocked,
            priority=1,
        ),
    ]
    result.scalars.return_value = scalars_result
    mock_db.execute.return_value = result
    with patch("api.main._remember_displayed_tasks", new_callable=AsyncMock) as remember:
        asyncio.run(handle_telegram_command("/urgent", None, "12345", "usr_abc", mock_db))
    text = mock_send.await_args.args[1]
    assert "Urgent Items" in text
    assert "Register for the 401k plan" in text
    assert "Submit payroll correction" in text
    assert "Due 3/25/2026 (1 day overdue)" in text
    remember.assert_awaited_once_with(mock_db, "usr_abc", "12345", ["tsk_urgent_1", "tsk_urgent_2"], "urgent")
    assert mock_db.commit.await_count >= 1


def test_command_web_returns_prefilled_workbench_link(mock_send, mock_db):
    old_base = settings.WEB_UI_BASE_URL
    settings.WEB_UI_BASE_URL = "https://assistant.example/app"
    try:
        asyncio.run(handle_telegram_command("/web", None, "12345", "usr_abc", mock_db))
    finally:
        settings.WEB_UI_BASE_URL = old_base
    text = mock_send.await_args.args[1]
    assert "web workbench" in text
    assert "https://assistant.example/app?token=test_token" in text
    assert "includes your API token" in text


def test_command_web_without_config_prompts_for_web_ui_base_url(mock_send, mock_db):
    old_base = settings.WEB_UI_BASE_URL
    settings.WEB_UI_BASE_URL = None
    try:
        asyncio.run(handle_telegram_command("/web", None, "12345", "usr_abc", mock_db))
    finally:
        settings.WEB_UI_BASE_URL = old_base
    text = mock_send.await_args.args[1]
    assert "WEB_UI_BASE_URL" in text
    assert "not configured" in text


def test_unknown_command_shows_minimal_visible_menu(mock_send, mock_db):
    asyncio.run(handle_telegram_command("/nope", None, "12345", "usr_abc", mock_db))
    text = mock_send.await_args.args[1]
    assert "/today" in text
    assert "/urgent" in text
    assert "/web" in text
    assert "/plan" not in text
    assert "/focus" not in text
    assert "/done" not in text
    assert "/ask" not in text


def test_action_batch_callback_shows_details(app_no_db, mock_send):
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_abc"), patch(
        "api.main._show_action_batch_details", new_callable=AsyncMock
    ) as show_details, patch("api.main.answer_callback_query", new_callable=AsyncMock) as ack:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_callback_update("batch:show:abt_1"), headers=_headers())
        assert resp.status_code == 200
        ack.assert_awaited_once()
        show_details.assert_awaited_once()
        kwargs = show_details.await_args.kwargs
        assert kwargs["chat_id"] == "12345"
        assert kwargs["user_id"] == "usr_abc"
        assert kwargs["batch_id"] == "abt_1"
        assert kwargs["detail"] == "show"


def test_command_today_suppresses_near_duplicate_visible_tasks(mock_redis, mock_send, mock_db):
    state = {
        "tasks": [
            Task(
                id="tsk_a",
                user_id="usr_abc",
                title="Plan Tuesday dinner: menu and get groceries",
                title_norm="plan tuesday dinner menu and get groceries",
                status=TaskStatus.open,
                updated_at=datetime(2026, 3, 10, 9, 0, 0),
            ),
            Task(
                id="tsk_b",
                user_id="usr_abc",
                title="Plan Tuesday dinner menu",
                title_norm="plan tuesday dinner menu",
                status=TaskStatus.open,
                updated_at=datetime(2026, 3, 10, 9, 0, 0),
            ),
            Task(
                id="tsk_c",
                user_id="usr_abc",
                title="Reach out to Ben and Jason regarding the apartment renovation",
                title_norm="reach out to ben and jason regarding the apartment renovation",
                status=TaskStatus.open,
                updated_at=datetime(2026, 3, 10, 9, 0, 0),
            ),
        ],
        "goals": [],
        "links": [],
    }
    with patch("api.main.redis_client", mock_redis), patch(
        "api.main.collect_planning_state", new_callable=AsyncMock, return_value=state
    ), patch("api.main._remember_displayed_tasks", new_callable=AsyncMock) as remember:
        asyncio.run(handle_telegram_command("/today", None, "12345", "usr_abc", mock_db))
    text = mock_send.await_args.args[1]
    assert "Plan Tuesday dinner: menu and get groceries" in text
    assert "Plan Tuesday dinner menu" not in text
    assert "Reach out to Ben and Jason regarding the apartment renovation" in text
    remember.assert_awaited_once_with(mock_db, "usr_abc", "12345", ["tsk_a", "tsk_c"], "today")


def test_command_today_stores_due_reminder_context_after_successful_send(mock_redis, mock_send, mock_db):
    mock_redis.get.return_value = json.dumps(
        {
            "schema_version": "plan.v1",
            "plan_window": "today",
            "generated_at": "2026-03-25T18:00:00Z",
            "today_plan": [
                {"task_id": "tsk_1", "rank": 1, "title": "Task 1", "score": 1.0},
            ],
            "next_actions": [],
            "blocked_items": [],
            "why_this_order": [],
            "assumptions": [],
            "due_reminders": [
                {"reminder_id": "rem_1", "title": "Payroll reminder", "remind_at": "2026-03-25T18:00:00Z"},
                {"reminder_id": "rem_2", "title": "Insurance reminder", "remind_at": "2026-03-25T19:00:00Z"},
            ],
        }
    )
    with patch("api.main.redis_client", mock_redis), patch(
        "api.main.utc_now", return_value=datetime(2026, 3, 25, 18, 1, 0, tzinfo=timezone.utc)
    ), patch(
        "api.main._remember_displayed_tasks", new_callable=AsyncMock
    ) as remember_tasks, patch("api.main._remember_recent_reminders", new_callable=AsyncMock) as remember_reminders:
        asyncio.run(handle_telegram_command("/today", None, "12345", "usr_abc", mock_db))
    remember_tasks.assert_awaited_once_with(mock_db, "usr_abc", "12345", ["tsk_1"], "today")
    remember_reminders.assert_awaited_once_with(
        db=mock_db,
        user_id="usr_abc",
        chat_id="12345",
        reminder_ids=["rem_1", "rem_2"],
        reason="today_view",
        ttl_hours=12,
    )
    assert mock_db.commit.await_count >= 1


def test_command_done_without_args_uses_ordinal_first_guidance(mock_db, mock_send):
    asyncio.run(handle_telegram_command("/done", None, "12345", "usr_abc", mock_db))
    mock_db.execute.assert_not_awaited()
    mock_db.commit.assert_not_awaited()
    text = mock_send.await_args.args[1]
    assert "/done 2" in text
    assert "latest visible plan list" in text
    assert "Advanced: you can still use <code>/done tsk_123</code>" in text


def test_command_done_updates_owned_task_only(mock_db, mock_send, mock_redis):
    result = Mock()
    result.scalar_one_or_none.return_value = WorkItem(
        id="tsk_x",
        user_id="usr_abc",
        kind=WorkItemKind.task,
        title="Buy paint rollers",
        title_norm="buy paint rollers",
        status=WorkItemStatus.open,
    )
    mock_db.execute.return_value = result
    with patch("api.main.redis_client", mock_redis):
        asyncio.run(handle_telegram_command("/done", "tsk_x", "12345", "usr_abc", mock_db))
    mock_db.commit.assert_awaited_once()
    mock_redis.delete.assert_awaited_once_with("plan:today:usr_abc:12345")
    assert "Marked as done" in mock_send.await_args.args[1]
    assert "Buy paint rollers" in mock_send.await_args.args[1]


def test_command_done_rejects_non_owned_or_unknown(mock_db, mock_send):
    result = Mock()
    result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = result
    asyncio.run(handle_telegram_command("/done", "tsk_other", "12345", "usr_abc", mock_db))
    mock_db.commit.assert_not_awaited()
    assert "not found" in mock_send.await_args.args[1].lower()


def test_command_done_supports_recent_focus_ordinal(mock_db, mock_send, mock_redis):
    result = Mock()
    result.scalar_one_or_none.return_value = WorkItem(
        id="tsk_focus_2",
        user_id="usr_abc",
        kind=WorkItemKind.task,
        title="Call contractor",
        title_norm="call contractor",
        status=WorkItemStatus.open,
    )
    mock_db.execute.return_value = result
    with patch("api.main._resolve_displayed_task_id", new_callable=AsyncMock, return_value="tsk_focus_2") as resolve_task:
        with patch("api.main.redis_client", mock_redis):
            asyncio.run(handle_telegram_command("/done", "2", "12345", "usr_abc", mock_db))
    resolve_task.assert_awaited_once_with(mock_db, "usr_abc", "12345", 2)
    mock_db.commit.assert_awaited_once()
    mock_redis.delete.assert_awaited_once_with("plan:today:usr_abc:12345")
    assert "Call contractor" in mock_send.await_args.args[1]


def test_command_done_rejects_unknown_ordinal_without_mutation(mock_db, mock_send):
    with patch("api.main._resolve_displayed_task_id", new_callable=AsyncMock, return_value=None):
        asyncio.run(handle_telegram_command("/done", "99", "12345", "usr_abc", mock_db))
    mock_db.execute.assert_not_awaited()
    mock_db.commit.assert_not_awaited()
    text = mock_send.await_args.args[1]
    assert "most recent visible plan list" in text
    assert "Advanced: you can still use <code>/done tsk_123</code>" in text


def test_apply_capture_repairs_wrapper_title_on_touched_task(mock_db):
    existing = WorkItem(
        id="tsk_wrap",
        user_id="usr_abc",
        kind=WorkItemKind.task,
        title="Move 'Complete Worker's Compensation form for employee' to today",
        title_norm="move complete workers compensation form for employee to today",
        status=WorkItemStatus.open,
    )
    result = Mock()
    result.scalar_one_or_none.return_value = existing
    mock_db.execute.return_value = result

    _, applied = asyncio.run(
        _apply_capture(
            db=mock_db,
            user_id="usr_abc",
            chat_id="12345",
            source="telegram",
            message="The first one is complete.",
            extraction={
                "tasks": [
                    {
                        "title": "Complete Worker's Compensation form for employee",
                        "action": "complete",
                        "status": "done",
                        "target_task_id": "tsk_wrap",
                    }
                ],
                "goals": [],
                "problems": [],
                "links": [],
            },
            request_id="req_wrap",
            commit=False,
            enqueue_summary=False,
        )
    )

    assert existing.title == "Complete Worker's Compensation form for employee"
    assert existing.title_norm == "complete worker's compensation form for employee"
    assert applied.items[0].label == "Complete Worker's Compensation form for employee"
    added_types = [type(call.args[0]) for call in mock_db.add.call_args_list if call.args]
    assert ConversationEvent in added_types
    assert ActionBatch in added_types
    assert WorkItemVersion in added_types


def test_apply_capture_flushes_inbox_item_before_creating_work_items(mock_db):
    flush_called = False

    async def _flush():
        nonlocal flush_called
        flush_called = True

    def _add(obj):
        if isinstance(obj, WorkItem):
            assert flush_called is True

    mock_db.flush = AsyncMock(side_effect=_flush)
    mock_db.add.side_effect = _add

    _, applied = asyncio.run(
        _apply_capture(
            db=mock_db,
            user_id="usr_abc",
            chat_id="12345",
            source="telegram",
            message="For today:\n\nPack for tournament\n\nGet Amy the tax documents\n\nWash my car",
            extraction={
                "tasks": [
                    {"title": "Pack for tournament", "action": "create", "due_date": "2026-03-26"},
                    {"title": "Get Amy the tax documents", "action": "create", "due_date": "2026-03-26"},
                    {"title": "Wash my car", "action": "create", "due_date": "2026-03-26"},
                ],
                "goals": [],
                "problems": [],
                "links": [],
                "reminders": [],
            },
            request_id="req_inbox_flush",
            commit=False,
            enqueue_summary=False,
        )
    )

    mock_db.flush.assert_awaited_once()
    assert applied.tasks_created == 3


def test_apply_capture_updates_targeted_reminder(mock_db):
    existing = Reminder(
        id="rem_payroll",
        user_id="usr_abc",
        title="Call Patrick",
        kind=ReminderKind.one_off,
        status=ReminderStatus.pending,
        remind_at=datetime(2026, 3, 25, 18, 0, tzinfo=timezone.utc),
        message="Old reminder",
    )
    result = Mock()
    result.scalar_one_or_none.return_value = existing
    mock_db.execute.return_value = result

    _, applied = asyncio.run(
        _apply_capture(
            db=mock_db,
            user_id="usr_abc",
            chat_id="12345",
            source="telegram",
            message="Move the Patrick reminder to tomorrow morning.",
            extraction={
                "tasks": [],
                "goals": [],
                "problems": [],
                "links": [],
                "reminders": [
                    {
                        "title": "Call Patrick",
                        "action": "update",
                        "target_reminder_id": "rem_payroll",
                        "remind_at": "2026-03-26T14:00:00Z",
                        "message": "Ask about payroll",
                    }
                ],
            },
            request_id="req_rem",
            commit=False,
            enqueue_summary=False,
        )
    )

    assert existing.title == "Call Patrick"
    assert existing.message == "Ask about payroll"
    assert existing.remind_at == datetime(2026, 3, 26, 14, 0, tzinfo=timezone.utc)
    assert applied.reminders_updated == 1
    assert applied.items[0].group == "reminder_updated"
    added_types = [type(call.args[0]) for call in mock_db.add.call_args_list if call.args]
    assert ConversationEvent in added_types
    assert ActionBatch in added_types
    assert ReminderVersion in added_types


def test_validate_extraction_payload_accepts_project_and_subtask_fields():
    extraction = {
        "tasks": [
            {"title": "Research 401k requirements in NYC", "action": "create", "kind": "project"},
            {
                "title": "Review NYC-specific rules",
                "action": "create",
                "kind": "subtask",
                "parent_title": "Research 401k requirements in NYC",
            },
        ],
        "goals": [],
        "problems": [],
        "links": [],
        "reminders": [],
    }

    _validate_extraction_payload(extraction)


def test_validate_extraction_payload_folds_goal_and_problem_entries_into_project_tasks():
    extraction = {
        "tasks": [],
        "goals": [{"title": "Finish apartment renovation", "description": "Own the full project."}],
        "problems": [{"title": "Resolve payroll discrepancy"}],
        "links": [],
        "reminders": [],
    }

    _validate_extraction_payload(extraction)

    assert extraction["goals"] == []
    assert extraction["problems"] == []
    assert extraction["tasks"] == [
        {"title": "Finish apartment renovation", "kind": "project", "notes": "Own the full project."},
        {"title": "Resolve payroll discrepancy", "kind": "project", "notes": None},
    ]


def test_apply_capture_creates_project_with_subtasks(mock_db):
    project_lookup = Mock()
    project_lookup.scalar_one_or_none.return_value = None
    parent_lookup = Mock()
    parent_lookup.scalar_one_or_none.return_value = None
    mock_db.execute.side_effect = [project_lookup, parent_lookup]

    _, applied = asyncio.run(
        _apply_capture(
            db=mock_db,
            user_id="usr_abc",
            chat_id="12345",
            source="telegram",
            message="Research 401k requirements in NYC and create subtasks for me.",
            extraction={
                "tasks": [
                    {
                        "title": "Research 401k requirements in NYC",
                        "action": "create",
                        "kind": "project",
                    },
                    {
                        "title": "Review NYC-specific rules",
                        "action": "create",
                        "kind": "subtask",
                        "parent_title": "Research 401k requirements in NYC",
                    },
                    {
                        "title": "Summarize employer filing deadlines",
                        "action": "create",
                        "kind": "subtask",
                        "parent_title": "Research 401k requirements in NYC",
                    },
                ],
                "goals": [],
                "problems": [],
                "links": [],
                "reminders": [],
            },
            request_id="req_proj",
            commit=False,
            enqueue_summary=False,
        )
    )

    created_items = [
        call.args[0]
        for call in mock_db.add.call_args_list
        if call.args and isinstance(call.args[0], WorkItem)
    ]
    assert len(created_items) == 3
    parent = next(item for item in created_items if item.kind == WorkItemKind.project)
    children = [item for item in created_items if item.kind == WorkItemKind.subtask]
    assert len(children) == 2
    assert all(child.parent_id == parent.id for child in children)
    assert applied.tasks_created == 3
    labels = [item.label for item in applied.items]
    assert "Project: Research 401k requirements in NYC" in labels
    assert "Subtask: Review NYC-specific rules" in labels
    assert "Subtask: Summarize employer filing deadlines" in labels


def test_apply_capture_promotes_existing_task_to_project(mock_db):
    existing = WorkItem(
        id="tsk_promote",
        user_id="usr_abc",
        kind=WorkItemKind.task,
        title="Apartment renovation",
        title_norm="apartment renovation",
        status=WorkItemStatus.open,
    )
    result = Mock()
    result.scalar_one_or_none.return_value = existing
    mock_db.execute.return_value = result

    _, applied = asyncio.run(
        _apply_capture(
            db=mock_db,
            user_id="usr_abc",
            chat_id="12345",
            source="telegram",
            message="Turn apartment renovation into a project.",
            extraction={
                "tasks": [
                    {
                        "title": "Apartment renovation",
                        "action": "update",
                        "target_task_id": "tsk_promote",
                        "kind": "project",
                    }
                ],
                "goals": [],
                "problems": [],
                "links": [],
                "reminders": [],
            },
            request_id="req_promote",
            commit=False,
            enqueue_summary=False,
        )
    )

    assert existing.kind == WorkItemKind.project
    assert existing.parent_id is None
    assert applied.tasks_updated == 1
    assert applied.items[0].label == "Project: Apartment renovation"


def test_action_draft_preview_groups_mixed_task_actions():
    preview = _format_action_draft_preview(
        {
            "tasks": [
                {"action": "complete", "title": "Remind Amy to find the compact backpack"},
                {"action": "update", "title": "Reach out to Ben and Jason", "notes": "Still unresolved issues", "due_date": "2026-03-25", "target_task_id": "tsk_1"},
                {"action": "create", "title": "Decide our intentions regarding Ginseng ordering"},
            ],
            "goals": [],
            "problems": [],
            "links": [],
        }
    )
    assert "Review changes" in preview
    assert "Mark complete" in preview
    assert "Update existing task" in preview
    assert "Create new task" in preview
    assert "Complete task:" in preview
    assert "Update task:" in preview
    assert "due -&gt; 2026-03-25" in preview
    assert "notes -&gt; Still unresolved issues" in preview


def test_action_draft_preview_groups_reminder_actions():
    with patch("api.main._local_today", return_value=date(2026, 3, 25)):
        preview = _format_action_draft_preview(
            {
                "tasks": [],
                "goals": [],
                "problems": [],
                "links": [],
                "reminders": [
                    {
                        "action": "create",
                        "title": "Call Patrick",
                        "remind_at": "2026-03-25T15:00:00Z",
                        "message": "Ask about payroll",
                    },
                    {
                        "action": "complete",
                        "title": "Follow up with accountant",
                        "target_reminder_id": "rem_1",
                    },
                ],
            }
        )
    assert "Create reminder" in preview
    assert "Mark reminder complete" in preview
    assert "Remind me" in preview
    assert "Complete reminder:" in preview
    assert "today at" in preview
    assert "Note: Ask about payroll" in preview


def test_action_draft_preview_shows_project_and_subtask_metadata():
    preview = _format_action_draft_preview(
        {
            "tasks": [
                {"action": "create", "kind": "project", "title": "Research 401k requirements in NYC"},
                {
                    "action": "create",
                    "kind": "subtask",
                    "title": "Review NYC-specific rules",
                    "parent_title": "Research 401k requirements in NYC",
                },
                {
                    "action": "update",
                    "kind": "project",
                    "title": "Apartment renovation",
                    "target_task_id": "tsk_proj",
                },
            ],
            "goals": [],
            "problems": [],
            "links": [],
            "reminders": [],
        }
    )
    assert "Create project:" in preview
    assert "Create subtask:" in preview
    assert "Promote to project:" in preview
    assert "parent -&gt; Research 401k requirements in NYC" in preview


def test_action_draft_preview_humanizes_reminder_schedule_when_title_matches_message():
    with patch("api.main._local_today", return_value=date(2026, 3, 26)):
        preview = _format_action_draft_preview(
            {
                "tasks": [],
                "goals": [],
                "problems": [],
                "links": [],
                "reminders": [
                    {
                        "action": "create",
                        "title": "Tell Callum about the Telegram Todo app",
                        "remind_at": "2026-03-26T23:00:00Z",
                        "message": "Tell Callum about the Telegram Todo app",
                    }
                ],
            }
        )
    assert "Remind me" in preview
    assert "today at" in preview
    assert "Tell Callum about the Telegram Todo app" in preview
    assert "message -&gt;" not in preview
    assert "at -&gt;" not in preview


def test_best_task_reference_candidate_uses_parent_title_context():
    candidate = _best_task_reference_candidate(
        "the NYC rules subtask under 401k research",
        {
            "tasks": [
                {
                    "id": "tsk_child_1",
                    "title": "Review NYC-specific rules",
                    "parent_title": "Research 401k requirements in NYC",
                    "status": "open",
                },
                {
                    "id": "tsk_other",
                    "title": "Review NYC-specific rules",
                    "parent_title": "Apartment renovation",
                    "status": "open",
                },
            ],
            "recent_task_refs": [],
            "displayed_task_refs": [],
        },
    )
    assert candidate is not None
    assert candidate["id"] == "tsk_child_1"


def test_best_reminder_reference_candidate_uses_work_item_title_context():
    candidate = _best_reminder_reference_candidate(
        "the payroll reminder for 401k research",
        {
            "recent_reminder_refs": [
                {
                    "id": "rem_401k",
                    "title": "Payroll reminder",
                    "work_item_title": "Research 401k requirements in NYC",
                    "status": "pending",
                }
            ],
            "reminders": [
                {
                    "id": "rem_401k",
                    "title": "Payroll reminder",
                    "work_item_title": "Research 401k requirements in NYC",
                    "status": "pending",
                },
                {
                    "id": "rem_apartment",
                    "title": "Payroll reminder",
                    "work_item_title": "Apartment renovation",
                    "status": "pending",
                },
            ],
        },
    )
    assert candidate is not None
    assert candidate["id"] == "rem_401k"


def test_non_command_planner_reminder_action_creates_draft(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.88,
        "needs_confirmation": True,
        "actions": [
            {
                "entity_type": "reminder",
                "action": "create",
                "title": "Call Patrick",
                "message": "Ask about payroll",
                "remind_at": "2026-03-25T15:00:00Z",
            }
        ],
    }
    fake_draft = _fake_draft(
        source_message="Remind me to call Patrick this afternoon.",
        proposal_json={"tasks": [], "goals": [], "problems": [], "links": [], "reminders": []},
    )
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value={"tasks": [], "reminders": []}
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates", new_callable=AsyncMock
    ) as extract_fallback:
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Remind me to call Patrick this afternoon."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extract_fallback.assert_not_awaited()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == []
        assert extraction["reminders"] == [
            {
                "title": "Call Patrick",
                "action": "create",
                "message": "Ask about payroll",
                "remind_at": "2026-03-25T15:00:00Z",
            }
        ]


def test_non_command_reminder_without_schedule_requests_time_clarification(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.88,
        "needs_confirmation": True,
        "actions": [
            {
                "entity_type": "reminder",
                "action": "create",
                "title": "Call Patrick",
                "message": "Ask about payroll",
            }
        ],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._stage_clarification_draft", new_callable=AsyncMock
    ) as stage_clarification, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value={"tasks": [], "reminders": []}
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ):
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Remind me to call Patrick about payroll."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        stage_clarification.assert_awaited_once()
        kwargs = stage_clarification.await_args.kwargs
        assert "When should I remind you about <code>Call Patrick</code>" in kwargs["clarification_text"]
        assert kwargs["clarification_state"]["kind"] == "reminder_schedule"


def test_non_command_unresolved_reminder_update_requests_reminder_clarification(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.9,
        "needs_confirmation": True,
        "actions": [
            {
                "entity_type": "reminder",
                "action": "update",
                "title": "Payroll reminder",
                "message": "Push it to tomorrow morning",
            }
        ],
    }
    grounding = {
        "tasks": [],
        "reminders": [
            {"id": "rem_patrick", "title": "Payroll reminder for Patrick", "status": "pending"},
            {"id": "rem_pat", "title": "Payroll reminder for Pat", "status": "pending"},
        ],
    }
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._stage_clarification_draft", new_callable=AsyncMock
    ) as stage_clarification, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ):
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Update the payroll reminder."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        stage_clarification.assert_awaited_once()
        kwargs = stage_clarification.await_args.kwargs
        assert "Which reminder do you want to update?" in kwargs["clarification_text"]
        assert kwargs["clarification_state"]["kind"] == "reminder_candidates"
        assert len(kwargs["clarification_state"]["candidates"]) == 2


def test_non_command_recent_reminder_resolution_statement_stages_completion(app_no_db, mock_extract):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 1.0,
        "needs_confirmation": True,
        "actions": [
            {
                "entity_type": "reminder",
                "action": "complete",
                "target_reminder_id": "rem_patrick",
            }
        ],
    }
    grounding = {
        "tasks": [],
        "recent_reminder_refs": [
            {
                "id": "rem_patrick",
                "title": "Check on Patrick",
                "status": "pending",
            }
        ],
        "reminders": [
            {
                "id": "rem_patrick",
                "title": "Check on Patrick",
                "status": "pending",
            }
        ],
    }
    fake_draft = _fake_draft(
        source_message="we checked on patrick, he's alright.",
        proposal_json={"tasks": [], "goals": [], "problems": [], "links": [], "reminders": []},
    )
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main.adapter.plan_actions", new_callable=AsyncMock, return_value=planned
    ), patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock, return_value={"approved": True, "issues": []}
    ), patch(
        "api.main.adapter.extract_structured_updates", new_callable=AsyncMock
    ) as extract_fallback:
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("we checked on patrick, he's alright."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_awaited_once()
        send_preview.assert_awaited_once()
        extract_fallback.assert_not_awaited()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert extraction["tasks"] == []
        assert extraction["reminders"] == [
            {
                "title": "Check on Patrick",
                "action": "complete",
                "status": "completed",
                "target_reminder_id": "rem_patrick",
            }
        ]


def test_non_command_multi_action_message_uses_richer_extract_when_planner_only_returns_one_action(app_no_db, mock_send, mock_extract):
    mock_extract.interpret_telegram_turn.return_value = {
        "speech_act": "action",
        "confidence": 0.96,
    }
    mock_extract.plan_actions.return_value = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.95,
        "needs_confirmation": True,
        "actions": [
            {
                "entity_type": "reminder",
                "action": "complete",
                "status": "completed",
                "target_reminder_id": "rem_callum",
                "title": "Tell Callum about the Telegram Todo app",
            }
        ],
    }
    mock_extract.extract_structured_updates.return_value = {
        "tasks": [
            {
                "action": "update",
                "title": "Wash my car",
                "target_task_id": "tsk_wash",
                "due_date": "2026-04-02",
            },
            {
                "action": "complete",
                "status": "done",
                "title": "Pack for tournament",
                "target_task_id": "tsk_pack",
            },
        ],
        "goals": [],
        "problems": [],
        "links": [],
        "reminders": [
            {
                "action": "complete",
                "status": "completed",
                "title": "Tell Callum about the Telegram Todo app",
                "target_reminder_id": "rem_callum",
            }
        ],
    }
    grounding = {
        "tasks": [
            {"id": "tsk_wash", "title": "Wash my car", "status": "open", "due_date": "2026-03-26"},
            {"id": "tsk_pack", "title": "Pack for tournament", "status": "open", "due_date": "2026-03-26"},
        ],
        "recent_task_refs": [
            {"id": "tsk_wash", "title": "Wash my car", "status": "open"},
            {"id": "tsk_pack", "title": "Pack for tournament", "status": "open"},
        ],
        "recent_reminder_refs": [
            {"id": "rem_callum", "title": "Tell Callum about the Telegram Todo app", "status": "pending"},
        ],
        "reminders": [
            {"id": "rem_callum", "title": "Tell Callum about the Telegram Todo app", "status": "pending"},
        ],
        "current_date_local": "2026-03-26",
        "timezone": "America/New_York",
    }
    message = 'I told callum about the app.\n\nmove the "wash car" to next week\n\nI finished packing for the tournament as well.'
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
    ), patch(
        "api.main._build_extraction_grounding", new_callable=AsyncMock, return_value=grounding
    ), patch(
        "api.main._create_action_draft", new_callable=AsyncMock, return_value=_fake_draft()
    ) as create_draft, patch(
        "api.main._send_or_edit_draft_preview", new_callable=AsyncMock
    ) as send_preview, patch(
        "api.main.adapter.critique_actions", new_callable=AsyncMock
    ) as critique_actions:
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update(message), headers=_headers())
        assert resp.status_code == 200
        critique_actions.assert_not_awaited()
        create_draft.assert_awaited_once()
        extraction = create_draft.await_args.kwargs["extraction"]
        assert len(extraction["tasks"]) == 2
        assert len(extraction["reminders"]) == 1
        assert extraction["tasks"][0]["target_task_id"] == "tsk_wash"
        assert extraction["tasks"][1]["target_task_id"] == "tsk_pack"
        assert extraction["reminders"][0]["target_reminder_id"] == "rem_callum"
        send_preview.assert_awaited_once()


def test_reminder_reference_candidates_prefer_recent_context():
    candidates = _reminder_reference_candidates(
        {
            "recent_reminder_refs": [
                {"id": "rem_recent", "title": "Payroll reminder for Patrick", "status": "pending"},
            ],
            "reminders": [
                {"id": "rem_recent", "title": "Payroll reminder for Patrick", "status": "pending"},
                {"id": "rem_other", "title": "Dentist reminder", "status": "pending"},
            ],
        }
    )
    by_id = {candidate["id"]: candidate for candidate in candidates}
    assert "recent" in by_id["rem_recent"]["sources"]
    assert "grounding" in by_id["rem_recent"]["sources"]
    assert by_id["rem_other"]["sources"] == {"grounding"}


def test_remember_recent_reminders_records_reminder_context(mock_db):
    asyncio.run(
        _remember_recent_reminders(
            db=mock_db,
            user_id="usr_abc",
            chat_id="12345",
            reminder_ids=["rem_1", "rem_1", "rem_2"],
            reason="capture_apply",
            ttl_hours=12,
        )
    )
    added = [call.args[0] for call in mock_db.add.call_args_list if call.args]
    context_items = [item for item in added if isinstance(item, RecentContextItem)]
    assert len(context_items) == 2
    assert {item.entity_id for item in context_items} == {"rem_1", "rem_2"}
    assert all(item.entity_type == EntityType.reminder for item in context_items)
