import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from common.models import EntityType, RecentContextItem, Reminder, ReminderStatus, WorkItem, WorkItemKind, WorkItemStatus


def run_grounding_terms(message: str) -> set[str]:
    terms = set(re.findall(r"[a-zA-Z0-9]{3,}", (message or "").lower()))
    return {t for t in terms if t not in {"the", "and", "for", "with", "that", "this", "from", "have", "need"}}


async def run_build_extraction_grounding(
    db,
    user_id: str,
    chat_id: str,
    *,
    helpers: Dict[str, Any],
    message: str = "",
) -> Dict[str, Any]:
    task_rows = (
        await db.execute(
            select(WorkItem)
            .where(
                WorkItem.user_id == user_id,
                WorkItem.kind.in_([WorkItemKind.task, WorkItemKind.subtask]),
                WorkItem.status != WorkItemStatus.archived,
            )
            .order_by(WorkItem.updated_at.desc())
            .limit(80)
        )
    ).scalars().all()
    parent_ids = {
        task.parent_id
        for task in task_rows
        if isinstance(getattr(task, "parent_id", None), str) and task.parent_id.strip()
    }
    parent_titles_by_id: Dict[str, str] = {}
    if parent_ids:
        parent_rows = (
            await db.execute(
                select(WorkItem).where(
                    WorkItem.user_id == user_id,
                    WorkItem.id.in_(parent_ids),
                )
            )
        ).scalars().all()
        parent_titles_by_id = {
            parent.id: helpers["_canonical_task_title"](parent.title)
            for parent in parent_rows
            if isinstance(parent.id, str) and parent.id.strip()
        }
    prepared = []
    terms = helpers["_grounding_terms"](message)
    for idx, task in enumerate(task_rows):
        visible_title = helpers["_canonical_task_title"](task.title)
        title_l = visible_title.lower()
        notes_l = (task.notes or "").lower()
        overlap = 0
        if terms:
            for term in terms:
                if term in title_l:
                    overlap += 3
                elif term in notes_l:
                    overlap += 1
        status = task.status.value if hasattr(task.status, "value") else str(task.status)
        status_boost = 2 if status == "open" else 0
        recency_boost = max(0, 10 - idx)
        score = overlap + status_boost + recency_boost
        prepared.append(
            (
                score,
                {
                    "id": task.id,
                    "title": visible_title,
                    "status": status,
                    "priority": task.priority,
                    "impact_score": getattr(task, "impact_score", None),
                    "urgency_score": getattr(task, "urgency_score", None),
                    "notes": task.notes,
                    "due_date": helpers["work_item_due_date_text"](task),
                    "parent_title": parent_titles_by_id.get(task.parent_id),
                },
            )
        )
    prepared.sort(key=lambda item: item[0], reverse=True)
    max_items = 12 if terms else 8
    tasks = [item[1] for item in prepared[:max_items]]
    recent_refs: List[Dict[str, Any]] = []
    now = helpers["utc_now"]()
    recent_stmt = (
        select(RecentContextItem)
        .where(
            RecentContextItem.user_id == user_id,
            RecentContextItem.chat_id == chat_id,
            RecentContextItem.entity_type.in_([EntityType.task, EntityType.work_item]),
            RecentContextItem.expires_at >= now,
        )
        .order_by(RecentContextItem.surfaced_at.desc())
        .limit(24)
    )
    recent_rows = (await db.execute(recent_stmt)).scalars().all()
    recent_task_ids: List[str] = []
    displayed_meta_by_ordinal: Dict[int, Dict[str, Any]] = {}
    latest_display_batch_id: Optional[str] = None
    seen: set[str] = set()
    for row in recent_rows:
        parsed_reason = helpers["_parse_recent_display_reason"](row.reason)
        if parsed_reason:
            view_name, batch_id, ordinal = parsed_reason
            if latest_display_batch_id is None:
                latest_display_batch_id = batch_id
            if (
                batch_id == latest_display_batch_id
                and ordinal not in displayed_meta_by_ordinal
                and isinstance(row.entity_id, str)
                and row.entity_id
            ):
                displayed_meta_by_ordinal[ordinal] = {
                    "id": row.entity_id,
                    "ordinal": ordinal,
                    "view_name": view_name,
                }
        if row.entity_id not in seen:
            seen.add(row.entity_id)
            recent_task_ids.append(row.entity_id)
        if len(recent_task_ids) >= 8:
            break
    displayed_task_ids = [meta["id"] for _, meta in sorted(displayed_meta_by_ordinal.items())]
    combined_task_ids: List[str] = []
    seen_combined: set[str] = set()
    for task_id in recent_task_ids + displayed_task_ids:
        if isinstance(task_id, str) and task_id and task_id not in seen_combined:
            seen_combined.add(task_id)
            combined_task_ids.append(task_id)
    displayed_refs: List[Dict[str, Any]] = []
    if combined_task_ids:
        recent_tasks_stmt = select(WorkItem).where(
            WorkItem.user_id == user_id,
            WorkItem.id.in_(combined_task_ids),
            WorkItem.kind.in_([WorkItemKind.task, WorkItemKind.subtask]),
        )
        recent_tasks = (await db.execute(recent_tasks_stmt)).scalars().all()
        extra_parent_ids = {
            task.parent_id
            for task in recent_tasks
            if isinstance(getattr(task, "parent_id", None), str)
            and task.parent_id.strip()
            and task.parent_id not in parent_titles_by_id
        }
        if extra_parent_ids:
            extra_parent_rows = (
                await db.execute(
                    select(WorkItem).where(
                        WorkItem.user_id == user_id,
                        WorkItem.id.in_(extra_parent_ids),
                    )
                )
            ).scalars().all()
            parent_titles_by_id.update(
                {
                    parent.id: helpers["_canonical_task_title"](parent.title)
                    for parent in extra_parent_rows
                    if isinstance(parent.id, str) and parent.id.strip()
                }
            )
        task_by_id = {task.id: task for task in recent_tasks}
        for task_id in recent_task_ids:
            task = task_by_id.get(task_id)
            if not task:
                continue
            status = task.status.value if hasattr(task.status, "value") else str(task.status)
            recent_refs.append(
                {
                    "id": task.id,
                    "title": helpers["_canonical_task_title"](task.title),
                    "status": status,
                    "parent_title": parent_titles_by_id.get(task.parent_id),
                }
            )
        for ordinal in sorted(displayed_meta_by_ordinal):
            meta = displayed_meta_by_ordinal[ordinal]
            task = task_by_id.get(meta["id"])
            if not task:
                continue
            status = task.status.value if hasattr(task.status, "value") else str(task.status)
            displayed_refs.append(
                {
                    "ordinal": ordinal,
                    "id": task.id,
                    "title": helpers["_canonical_task_title"](task.title),
                    "status": status,
                    "view_name": meta["view_name"],
                    "parent_title": parent_titles_by_id.get(task.parent_id),
                }
            )

    recent_reminder_refs: List[Dict[str, Any]] = []
    recent_reminder_stmt = (
        select(RecentContextItem)
        .where(
            RecentContextItem.user_id == user_id,
            RecentContextItem.chat_id == chat_id,
            RecentContextItem.entity_type == EntityType.reminder,
            RecentContextItem.expires_at >= now,
        )
        .order_by(RecentContextItem.surfaced_at.desc())
        .limit(12)
    )
    recent_reminder_rows = (await db.execute(recent_reminder_stmt)).scalars().all()
    recent_reminder_ids: List[str] = []
    seen_reminder_ids: set[str] = set()
    for row in recent_reminder_rows:
        if isinstance(row.entity_id, str) and row.entity_id and row.entity_id not in seen_reminder_ids:
            seen_reminder_ids.add(row.entity_id)
            recent_reminder_ids.append(row.entity_id)
    reminder_by_id: Dict[str, Reminder] = {}
    reminder_work_item_titles_by_id: Dict[str, str] = {}
    if recent_reminder_ids:
        recent_reminders_stmt = select(Reminder).where(Reminder.user_id == user_id, Reminder.id.in_(recent_reminder_ids))
        recent_reminders = (await db.execute(recent_reminders_stmt)).scalars().all()
        reminder_by_id = {reminder.id: reminder for reminder in recent_reminders}
        linked_work_item_ids = {
            reminder.work_item_id
            for reminder in recent_reminders
            if isinstance(getattr(reminder, "work_item_id", None), str) and reminder.work_item_id.strip()
        }
        if linked_work_item_ids:
            linked_work_items = (
                await db.execute(
                    select(WorkItem).where(
                        WorkItem.user_id == user_id,
                        WorkItem.id.in_(linked_work_item_ids),
                    )
                )
            ).scalars().all()
            reminder_work_item_titles_by_id.update(
                {
                    item.id: helpers["_canonical_task_title"](item.title)
                    for item in linked_work_items
                    if isinstance(item.id, str) and item.id.strip()
                }
            )
        for reminder_id in recent_reminder_ids:
            reminder = reminder_by_id.get(reminder_id)
            if not reminder:
                continue
            recent_reminder_refs.append(
                {
                    "id": reminder.id,
                    "title": helpers["_canonical_task_title"](reminder.title),
                    "status": str(getattr(reminder.status, "value", reminder.status) or "").strip().lower(),
                    "message": reminder.message,
                    "kind": getattr(reminder.kind, "value", reminder.kind),
                    "remind_at": reminder.remind_at.isoformat()
                    if isinstance(reminder.remind_at, datetime)
                    else None,
                    "work_item_title": reminder_work_item_titles_by_id.get(reminder.work_item_id),
                }
            )

    reminder_rows = (
        await db.execute(
            select(Reminder)
            .where(
                Reminder.user_id == user_id,
                Reminder.status.in_([ReminderStatus.pending, ReminderStatus.sent]),
            )
            .order_by(Reminder.updated_at.desc())
            .limit(40)
        )
    ).scalars().all()
    linked_work_item_ids = {
        reminder.work_item_id
        for reminder in reminder_rows
        if isinstance(getattr(reminder, "work_item_id", None), str) and reminder.work_item_id.strip()
    }
    if linked_work_item_ids:
        linked_work_items = (
            await db.execute(
                select(WorkItem).where(
                    WorkItem.user_id == user_id,
                    WorkItem.id.in_(linked_work_item_ids),
                )
            )
        ).scalars().all()
        reminder_work_item_titles_by_id.update(
            {
                item.id: helpers["_canonical_task_title"](item.title)
                for item in linked_work_items
                if isinstance(item.id, str) and item.id.strip()
            }
        )
    prepared_reminders = []
    for idx, reminder in enumerate(reminder_rows):
        title_l = str(reminder.title or "").lower()
        message_l = str(reminder.message or "").lower()
        overlap = 0
        if terms:
            for term in terms:
                if term in title_l:
                    overlap += 3
                elif term in message_l:
                    overlap += 1
        status_value = getattr(reminder.status, "value", reminder.status)
        status_text = str(status_value or "").strip().lower()
        status_boost = 3 if status_text == "pending" else 1 if status_text == "sent" else 0
        recency_boost = max(0, 8 - idx)
        score = overlap + status_boost + recency_boost
        prepared_reminders.append(
            (
                score,
                {
                    "id": reminder.id,
                    "title": helpers["_canonical_task_title"](reminder.title),
                    "status": status_text or "pending",
                    "kind": getattr(reminder.kind, "value", reminder.kind),
                    "message": reminder.message,
                    "remind_at": reminder.remind_at.isoformat()
                    if isinstance(reminder.remind_at, datetime)
                    else None,
                    "recurrence_rule": reminder.recurrence_rule,
                    "work_item_id": reminder.work_item_id,
                    "work_item_title": reminder_work_item_titles_by_id.get(reminder.work_item_id),
                    "person_id": reminder.person_id,
                },
            )
        )
    prepared_reminders.sort(key=lambda item: item[0], reverse=True)
    max_reminders = 12 if terms else 8
    reminders = [item[1] for item in prepared_reminders[:max_reminders]]

    return {
        "chat_id": chat_id,
        "current_date_utc": helpers["utc_now"]().date().isoformat(),
        "current_datetime_utc": helpers["utc_now"]().isoformat(),
        "current_date_local": helpers["_local_today"]().isoformat(),
        "current_datetime_local": helpers["_local_now"]().isoformat(),
        "timezone": helpers["settings"].APP_TIMEZONE,
        "tasks": tasks,
        "recent_task_refs": recent_refs,
        "displayed_task_refs": displayed_refs,
        "recent_reminder_refs": recent_reminder_refs,
        "reminders": reminders,
    }


