import copy
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from common.models import Reminder, ReminderStatus, WorkItem, WorkItemKind, WorkItemStatus


def run_plan_cache_key(user_id: str, chat_id: str) -> str:
    return f"plan:today:{user_id}:{chat_id}"


def run_plan_payload_generated_at(payload: Dict[str, Any], *, helpers: Dict[str, Any]) -> Optional[datetime]:
    if not isinstance(payload, dict):
        return None
    return helpers["_parse_iso_datetime"](payload.get("generated_at"))


def run_plan_payload_is_fresh(
    payload: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
    max_age_seconds: int,
) -> bool:
    generated_at = helpers["_plan_payload_generated_at"](payload)
    if not generated_at:
        return False
    age_seconds = max(0, int((helpers["utc_now"]() - generated_at).total_seconds()))
    return age_seconds <= max(1, max_age_seconds)


def run_telegram_plan_payload(payload: Dict[str, Any], *, served_from_cache: bool) -> Dict[str, Any]:
    decorated = copy.deepcopy(payload) if isinstance(payload, dict) else {}
    decorated["_served_from_cache"] = bool(served_from_cache)
    return decorated


def _telegram_view_work_item_kind(task: Any) -> str:
    raw_kind = getattr(task, "kind", None)
    if hasattr(raw_kind, "value"):
        return str(raw_kind.value or "task")
    if isinstance(raw_kind, str) and raw_kind.strip():
        return raw_kind.strip().lower()
    return "task"


def _telegram_view_work_item_status(task: Any) -> str:
    raw_status = getattr(task, "status", None)
    if hasattr(raw_status, "value"):
        return str(raw_status.value)
    return str(raw_status or "")


def _telegram_view_work_item_payload(task: Any, *, helpers: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": getattr(task, "id", None),
        "title": helpers["_canonical_task_title"](getattr(task, "title", "")),
        "kind": _telegram_view_work_item_kind(task),
        "parent_id": getattr(task, "parent_id", None),
        "status": _telegram_view_work_item_status(task),
        "due_date": helpers["work_item_due_date_text"](task),
    }


async def run_invalidate_today_plan_cache(user_id: str, chat_id: str, *, helpers: Dict[str, Any]) -> None:
    await helpers["redis_client"].delete(helpers["_plan_cache_key"](user_id, chat_id))


def run_extract_plan_task_ids(plan_payload: Dict[str, Any], *, limit: Optional[int] = None) -> List[str]:
    if not isinstance(plan_payload, dict):
        return []
    out: List[str] = []
    seen: set[str] = set()
    rows = plan_payload.get("today_plan")
    if not isinstance(rows, list):
        return out
    for item in rows:
        if not isinstance(item, dict):
            continue
        task_id = item.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id in seen:
            continue
        seen.add(task_id)
        out.append(task_id)
        if isinstance(limit, int) and limit > 0 and len(out) >= limit:
            break
    return out


async def run_cache_today_plan_payload(
    user_id: str,
    chat_id: str,
    payload: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
) -> None:
    validated = helpers["PlanResponseV1"](**payload)
    await helpers["redis_client"].setex(
        helpers["_plan_cache_key"](user_id, chat_id),
        helpers["PLAN_CACHE_TTL_SECONDS"],
        validated.model_dump_json(),
    )


async def run_build_live_today_plan_payload(db, user_id: str, *, helpers: Dict[str, Any]) -> Dict[str, Any]:
    state = await helpers["collect_planning_state"](db, user_id)
    payload = helpers["render_fallback_plan_explanation"](helpers["build_plan_payload"](state, helpers["utc_now"]()))
    try:
        return helpers["PlanResponseV1"](**payload).model_dump()
    except Exception as exc:
        helpers["logger"].error("Plan validation failed during live build for user %s: %s", user_id, exc)
        emergency_payload = {
            "schema_version": "plan.v1",
            "plan_window": "today",
            "generated_at": helpers["utc_now"]().isoformat().replace("+00:00", "Z"),
            "today_plan": [],
            "next_actions": [],
            "blocked_items": [],
            "due_reminders": [],
        }
        return helpers["PlanResponseV1"](**emergency_payload).model_dump()


