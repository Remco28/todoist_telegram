import copy
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from common.models import WorkItem, WorkItemKind, WorkItemStatus


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


async def run_send_urgent_task_view(db, user_id: str, chat_id: str, *, helpers: Dict[str, Any]) -> None:
    urgent_tasks = (
        await db.execute(
            select(WorkItem)
            .where(
                WorkItem.user_id == user_id,
                WorkItem.kind.in_([WorkItemKind.task, WorkItemKind.subtask]),
                WorkItem.status.in_([WorkItemStatus.open, WorkItemStatus.blocked]),
                WorkItem.priority == 1,
            )
            .order_by(WorkItem.due_at.asc().nulls_last(), WorkItem.updated_at.desc())
            .limit(12)
        )
    ).scalars().all()
    payload = [
        {
            "id": task.id,
            "title": helpers["_canonical_task_title"](task.title),
            "due_date": helpers["work_item_due_date_text"](task),
        }
        for task in urgent_tasks
    ]
    sent = await helpers["send_message"](chat_id, helpers["format_urgent_tasks"](payload))
    if not (isinstance(sent, dict) and sent.get("ok") is True):
        return
    task_ids = [task["id"] for task in payload if isinstance(task.get("id"), str) and task.get("id")]
    if task_ids:
        await helpers["_remember_displayed_tasks"](db, user_id, chat_id, task_ids, "urgent")
        await db.commit()


async def run_send_open_task_view(db, user_id: str, chat_id: str, *, helpers: Dict[str, Any]) -> None:
    open_tasks = (
        await db.execute(
            select(WorkItem)
            .where(
                WorkItem.user_id == user_id,
                WorkItem.kind.in_([WorkItemKind.task, WorkItemKind.subtask]),
                WorkItem.status.in_([WorkItemStatus.open, WorkItemStatus.blocked]),
            )
            .order_by(WorkItem.priority.asc(), WorkItem.due_at.asc().nulls_last(), WorkItem.updated_at.desc())
            .limit(20)
        )
    ).scalars().all()
    payload = [
        {
            "id": task.id,
            "title": helpers["_canonical_task_title"](task.title),
            "status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "due_date": helpers["work_item_due_date_text"](task),
        }
        for task in open_tasks
    ]
    sent = await helpers["send_message"](chat_id, helpers["format_open_tasks"](payload))
    if not (isinstance(sent, dict) and sent.get("ok") is True):
        return
    task_ids = [task["id"] for task in payload if isinstance(task.get("id"), str) and task.get("id")]
    if task_ids:
        await helpers["_remember_displayed_tasks"](db, user_id, chat_id, task_ids, "open")
        await db.commit()


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
    await helpers["send_message"](chat_id, clarification_text)