async def run_enqueue_summary_job(user_id: str, chat_id: str, inbox_item_id: str, *, helpers: Dict[str, Any]) -> None:
    job_payload = {
        "job_id": str(uuid.uuid4()),
        "topic": "memory.summarize",
        "payload": {"user_id": user_id, "chat_id": chat_id, "inbox_item_id": inbox_item_id},
    }
    await helpers["redis_client"].rpush("default_queue", json.dumps(job_payload))


async def run_remember_recent_tasks(
    db,
    user_id: str,
    chat_id: str,
    task_ids: List[str],
    reason: str,
    *,
    helpers: Dict[str, Any],
    ttl_hours: int = 24,
) -> None:
    await helpers["remember_recent_tasks"](
        db,
        user_id=user_id,
        chat_id=chat_id,
        task_ids=task_ids,
        reason=reason,
        ttl_hours=ttl_hours,
    )


async def run_remember_recent_reminders(
    db,
    user_id: str,
    chat_id: str,
    reminder_ids: List[str],
    reason: str,
    *,
    helpers: Dict[str, Any],
    ttl_hours: int = 24,
) -> None:
    await helpers["remember_recent_reminders"](
        db,
        user_id=user_id,
        chat_id=chat_id,
        reminder_ids=reminder_ids,
        reason=reason,
        ttl_hours=ttl_hours,
    )