async def run_load_today_plan_payload(
    db,
    user_id: str,
    chat_id: str,
    *,
    helpers: Dict[str, Any],
    require_fresh: bool = True,
) -> tuple[Dict[str, Any], bool]:
    cached = await helpers["redis_client"].get(helpers["_plan_cache_key"](user_id, chat_id))
    if cached:
        try:
            payload = helpers["PlanResponseV1"](**json.loads(cached)).model_dump()
            if not require_fresh or helpers["_plan_payload_is_fresh"](payload):
                return payload, True
        except Exception as exc:
            helpers["logger"].warning("Cached plan invalid for user %s chat %s: %s", user_id, chat_id, exc)

    payload = await helpers["_build_live_today_plan_payload"](db, user_id)
    try:
        await helpers["_cache_today_plan_payload"](user_id, chat_id, payload)
    except Exception as exc:
        helpers["logger"].warning("Failed to cache live today plan for user %s chat %s: %s", user_id, chat_id, exc)
    return payload, False


async def run_send_today_plan_view(
    db,
    user_id: str,
    chat_id: str,
    payload: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
    served_from_cache: bool,
    view_name: str,
) -> None:
    telegram_payload = helpers["_telegram_plan_payload"](payload, served_from_cache=served_from_cache)
    if view_name == "focus":
        text = helpers["format_focus_mode"](telegram_payload)
        task_ids = helpers["_extract_plan_task_ids"](telegram_payload, limit=3)
    else:
        text = helpers["format_today_plan"](telegram_payload)
        task_ids = helpers["_extract_plan_task_ids"](telegram_payload)
    visible_due_reminders = (telegram_payload.get("due_reminders") or [])[:8]
    reminder_ids = [
        item.get("reminder_id")
        for item in visible_due_reminders
        if isinstance(item, dict) and isinstance(item.get("reminder_id"), str) and item.get("reminder_id")
    ]
    sent = await helpers["send_message"](chat_id, text)
    if not (isinstance(sent, dict) and sent.get("ok") is True):
        return
    updated_context = False
    if task_ids:
        await helpers["_remember_displayed_tasks"](db, user_id, chat_id, task_ids, view_name)
        updated_context = True
    if reminder_ids:
        await helpers["_remember_recent_reminders"](
            db=db,
            user_id=user_id,
            chat_id=chat_id,
            reminder_ids=reminder_ids,
            reason=f"{view_name}_view",
            ttl_hours=12,
        )
        updated_context = True
    if updated_context:
        await db.commit()
    if "_get_or_create_session" in helpers and "_update_session_state" in helpers:
        session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=chat_id)
        active_entity_refs = [
            {"entity_type": "work_item", "entity_id": item["task_id"], "title": item["title"], "source": view_name}
            for item in (telegram_payload.get("today_plan") or [])
            if isinstance(item, dict)
            and isinstance(item.get("task_id"), str)
            and item.get("task_id")
            and isinstance(item.get("title"), str)
        ]
        active_entity_refs.extend(
            [
                {
                    "entity_type": "reminder",
                    "entity_id": item["reminder_id"],
                    "title": str(item.get("title") or "").strip() or str(item.get("message") or "").strip(),
                    "source": view_name,
                }
                for item in visible_due_reminders
                if isinstance(item, dict)
                and isinstance(item.get("reminder_id"), str)
                and item.get("reminder_id")
                and (str(item.get("title") or "").strip() or str(item.get("message") or "").strip())
            ]
        )
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode=view_name,
            active_entity_refs=active_entity_refs[:12],
            pending_draft_id=None,
            pending_clarification=None,
        )


async def run_send_urgent_task_view(db, user_id: str, chat_id: str, *, helpers: Dict[str, Any]) -> None:
    urgent_tasks = (
        await db.execute(
            select(WorkItem)
            .where(
                WorkItem.user_id == user_id,
                WorkItem.kind.in_([WorkItemKind.project, WorkItemKind.task, WorkItemKind.subtask]),
                WorkItem.status.in_([WorkItemStatus.open, WorkItemStatus.blocked]),
                WorkItem.priority == 1,
            )
            .order_by(WorkItem.due_at.asc().nulls_last(), WorkItem.updated_at.desc())
            .limit(12)
        )
    ).scalars().all()
    payload = [_telegram_view_work_item_payload(task, helpers=helpers) for task in urgent_tasks]
    sent = await helpers["send_message"](chat_id, helpers["format_urgent_tasks"](payload))
    if not (isinstance(sent, dict) and sent.get("ok") is True):
        return
    task_ids = [task["id"] for task in payload if isinstance(task.get("id"), str) and task.get("id")]
    if task_ids:
        await helpers["_remember_displayed_tasks"](db, user_id, chat_id, task_ids, "urgent")
        await db.commit()
    if "_get_or_create_session" in helpers and "_update_session_state" in helpers:
        session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=chat_id)
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode="urgent",
            active_entity_refs=[
                {"entity_type": "work_item", "entity_id": item["id"], "title": item["title"], "source": "urgent"}
                for item in payload
                if isinstance(item.get("id"), str) and item.get("id") and isinstance(item.get("title"), str)
            ][:12],
            pending_draft_id=None,
            pending_clarification=None,
        )


