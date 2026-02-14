"""Phase 4 Telegram webhook tests (spec cases 1-9) with stable boundaries.

These tests validate:
- webhook auth/ingest behavior
- command parsing/routing
- command semantics via handle_telegram_command
- non-command capture integration path
"""
import asyncio
import json
from datetime import datetime, date
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from api.main import (
    handle_telegram_command,
    _draft_set_awaiting_edit_input,
    _draft_set_proposal_message_id,
)
from api.schemas import AppliedChanges, QueryResponseV1
from common.config import settings

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
    mock_extract.extract_structured_updates.return_value = {
        "tasks": [],
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
        create_draft.assert_not_awaited()
        assert "could not find open matching tasks to complete" in mock_send.await_args.args[1].lower()


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
            json=_tg_update("Reading the chapter, memorizing the script, and the french homework are all done. Mark them as complete."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_not_awaited()
        assert "could not find open matching tasks to complete" in mock_send.await_args.args[1].lower()


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
            json=_tg_update("Update my reminder for Gil"),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_not_awaited()
        apply_capture.assert_not_awaited()
        assert mock_send.await_count >= 1
        msg = mock_send.await_args_list[-1].args[1]
        assert "I need one clarification before applying changes" in msg
        assert "Which existing task should I update" in msg


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
            {"entity_type": "task", "action": "create", "title": "Do 100 pushups"},
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


def test_completion_request_with_already_done_tasks_prompts_no_open_match(app_no_db, mock_send):
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
        assert "could not find open matching tasks" in mock_send.await_args.args[1].lower()


def test_soft_completion_statement_without_resolved_actions_requests_clarification(app_no_db, mock_send):
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
            json=_tg_update("I cleaned the keyboard already."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_not_awaited()
        assert "could not find open matching tasks to complete" in mock_send.await_args.args[1].lower()


def test_completion_high_confidence_without_actionable_entities_does_not_autopilot(app_no_db, mock_send):
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
        "api.main._enqueue_todoist_sync_job", new_callable=AsyncMock
    ) as enqueue_sync, patch(
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
        apply_capture.return_value = ("inb_1", AppliedChanges(tasks_updated=2))
        resp = _post(
            app_no_db,
            WEBHOOK_URL,
            json=_tg_update("Mark French homework and memorize script as complete."),
            headers=_headers(),
        )
        assert resp.status_code == 200
        create_draft.assert_not_awaited()
        apply_capture.assert_not_awaited()
        enqueue_sync.assert_not_awaited()
        assert "could not find open matching tasks to complete" in mock_send.await_args.args[1].lower()


def test_create_intent_autopilot_sanitizes_and_creates_from_message(app_no_db, mock_send):
    planned = {
        "intent": "action",
        "scope": "single",
        "confidence": 0.95,
        "needs_confirmation": False,
        "actions": [{"entity_type": "task", "action": "update", "title": "Do 100 burpees"}],
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
        "api.main._enqueue_todoist_sync_job", new_callable=AsyncMock
    ), patch(
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
        apply_capture.assert_not_awaited()
        create_draft.assert_not_awaited()
        assert "could not find open matching tasks to complete" in mock_send.await_args.args[1].lower()


def test_tonight_forces_local_today_due_date(app_no_db, mock_send):
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
        assert extraction["tasks"][0]["due_date"] == "2026-02-12"


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
        "api.main._enqueue_todoist_sync_job", new_callable=AsyncMock
    ), patch(
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


def test_non_command_question_routes_to_query_no_capture(app_no_db, mock_send):
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main.query_ask", new_callable=AsyncMock
    ) as mocked_query, patch("api.main._apply_capture", new_callable=AsyncMock) as apply_capture, patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=None
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


def test_non_command_yes_applies_open_draft(app_no_db, mock_send):
    fake_draft = type("Draft", (), {"id": "drf_1", "source_message": "plan kitchen", "proposal_json": {"tasks": [{"title": "Task A"}]}})()
    with patch("api.main._resolve_telegram_user", new_callable=AsyncMock, return_value="usr_123"), patch(
        "api.main._get_open_action_draft", new_callable=AsyncMock, return_value=fake_draft
    ), patch("api.main._confirm_action_draft", new_callable=AsyncMock) as confirm_draft:
        confirm_draft.return_value = AppliedChanges(tasks_created=1)
        resp = _post(app_no_db, WEBHOOK_URL, json=_tg_update("yes"), headers=_headers())
        assert resp.status_code == 200
        confirm_draft.assert_awaited_once()
        assert "task(s) created" in mock_send.await_args.args[1].lower()


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
        assert "proposed updates" in mock_send.await_args.args[1].lower()


def test_revise_edits_existing_proposal_message_in_place(app_no_db, mock_send):
    fake_draft = type(
        "Draft",
        (),
        {
            "id": "drf_1",
            "source_message": "plan kitchen",
            "proposal_json": {"tasks": [{"title": "Task A"}], "_meta": {"proposal_message_id": 321}},
            "updated_at": datetime.utcnow(),
            "expires_at": datetime.utcnow(),
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
    assert "Plan refresh enqueued" in mock_send.await_args.args[1]


def test_command_ask_returns_query_answer(mock_send, mock_db):
    with patch("api.main.query_ask", new_callable=AsyncMock) as mocked_query:
        mocked_query.return_value = QueryResponseV1(answer="You have no blocked tasks.", confidence=0.95)
        asyncio.run(handle_telegram_command("/ask", "what is blocked", "12345", "usr_abc", mock_db))
    mocked_query.assert_awaited_once()
    assert "no blocked tasks" in mock_send.await_args.args[1]


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