def run_recent_display_reason(view_name: str, batch_id: str, ordinal: int) -> str:
    return f"task_display:{view_name}:{batch_id}:{ordinal}"


def run_parse_recent_display_reason(reason: Any) -> tuple[str, str, int] | None:
    if not isinstance(reason, str):
        return None
    parts = reason.split(":")
    if len(parts) != 4 or parts[0] != "task_display":
        return None
    try:
        ordinal = int(parts[3])
    except ValueError:
        return None
    return parts[1], parts[2], ordinal


async def run_remember_displayed_tasks(
    db,
    user_id: str,
    chat_id: str,
    task_ids: List[str],
    view_name: str,
    *,
    helpers: Dict[str, Any],
    ttl_hours: int = 12,
) -> None:
    now = helpers["utc_now"]()
    expires_at = now + timedelta(hours=max(1, ttl_hours))
    batch_id = uuid.uuid4().hex[:8]
    unique_ids: List[str] = []
    seen: set[str] = set()
    for task_id in task_ids:
        if isinstance(task_id, str) and task_id and task_id not in seen:
            seen.add(task_id)
            unique_ids.append(task_id)
    for ordinal, task_id in enumerate(unique_ids[:12], start=1):
        db.add(
            RecentContextItem(
                id=f"rcx_{uuid.uuid4().hex[:12]}",
                user_id=user_id,
                chat_id=chat_id,
                entity_type=EntityType.work_item,
                entity_id=task_id,
                reason=helpers["_recent_display_reason"](view_name, batch_id, ordinal),
                surfaced_at=now + timedelta(microseconds=ordinal),
                expires_at=expires_at,
            )
        )