async def run_send_open_task_view(db, user_id: str, chat_id: str, *, helpers: Dict[str, Any]) -> None:
    open_tasks = (
        await db.execute(
            select(WorkItem)
            .where(
                WorkItem.user_id == user_id,
                WorkItem.kind.in_([WorkItemKind.project, WorkItemKind.task, WorkItemKind.subtask]),
                WorkItem.status.in_([WorkItemStatus.open, WorkItemStatus.blocked]),
            )
            .order_by(WorkItem.priority.asc(), WorkItem.due_at.asc().nulls_last(), WorkItem.updated_at.desc())
            .limit(60)
        )
    ).scalars().all()
    payload = [_telegram_view_work_item_payload(task, helpers=helpers) for task in open_tasks]
    sent = await helpers["send_message"](chat_id, helpers["format_open_tasks"](payload))
    if not (isinstance(sent, dict) and sent.get("ok") is True):
        return
    task_ids = [task["id"] for task in payload if isinstance(task.get("id"), str) and task.get("id")]
    if task_ids:
        await helpers["_remember_displayed_tasks"](db, user_id, chat_id, task_ids, "open")
        await db.commit()
    if "_get_or_create_session" in helpers and "_update_session_state" in helpers:
        session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=chat_id)
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode="open_tasks",
            active_entity_refs=[
                {"entity_type": "work_item", "entity_id": item["id"], "title": item["title"], "source": "open_tasks"}
                for item in payload
                if isinstance(item.get("id"), str) and item.get("id") and isinstance(item.get("title"), str)
            ][:12],
            pending_draft_id=None,
            pending_clarification=None,
        )


def _telegram_view_local_date(value: Any, *, helpers: Dict[str, Any]) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    tz_name = (helpers["settings"].APP_TIMEZONE or "").strip() or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    return value.astimezone(tz)


def _telegram_view_next_week_range(*, helpers: Dict[str, Any]) -> tuple[datetime, datetime, str]:
    local_today = helpers["_local_today"]()
    days_until_next_monday = (7 - local_today.weekday()) % 7
    if days_until_next_monday == 0:
        days_until_next_monday = 7
    start_date = local_today + timedelta(days=days_until_next_monday)
    end_date = start_date + timedelta(days=6)
    label = f"Week of {start_date.month}/{start_date.day}/{start_date.year}"
    return (
        datetime(start_date.year, start_date.month, start_date.day, 0, 0, tzinfo=timezone.utc),
        datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc),
        label,
    )


