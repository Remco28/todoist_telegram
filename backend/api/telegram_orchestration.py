import hashlib
import secrets
import uuid
from datetime import timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select

from common.models import (
    ConversationDirection,
    ConversationEvent,
    ConversationSource,
    TelegramLinkToken,
    TelegramUserMap,
    VersionOperation,
    WorkItem,
    WorkItemKind,
    WorkItemStatus,
)


async def run_handle_telegram_command(
    command: str,
    args: Optional[str],
    chat_id: str,
    user_id: str,
    db,
    *,
    helpers: Dict[str, Any],
):
    if command == "/today":
        payload, served_from_cache = await helpers["_load_today_plan_payload"](
            db,
            user_id,
            chat_id,
            require_fresh=True,
        )
        await helpers["_send_today_plan_view"](
            db,
            user_id,
            chat_id,
            payload,
            served_from_cache=served_from_cache,
            view_name="today",
        )

    elif command == "/urgent":
        await helpers["_send_urgent_task_view"](db, user_id, chat_id)

    elif command == "/web":
        url = helpers["_build_workbench_url"](user_id)
        if not url:
            await helpers["send_message"](
                chat_id,
                "Web workbench is not configured yet.\n"
                "Set <code>WEB_UI_BASE_URL</code> to your public <code>/app</code> URL.",
            )
            return
        token_included = "token=" in url
        note = (
            "This link includes your API token. Treat it like a secret."
            if token_included
            else "You may need to paste your API token into the page the first time."
        )
        await helpers["send_message"](
            chat_id,
            f'Open the <a href="{helpers["escape_html"](url)}">web workbench</a>.\n'
            f"<i>{helpers['escape_html'](note)}</i>",
        )

    elif command == "/plan":
        await helpers["send_message"](
            chat_id,
            "Manual plan refresh is no longer part of normal use.\nUse <code>/today</code> to see the latest plan.",
        )

    elif command == "/focus":
        await helpers["send_message"](
            chat_id,
            "Ask naturally instead, for example:\n<code>What should I focus on right now?</code>",
        )

    elif command == "/done":
        if not args:
            await helpers["send_message"](
                chat_id,
                "Reply with a list number from your latest visible plan list.\n"
                "Example: <code>/done 2</code>.\n"
                "Advanced: you can still use <code>/done tsk_123</code> if needed.",
            )
            return

        task_ref = args.strip()
        task_id = task_ref
        if task_ref.isdigit():
            task_id = await helpers["_resolve_displayed_task_id"](db, user_id, chat_id, int(task_ref))
            if not task_id:
                await helpers["send_message"](
                    chat_id,
                    "I could not match that list number from your most recent visible plan list.\n"
                    "Use <code>/today</code> first, or ask what to focus on, then retry "
                    "<code>/done &lt;number&gt;</code>.\n"
                    "Advanced: you can still use <code>/done tsk_123</code> if needed.",
                )
                return

        task = (
            await db.execute(
                select(WorkItem).where(
                    WorkItem.id == task_id,
                    WorkItem.user_id == user_id,
                    WorkItem.kind.in_([WorkItemKind.task, WorkItemKind.subtask]),
                )
            )
        ).scalar_one_or_none()
        if not task:
            await helpers["send_message"](
                chat_id,
                f"Task <code>{helpers['escape_html'](task_ref)}</code> not found or not owned by you.",
            )
            return

        before_snapshot: Dict[str, Any] = {}
        canonical_title = helpers["_canonical_task_title"](task.title)
        if canonical_title and task.title != canonical_title:
            task.title = canonical_title
            task.title_norm = canonical_title.lower().strip()

        before_snapshot = helpers["work_item_snapshot"](task)
        task.status = WorkItemStatus.done
        task.completed_at = helpers["utc_now"]()
        task.updated_at = helpers["utc_now"]()
        after_snapshot = helpers["work_item_snapshot"](task)
        work_item_id = task.id

        conversation_event = ConversationEvent(
            id=f"cev_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            chat_id=chat_id,
            source=ConversationSource.telegram,
            direction=ConversationDirection.inbound,
            content_text=f"/done {task_ref}",
            normalized_text=f"/done {task_ref}",
            metadata_json={"command": "/done", "task_ref": task_ref},
            created_at=helpers["utc_now"](),
        )
        db.add(conversation_event)
        if work_item_id:
            await helpers["_record_work_item_action_batch"](
                db,
                user_id=user_id,
                conversation_event_id=conversation_event.id,
                source_message=f"/done {task_ref}",
                proposal_json={"tasks": [{"target_task_id": work_item_id, "action": "complete", "status": "done"}]},
                version_records=[
                    {
                        "work_item_id": work_item_id,
                        "operation": VersionOperation.complete,
                        "before_json": before_snapshot,
                        "after_json": after_snapshot,
                    }
                ],
            )
        await db.commit()
        try:
            await helpers["_invalidate_today_plan_cache"](user_id, chat_id)
        except Exception as exc:
            helpers["logger"].error(
                "Failed to invalidate today plan cache after /done for user %s chat %s: %s",
                user_id,
                chat_id,
                exc,
            )
        await helpers["send_message"](
            chat_id,
            f"Marked as done: <b>{helpers['escape_html'](helpers['_canonical_task_title'](task.title))}</b>.",
        )

    elif command == "/ask":
        await helpers["send_message"](
            chat_id,
            "Just ask the question directly without <code>/ask</code>.\n"
            "Example: <code>What tasks are overdue?</code>",
        )

    else:
        supported = "/today - Show what needs attention today\n/urgent - Show high-priority items\n/web - Open the web workbench"
        await helpers["send_message"](chat_id, f"Unknown command. Supported:\n{supported}")