def run_task_ids_from_query_response(response) -> List[str]:
    raw_ids = response.surfaced_entity_ids if hasattr(response, "surfaced_entity_ids") else None
    if not isinstance(raw_ids, list):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for value in raw_ids:
        if not isinstance(value, str):
            continue
        task_id = value.strip()
        if not task_id.startswith("tsk_") or task_id in seen:
            continue
        seen.add(task_id)
        out.append(task_id)
    return out


def run_reminder_ids_from_query_response(response) -> List[str]:
    raw_ids = response.surfaced_entity_ids if hasattr(response, "surfaced_entity_ids") else None
    if not isinstance(raw_ids, list):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for value in raw_ids:
        if not isinstance(value, str):
            continue
        reminder_id = value.strip()
        if not reminder_id.startswith("rem_") or reminder_id in seen:
            continue
        seen.add(reminder_id)
        out.append(reminder_id)
    return out


def run_infer_task_ids_from_answer_text(answer: str, grounding: Dict[str, Any], *, helpers: Dict[str, Any], limit: int = 6) -> List[str]:
    answer_text = helpers["_normalize_query_text"](answer)
    if not answer_text:
        return []
    candidates = helpers["_completion_candidate_rows"](grounding)
    out: List[str] = []
    seen: set[str] = set()
    for row in candidates:
        task_id = row.get("id")
        if not isinstance(task_id, str) or not task_id.strip() or task_id in seen:
            continue
        canonical_title = helpers["_canonical_task_title"](row.get("title"))
        title_text = helpers["_normalize_query_text"](canonical_title)
        if not title_text:
            continue
        title_terms = set(title_text.split())
        overlap = title_terms.intersection(set(answer_text.split()))
        title_in_answer = title_text in answer_text
        if not title_in_answer and len(overlap) < min(2, len(title_terms)):
            continue
        seen.add(task_id)
        out.append(task_id)
        if len(out) >= max(1, limit):
            break
    return out