async def run_send_due_today_view(db, user_id: str, chat_id: str, *, helpers: Dict[str, Any]) -> None:
    local_today = helpers["_local_today"]()
    due_candidates = (
        await db.execute(
            select(WorkItem)
            .where(
                WorkItem.user_id == user_id,
                WorkItem.kind.in_([WorkItemKind.project, WorkItemKind.task, WorkItemKind.subtask]),
                WorkItem.status.in_([WorkItemStatus.open, WorkItemStatus.blocked]),
                WorkItem.due_at.is_not(None),
            )
            .order_by(WorkItem.priority.asc(), WorkItem.due_at.asc(), WorkItem.updated_at.desc())
            .limit(40)
        )
    ).scalars().all()
    due_tasks = []
    for task in due_candidates:
        local_due_at = _telegram_view_local_date(getattr(task, "due_at", None), helpers=helpers)
        if local_due_at is None or local_due_at.date() != local_today:
            continue
        due_tasks.append(_telegram_view_work_item_payload(task, helpers=helpers))

    reminder_candidates = (
        await db.execute(
            select(Reminder)
            .where(
                Reminder.user_id == user_id,
                Reminder.status == ReminderStatus.pending,
            )
            .order_by(Reminder.remind_at.asc(), Reminder.updated_at.desc())
            .limit(20)
        )
    ).scalars().all()
    due_reminders = []
    for reminder in reminder_candidates:
        local_remind_at = _telegram_view_local_date(getattr(reminder, "remind_at", None), helpers=helpers)
        if local_remind_at is None or local_remind_at.date() != local_today:
            continue
        due_reminders.append(
            {
                "id": reminder.id,
                "title": reminder.title,
                "remind_at": reminder.remind_at.isoformat() if isinstance(reminder.remind_at, datetime) else None,
                "message": reminder.message,
            }
        )

    sent = await helpers["send_message"](chat_id, helpers["format_due_today"](due_tasks, due_reminders))
    if not (isinstance(sent, dict) and sent.get("ok") is True):
        return
    task_ids = [task["id"] for task in due_tasks if isinstance(task.get("id"), str) and task.get("id")]
    if task_ids:
        await helpers["_remember_displayed_tasks"](db, user_id, chat_id, task_ids, "due_today")
        await db.commit()
    reminder_ids = [item["id"] for item in due_reminders if isinstance(item.get("id"), str) and item.get("id")]
    if reminder_ids and "_remember_recent_reminders" in helpers:
        await helpers["_remember_recent_reminders"](
            db=db,
            user_id=user_id,
            chat_id=chat_id,
            reminder_ids=reminder_ids,
            reason="due_today_view",
            ttl_hours=12,
        )
    if "_get_or_create_session" in helpers and "_update_session_state" in helpers:
        session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=chat_id)
        active_refs = [
            {"entity_type": "work_item", "entity_id": item["id"], "title": item["title"], "source": "due_today"}
            for item in due_tasks
            if isinstance(item.get("id"), str) and item.get("id") and isinstance(item.get("title"), str)
        ][:12]
        active_refs.extend(
            {
                "entity_type": "reminder",
                "entity_id": item["id"],
                "title": item["title"],
                "source": "due_today",
            }
            for item in due_reminders
            if isinstance(item.get("id"), str) and item.get("id") and isinstance(item.get("title"), str)
        )
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode="due_today",
            active_entity_refs=active_refs[:12],
            pending_draft_id=None,
            pending_clarification=None,
        )


async def run_send_due_next_week_view(db, user_id: str, chat_id: str, *, helpers: Dict[str, Any]) -> None:
    range_start_utc, range_end_utc, week_label = _telegram_view_next_week_range(helpers=helpers)
    local_start = _telegram_view_local_date(range_start_utc, helpers=helpers)
    local_end = _telegram_view_local_date(range_end_utc, helpers=helpers)
    if local_start is None or local_end is None:
        return

    due_candidates = (
        await db.execute(
            select(WorkItem)
            .where(
                WorkItem.user_id == user_id,
                WorkItem.kind.in_([WorkItemKind.project, WorkItemKind.task, WorkItemKind.subtask]),
                WorkItem.status.in_([WorkItemStatus.open, WorkItemStatus.blocked]),
                WorkItem.due_at.is_not(None),
            )
            .order_by(WorkItem.due_at.asc(), WorkItem.priority.asc().nulls_last(), WorkItem.updated_at.desc())
            .limit(60)
        )
    ).scalars().all()
    due_tasks = []
    for task in due_candidates:
        local_due_at = _telegram_view_local_date(getattr(task, "due_at", None), helpers=helpers)
        if local_due_at is None:
            continue
        if local_start.date() <= local_due_at.date() <= local_end.date():
            due_tasks.append(_telegram_view_work_item_payload(task, helpers=helpers))

    reminder_candidates = (
        await db.execute(
            select(Reminder)
            .where(
                Reminder.user_id == user_id,
                Reminder.status == ReminderStatus.pending,
            )
            .order_by(Reminder.remind_at.asc(), Reminder.updated_at.desc())
            .limit(30)
        )
    ).scalars().all()
    due_reminders = []
    for reminder in reminder_candidates:
        local_remind_at = _telegram_view_local_date(getattr(reminder, "remind_at", None), helpers=helpers)
        if local_remind_at is None:
            continue
        if local_start.date() <= local_remind_at.date() <= local_end.date():
            due_reminders.append(
                {
                    "id": reminder.id,
                    "title": reminder.title,
                    "remind_at": reminder.remind_at.isoformat() if isinstance(reminder.remind_at, datetime) else None,
                    "message": reminder.message,
                }
            )

    sent = await helpers["send_message"](
        chat_id,
        helpers["format_due_next_week"](due_tasks, due_reminders, week_label=week_label),
    )
    if not (isinstance(sent, dict) and sent.get("ok") is True):
        return
    task_ids = [task["id"] for task in due_tasks if isinstance(task.get("id"), str) and task.get("id")]
    if task_ids:
        await helpers["_remember_displayed_tasks"](db, user_id, chat_id, task_ids, "due_next_week")
        await db.commit()
    reminder_ids = [item["id"] for item in due_reminders if isinstance(item.get("id"), str) and item.get("id")]
    if reminder_ids and "_remember_recent_reminders" in helpers:
        await helpers["_remember_recent_reminders"](
            db=db,
            user_id=user_id,
            chat_id=chat_id,
            reminder_ids=reminder_ids,
            reason="due_next_week_view",
            ttl_hours=12,
        )
    if "_get_or_create_session" in helpers and "_update_session_state" in helpers:
        session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=chat_id)
        active_refs = [
            {"entity_type": "work_item", "entity_id": item["id"], "title": item["title"], "source": "due_next_week"}
            for item in due_tasks
            if isinstance(item.get("id"), str) and item.get("id") and isinstance(item.get("title"), str)
        ][:12]
        active_refs.extend(
            {
                "entity_type": "reminder",
                "entity_id": item["id"],
                "title": item["title"],
                "source": "due_next_week",
            }
            for item in due_reminders
            if isinstance(item.get("id"), str) and item.get("id") and isinstance(item.get("title"), str)
        )
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode="due_next_week",
            active_entity_refs=active_refs[:12],
            pending_draft_id=None,
            pending_clarification=None,
        )


