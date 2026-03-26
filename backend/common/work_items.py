import copy
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional


def due_at_to_due_date(value: Optional[datetime]) -> Optional[date]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).date()


def work_item_attributes(item: Any) -> Dict[str, Any]:
    raw = getattr(item, "attributes_json", None)
    return copy.deepcopy(raw) if isinstance(raw, dict) else {}


def work_item_snapshot(item: Any) -> Dict[str, Any]:
    if item is None:
        return {}
    return {
        "id": getattr(item, "id", None),
        "kind": str(getattr(getattr(item, "kind", None), "value", getattr(item, "kind", None)) or ""),
        "parent_id": getattr(item, "parent_id", None),
        "area_id": getattr(item, "area_id", None),
        "title": getattr(item, "title", None),
        "title_norm": getattr(item, "title_norm", None),
        "notes": getattr(item, "notes", None),
        "attributes_json": work_item_attributes(item),
        "status": str(getattr(getattr(item, "status", None), "value", getattr(item, "status", None)) or ""),
        "priority": getattr(item, "priority", None),
        "due_at": getattr(item, "due_at", None).isoformat() if isinstance(getattr(item, "due_at", None), datetime) else None,
        "scheduled_for": getattr(item, "scheduled_for", None).isoformat()
        if isinstance(getattr(item, "scheduled_for", None), datetime)
        else None,
        "snooze_until": getattr(item, "snooze_until", None).isoformat()
        if isinstance(getattr(item, "snooze_until", None), datetime)
        else None,
        "estimated_minutes": getattr(item, "estimated_minutes", None),
        "source_inbox_item_id": getattr(item, "source_inbox_item_id", None),
        "completed_at": getattr(item, "completed_at", None).isoformat()
        if isinstance(getattr(item, "completed_at", None), datetime)
        else None,
        "archived_at": getattr(item, "archived_at", None).isoformat()
        if isinstance(getattr(item, "archived_at", None), datetime)
        else None,
    }


def work_item_due_date_text(item: Any) -> Optional[str]:
    due_at = getattr(item, "due_at", None)
    if isinstance(due_at, datetime):
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        return due_at.date().isoformat()
    due_date = getattr(item, "due_date", None)
    if isinstance(due_date, date):
        return due_date.isoformat()
    return None