def run_hash_link_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def run_build_telegram_deep_link(raw_token: str, *, helpers: Dict[str, Any]) -> Optional[str]:
    if helpers["settings"].TELEGRAM_DEEP_LINK_BASE_URL:
        return f"{helpers['settings'].TELEGRAM_DEEP_LINK_BASE_URL}{raw_token}"
    if helpers["settings"].TELEGRAM_BOT_USERNAME:
        return f"https://t.me/{helpers['settings'].TELEGRAM_BOT_USERNAME}?start={raw_token}"
    return None


def run_preferred_auth_token_for_user(user_id: str, *, helpers: Dict[str, Any]) -> Optional[str]:
    for token, mapped_user in helpers["settings"].token_user_map.items():
        if mapped_user == user_id:
            return token
    auth_tokens = helpers["settings"].auth_tokens
    if len(auth_tokens) == 1:
        return auth_tokens[0]
    return None


def run_build_workbench_url(user_id: str, *, helpers: Dict[str, Any]) -> Optional[str]:
    raw = (helpers["settings"].WEB_UI_BASE_URL or "").strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    path = parts.path or ""
    if path in {"", "/"}:
        path = "/app"
    query_pairs = dict(parse_qsl(parts.query, keep_blank_values=True))
    token = helpers["_preferred_auth_token_for_user"](user_id)
    if token and "token" not in query_pairs:
        query_pairs["token"] = token
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query_pairs), parts.fragment))


async def run_issue_telegram_link_token(user_id: str, db, *, helpers: Dict[str, Any]):
    raw_token = secrets.token_urlsafe(24)
    if helpers["settings"].TELEGRAM_LINK_TOKEN_TTL_SECONDS <= 0:
        expires_at = helpers["utc_now"]() + timedelta(days=36500)
    else:
        expires_at = helpers["utc_now"]() + timedelta(seconds=helpers["settings"].TELEGRAM_LINK_TOKEN_TTL_SECONDS)
    record = TelegramLinkToken(
        id=f"tlt_{uuid.uuid4().hex[:12]}",
        token_hash=helpers["_hash_link_token"](raw_token),
        user_id=user_id,
        expires_at=expires_at,
        consumed_at=None,
        created_at=helpers["utc_now"](),
    )
    db.add(record)
    await db.commit()
    return helpers["TelegramLinkTokenCreateResponse"](
        link_token=raw_token,
        expires_at=expires_at,
        deep_link=helpers["_build_telegram_deep_link"](raw_token),
    )


async def run_resolve_telegram_user(chat_id: str, db, *, helpers: Dict[str, Any]) -> Optional[str]:
    stmt = select(TelegramUserMap).where(TelegramUserMap.chat_id == chat_id)
    mapping = (await db.execute(stmt)).scalar_one_or_none()
    if not mapping:
        return None
    mapping.last_seen_at = helpers["utc_now"]()
    await db.commit()
    return mapping.user_id