async def run_stage_clarification_draft(
    db,
    user_id: str,
    chat_id: str,
    message: str,
    extraction: Dict[str, Any],
    request_id: str,
    clarification_text: str,
    *,
    helpers: Dict[str, Any],
    clarification_candidates: Optional[List[Dict[str, Any]]] = None,
    clarification_state: Optional[Dict[str, Any]] = None,
) -> None:
    draft = await helpers["_create_action_draft"](
        db=db,
        user_id=user_id,
        chat_id=chat_id,
        message=message,
        extraction=extraction,
        request_id=request_id,
    )
    helpers["_draft_set_awaiting_edit_input"](draft, True)
    state = clarification_state if isinstance(clarification_state, dict) else None
    if state is None and isinstance(clarification_candidates, list) and clarification_candidates:
        state = {"kind": "task_candidates", "candidates": clarification_candidates[:4]}
    if state is not None:
        helpers["_draft_set_clarification_state"](draft, state)
    if isinstance(clarification_candidates, list) and clarification_candidates and (
        not isinstance(state, dict) or state.get("kind") in {None, "task_candidates"}
    ):
        candidate_ids = [
            row.get("id")
            for row in clarification_candidates
            if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("id")
        ]
        if candidate_ids:
            await helpers["_remember_recent_tasks"](
                db=db,
                user_id=user_id,
                chat_id=chat_id,
                task_ids=candidate_ids,
                reason="clarification_candidates",
                ttl_hours=12,
            )
    if isinstance(clarification_candidates, list) and clarification_candidates and isinstance(state, dict) and state.get(
        "kind"
    ) == "reminder_candidates":
        candidate_ids = [
            row.get("id")
            for row in clarification_candidates
            if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("id")
        ]
        if candidate_ids:
            await helpers["_remember_recent_reminders"](
                db=db,
                user_id=user_id,
                chat_id=chat_id,
                reminder_ids=candidate_ids,
                reason="clarification_candidates",
                ttl_hours=12,
            )
    draft.updated_at = helpers["_draft_now"]()
    draft.expires_at = helpers["_draft_now"]() + timedelta(seconds=helpers["ACTION_DRAFT_TTL_SECONDS"])
    await db.commit()
    if "_get_or_create_session" in helpers and "_update_session_state" in helpers:
        session = await helpers["_get_or_create_session"](db=db, user_id=user_id, chat_id=chat_id)
        await helpers["_update_session_state"](
            db=db,
            session=session,
            current_mode="draft",
            active_entity_refs=helpers["_session_state_payload"](session).get("active_entity_refs", []),
            pending_draft_id=draft.id,
            pending_clarification=state,
        )
    await helpers["send_message"](chat_id, clarification_text)
