import copy
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional


def run_parse_due_date(value: Any) -> Optional[date]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def run_parse_due_at(value: Any, *, helpers: Dict[str, Any]) -> Optional[datetime]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        if "t" in raw.lower():
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    due = run_parse_due_date(raw)
    if due is None:
        return None
    return datetime(due.year, due.month, due.day, 12, 0, tzinfo=timezone.utc)


def run_coerce_work_item_status(value: Any, *, helpers: Dict[str, Any]):
    raw = str(getattr(value, "value", value) or "").strip().lower()
    if raw == "blocked":
        return helpers["WorkItemStatus"].blocked
    if raw == "done":
        return helpers["WorkItemStatus"].done
    if raw == "archived":
        return helpers["WorkItemStatus"].archived
    return helpers["WorkItemStatus"].open


def run_new_work_item_id(kind, *, helpers: Dict[str, Any]) -> str:
    if kind in {helpers["WorkItemKind"].task, helpers["WorkItemKind"].subtask}:
        return f"tsk_{uuid.uuid4().hex[:12]}"
    return f"wki_{uuid.uuid4().hex[:12]}"


def run_work_item_view_payload(item, *, helpers: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "kind": getattr(item.kind, "value", item.kind),
        "parent_id": item.parent_id,
        "area_id": item.area_id,
        "title": item.title,
        "title_norm": item.title_norm,
        "notes": item.notes,
        "attributes_json": helpers["work_item_attributes"](item),
        "status": getattr(item.status, "value", item.status),
        "priority": item.priority,
        "due_at": item.due_at,
        "scheduled_for": item.scheduled_for,
        "snooze_until": item.snooze_until,
        "estimated_minutes": item.estimated_minutes,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "completed_at": item.completed_at,
        "archived_at": item.archived_at,
    }


def run_work_item_link_type_from_legacy(link_type, *, helpers: Dict[str, Any]):
    if link_type == helpers["LinkType"].blocks:
        return helpers["WorkItemLinkType"].blocks
    if link_type == helpers["LinkType"].depends_on:
        return helpers["WorkItemLinkType"].depends_on
    if link_type == helpers["LinkType"].related:
        return helpers["WorkItemLinkType"].related_to
    if link_type in {helpers["LinkType"].supports_goal, helpers["LinkType"].addresses_problem}:
        return helpers["WorkItemLinkType"].part_of
    return None


def run_coerce_reminder_status(value: Any, *, helpers: Dict[str, Any]):
    raw = str(getattr(value, "value", value) or "").strip().lower()
    if raw == "sent":
        return helpers["ReminderStatus"].sent
    if raw == "completed":
        return helpers["ReminderStatus"].completed
    if raw == "dismissed":
        return helpers["ReminderStatus"].dismissed
    if raw == "canceled":
        return helpers["ReminderStatus"].canceled
    return helpers["ReminderStatus"].pending


def run_coerce_reminder_kind(value: Any, *, helpers: Dict[str, Any]):
    raw = str(getattr(value, "value", value) or "").strip().lower()
    if raw == "follow_up":
        return helpers["ReminderKind"].follow_up
    if raw == "recurring":
        return helpers["ReminderKind"].recurring
    return helpers["ReminderKind"].one_off


def run_reminder_view_payload(reminder) -> Dict[str, Any]:
    return {
        "id": reminder.id,
        "user_id": reminder.user_id,
        "work_item_id": reminder.work_item_id,
        "work_item_title": getattr(reminder, "work_item_title", None),
        "person_id": reminder.person_id,
        "kind": getattr(reminder.kind, "value", reminder.kind),
        "status": getattr(reminder.status, "value", reminder.status),
        "title": reminder.title,
        "message": reminder.message,
        "remind_at": reminder.remind_at,
        "recurrence_rule": reminder.recurrence_rule,
        "last_sent_at": reminder.last_sent_at,
        "completed_at": reminder.completed_at,
        "dismissed_at": reminder.dismissed_at,
        "created_at": reminder.created_at,
        "updated_at": reminder.updated_at,
    }


def run_validated_recurrence_rule(value: Optional[str], *, helpers: Dict[str, Any]) -> Optional[str]:
    normalized = helpers["normalize_recurrence_rule"](value)
    if value is None or normalized is not None:
        return normalized
    supported = ", ".join(helpers["supported_recurrence_rules"]())
    raise helpers["HTTPException"](status_code=400, detail=f"Unsupported recurrence_rule. Use one of: {supported}")


async def run_get_work_item_by_id(db, user_id: str, item_id: str, *, helpers: Dict[str, Any], kinds=None):
    query = helpers["select"](helpers["WorkItem"]).where(
        helpers["WorkItem"].id == item_id,
        helpers["WorkItem"].user_id == user_id,
    )
    if kinds:
        query = query.where(helpers["WorkItem"].kind.in_(kinds))
    return (await db.execute(query)).scalar_one_or_none()


def run_apply_work_item_updates(item, update_data: Dict[str, Any], *, helpers: Dict[str, Any]) -> None:
    if "kind" in update_data and update_data["kind"] is not None:
        item.kind = update_data["kind"]
    if "parent_id" in update_data:
        item.parent_id = update_data["parent_id"]
    if "area_id" in update_data:
        item.area_id = update_data["area_id"]
    if "title" in update_data and isinstance(update_data["title"], str):
        canonical_title = helpers["_canonical_task_title"](update_data["title"])
        item.title = canonical_title
        item.title_norm = canonical_title.lower().strip()
    if "notes" in update_data:
        item.notes = update_data["notes"]
    if "attributes_json" in update_data and isinstance(update_data["attributes_json"], dict):
        item.attributes_json = copy.deepcopy(update_data["attributes_json"])
    if "priority" in update_data:
        item.priority = update_data["priority"]
    if "due_at" in update_data:
        item.due_at = helpers["_parse_due_at"](update_data["due_at"])
    if "scheduled_for" in update_data:
        item.scheduled_for = helpers["_parse_due_at"](update_data["scheduled_for"])
    if "snooze_until" in update_data:
        item.snooze_until = helpers["_parse_due_at"](update_data["snooze_until"])
    if "estimated_minutes" in update_data:
        item.estimated_minutes = update_data["estimated_minutes"]
    if "status" in update_data and update_data["status"] is not None:
        item.status = helpers["_coerce_work_item_status"](update_data["status"])
        item.completed_at = helpers["utc_now"]() if item.status == helpers["WorkItemStatus"].done else None
        item.archived_at = helpers["utc_now"]() if item.status == helpers["WorkItemStatus"].archived else None
    elif item.status != helpers["WorkItemStatus"].archived:
        item.archived_at = None
    item.updated_at = helpers["utc_now"]()