async def run_consume_telegram_link_token(
    chat_id: str,
    username: Optional[str],
    raw_token: str,
    db,
    *,
    helpers: Dict[str, Any],
) -> bool:
    token_hash = helpers["_hash_link_token"](raw_token.strip())
    stmt = select(TelegramLinkToken).where(TelegramLinkToken.token_hash == token_hash)
    token_row = (await db.execute(stmt)).scalar_one_or_none()
    if not token_row:
        return False
    if token_row.consumed_at is not None:
        return False
    expires_at = token_row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if helpers["settings"].TELEGRAM_LINK_TOKEN_TTL_SECONDS > 0 and expires_at < helpers["utc_now"]():
        return False

    mapping_stmt = select(TelegramUserMap).where(TelegramUserMap.chat_id == chat_id)
    mapping = (await db.execute(mapping_stmt)).scalar_one_or_none()
    now = helpers["utc_now"]()
    if mapping:
        mapping.user_id = token_row.user_id
        mapping.telegram_username = username
        mapping.linked_at = now
        mapping.last_seen_at = now
    else:
        db.add(
            TelegramUserMap(
                id=f"tgm_{uuid.uuid4().hex[:12]}",
                chat_id=chat_id,
                user_id=token_row.user_id,
                telegram_username=username,
                linked_at=now,
                last_seen_at=now,
            )
        )
    token_row.consumed_at = now
    await db.commit()
    return True


async def run_handle_telegram_callback_update(data: Dict[str, Any], db, *, helpers: Dict[str, Any]) -> None:
    chat_id = data["chat_id"]
    callback_query_id = data.get("callback_query_id")
    callback_data = data.get("callback_data", "")
    request_id = f"tg_{uuid.uuid4().hex[:8]}"

    user_id = await helpers["_resolve_telegram_user"](chat_id, db)
    if not user_id:
        if callback_query_id:
            await helpers["answer_callback_query"](callback_query_id, "Chat is not linked.")
        return
    session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=chat_id)

    open_draft = await helpers["_get_open_action_draft"](user_id=user_id, chat_id=chat_id, db=db)
    action, draft_id = helpers["_parse_draft_callback"](callback_data)
    if callback_query_id:
        await helpers["answer_callback_query"](callback_query_id)
    if not open_draft or not action or draft_id != open_draft.id:
        await helpers["send_message"](chat_id, "This proposal is no longer active. Send a new message to continue.")
        return

    if action == "confirm":
        applied = await helpers["_confirm_action_draft"](
            draft=open_draft,
            user_id=user_id,
            chat_id=chat_id,
            request_id=request_id,
            db=db,
        )
        await helpers["send_message"](chat_id, helpers["format_capture_ack"](applied.model_dump()))
    elif action == "discard":
        await helpers["_discard_action_draft"](open_draft, user_id=user_id, request_id=request_id, db=db)
        await helpers["send_message"](chat_id, "Discarded the pending proposal.")
    elif action == "edit":
        helpers["_draft_set_awaiting_edit_input"](open_draft, True)
        open_draft.updated_at = helpers["_draft_now"]()
        open_draft.expires_at = helpers["_draft_now"]() + timedelta(seconds=helpers["ACTION_DRAFT_TTL_SECONDS"])
        await db.commit()
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode="draft",
            active_entity_refs=helpers["_session_state_payload"](session).get("active_entity_refs", []),
            pending_draft_id=open_draft.id,
            pending_clarification=helpers["_draft_get_clarification_state"](open_draft),
        )
        await helpers["send_message"](
            chat_id,
            "Reply with your changes in one message, and I will revise the proposal.",
        )


async def run_handle_telegram_message_update(data: Dict[str, Any], db, *, helpers: Dict[str, Any]) -> None:
    chat_id = data["chat_id"]
    text = data.get("text", "")
    username = data.get("username")
    client_msg_id = data.get("client_msg_id")

    command, args = helpers["extract_command"](text)
    if command:
        if command == "/start":
            if args and await helpers["_consume_telegram_link_token"](chat_id, username, args, db):
                await helpers["send_message"](
                    chat_id,
                    "Telegram linked successfully. You can now send thoughts and commands.",
                )
            else:
                await helpers["send_message"](
                    chat_id,
                    "Link failed. Request a new link token from the API and try again.",
                )
            return

        user_id = await helpers["_resolve_telegram_user"](chat_id, db)
        if not user_id:
            await helpers["send_message"](
                chat_id,
                "This chat is not linked yet. Use /start <token> from your generated link token.",
            )
            return
        session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=chat_id)
        await helpers["handle_telegram_command"](command, args, chat_id, user_id, db)
        if command == "/web":
            await helpers["_update_session_state"](
                db=db,
                session=session,
                current_mode="web",
                active_entity_refs=helpers["_session_state_payload"](session).get("active_entity_refs", []),
                pending_draft_id=None,
                pending_clarification=None,
            )
        return

    user_id = await helpers["_resolve_telegram_user"](chat_id, db)
    if not user_id:
        await helpers["send_message"](
            chat_id,
            "This chat is not linked yet. Use /start <token> from your generated link token.",
        )
        return
    await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=chat_id)
    await helpers["_handle_telegram_draft_flow"](
        chat_id=chat_id,
        text=text,
        client_msg_id=client_msg_id,
        user_id=user_id,
        db=db,
    )