def run_infer_reminder_ids_from_answer_text(
    answer: str,
    grounding: Dict[str, Any],
    *,
    helpers: Dict[str, Any],
    limit: int = 6,
) -> List[str]:
    answer_text = helpers["_normalize_query_text"](answer)
    if not answer_text:
        return []
    candidates = helpers["_reminder_reference_candidates"](grounding)
    answer_terms = set(answer_text.split())
    out: List[str] = []
    seen: set[str] = set()
    for row in candidates:
        reminder_id = row.get("id")
        if not isinstance(reminder_id, str) or not reminder_id.strip() or reminder_id in seen:
            continue
        title_text = helpers["_normalize_query_text"](row.get("title"))
        if not title_text:
            continue
        title_terms = set(title_text.split())
        overlap = title_terms.intersection(answer_terms)
        title_in_answer = title_text in answer_text
        if not title_in_answer and len(overlap) < min(2, len(title_terms)):
            continue
        seen.add(reminder_id)
        out.append(reminder_id)
        if len(out) >= max(1, limit):
            break
    return out


async def run_remember_query_surface_context(
    db,
    *,
    user_id: str,
    chat_id: str,
    response,
    grounding: Dict[str, Any],
    helpers: Dict[str, Any],
) -> None:
    surfaced_task_ids = helpers["_task_ids_from_query_response"](response)
    inferred_task_ids = helpers["_infer_task_ids_from_answer_text"](response.answer, grounding)
    fallback_task_ids = [
        row.get("id")
        for row in (grounding.get("tasks") if isinstance(grounding, dict) else [])
        if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("id")
    ]
    task_ids = surfaced_task_ids[:6] if surfaced_task_ids else inferred_task_ids[:6] or fallback_task_ids[:6]

    surfaced_reminder_ids = helpers["_reminder_ids_from_query_response"](response)
    inferred_reminder_ids = helpers["_infer_reminder_ids_from_answer_text"](response.answer, grounding)
    reminder_ids = surfaced_reminder_ids[:6] if surfaced_reminder_ids else inferred_reminder_ids[:6]

    updated_context = False
    if task_ids:
        await helpers["_remember_recent_tasks"](
            db=db,
            user_id=user_id,
            chat_id=chat_id,
            task_ids=task_ids,
            reason="query_surface"
            if surfaced_task_ids
            else "query_answer_inferred"
            if inferred_task_ids
            else "query_context",
            ttl_hours=12,
        )
        updated_context = True
    if reminder_ids:
        await helpers["_remember_recent_reminders"](
            db=db,
            user_id=user_id,
            chat_id=chat_id,
            reminder_ids=reminder_ids,
            reason="query_surface" if surfaced_reminder_ids else "query_answer_inferred",
            ttl_hours=12,
        )
        updated_context = True
    if updated_context:
        await db.commit()


async def run_resolve_displayed_task_id(
    db,
    user_id: str,
    chat_id: str,
    ordinal: int,
    *,
    helpers: Dict[str, Any],
) -> Optional[str]:
    if ordinal < 1:
        return None
    now = helpers["utc_now"]()
    rows = (
        await db.execute(
            select(RecentContextItem)
            .where(
                RecentContextItem.user_id == user_id,
                RecentContextItem.chat_id == chat_id,
                RecentContextItem.entity_type.in_([EntityType.task, EntityType.work_item]),
                RecentContextItem.expires_at >= now,
                RecentContextItem.reason.like("task_display:%"),
            )
            .order_by(RecentContextItem.surfaced_at.desc())
            .limit(24)
        )
    ).scalars().all()
    latest_batch_id: Optional[str] = None
    matches: Dict[int, str] = {}
    for row in rows:
        parsed = helpers["_parse_recent_display_reason"](row.reason)
        if not parsed:
            continue
        _, batch_id, row_ordinal = parsed
        if latest_batch_id is None:
            latest_batch_id = batch_id
        if batch_id != latest_batch_id:
            continue
        if row_ordinal not in matches and isinstance(row.entity_id, str) and row.entity_id:
            matches[row_ordinal] = row.entity_id
    return matches.get(ordinal)
