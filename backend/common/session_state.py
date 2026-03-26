import copy
import inspect
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from common.models import Session

_UNSET = object()


def _aware(dt: Optional[datetime], *, now: datetime) -> datetime:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return now


def session_state_payload(session: Optional[Session]) -> Dict[str, Any]:
    if session is None:
        return {
            "session_id": None,
            "current_mode": None,
            "active_entity_refs": [],
            "pending_draft_id": None,
            "pending_clarification": None,
            "summary_metadata": {},
        }
    active_refs = session.active_entity_refs_json if isinstance(session.active_entity_refs_json, list) else []
    pending_clarification = (
        copy.deepcopy(session.pending_clarification_json)
        if isinstance(session.pending_clarification_json, dict) and session.pending_clarification_json
        else None
    )
    summary_metadata = (
        copy.deepcopy(session.summary_metadata_json)
        if isinstance(session.summary_metadata_json, dict)
        else {}
    )
    return {
        "session_id": session.id,
        "current_mode": session.current_mode,
        "active_entity_refs": copy.deepcopy(active_refs),
        "pending_draft_id": session.pending_draft_id,
        "pending_clarification": pending_clarification,
        "summary_metadata": summary_metadata,
    }


def active_entity_refs_from_grounding(grounding: Dict[str, Any], *, limit: int = 12) -> List[Dict[str, Any]]:
    if not isinstance(grounding, dict):
        return []
    refs: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_task_rows(rows: Any, source: str) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            entity_id = row.get("id")
            title = row.get("title")
            if not isinstance(entity_id, str) or not entity_id.strip():
                continue
            if not isinstance(title, str) or not title.strip():
                continue
            key = ("work_item", entity_id.strip())
            if key in seen:
                continue
            seen.add(key)
            item = {
                "entity_type": "work_item",
                "entity_id": entity_id.strip(),
                "title": title.strip(),
                "status": str(row.get("status") or "").strip().lower() or None,
                "source": source,
            }
            parent_title = row.get("parent_title")
            if isinstance(parent_title, str) and parent_title.strip():
                item["parent_title"] = parent_title.strip()
            if isinstance(row.get("ordinal"), int):
                item["ordinal"] = row["ordinal"]
            if isinstance(row.get("view_name"), str) and row.get("view_name").strip():
                item["view_name"] = row["view_name"].strip()
            refs.append(item)
            if len(refs) >= limit:
                return

    def add_reminder_rows(rows: Any, source: str) -> None:
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            entity_id = row.get("id")
            title = row.get("title")
            if not isinstance(entity_id, str) or not entity_id.strip():
                continue
            if not isinstance(title, str) or not title.strip():
                continue
            key = ("reminder", entity_id.strip())
            if key in seen:
                continue
            seen.add(key)
            item = {
                "entity_type": "reminder",
                "entity_id": entity_id.strip(),
                "title": title.strip(),
                "status": str(row.get("status") or "").strip().lower() or None,
                "source": source,
            }
            work_item_title = row.get("work_item_title")
            if isinstance(work_item_title, str) and work_item_title.strip():
                item["work_item_title"] = work_item_title.strip()
            refs.append(item)
            if len(refs) >= limit:
                return

    add_task_rows(grounding.get("displayed_task_refs"), "displayed")
    if len(refs) < limit:
        add_task_rows(grounding.get("recent_task_refs"), "recent")
    if len(refs) < limit:
        add_task_rows(grounding.get("tasks"), "grounding")
    if len(refs) < limit:
        add_reminder_rows(grounding.get("recent_reminder_refs"), "recent")
    if len(refs) < limit:
        add_reminder_rows(grounding.get("reminders"), "grounding")
    return refs[:limit]


async def get_latest_session(db, *, user_id: str, chat_id: str) -> Optional[Session]:
    stmt = (
        select(Session)
        .where(Session.user_id == user_id, Session.chat_id == chat_id)
        .order_by(Session.last_activity_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    scalar = result.scalar_one_or_none()
    if inspect.isawaitable(scalar):
        scalar = await scalar
    return scalar if isinstance(scalar, Session) else None


async def get_or_create_active_session(
    db,
    *,
    user_id: str,
    chat_id: str,
    now: datetime,
    inactivity_minutes: int,
) -> Session:
    session = await get_latest_session(db, user_id=user_id, chat_id=chat_id)
    cutoff = now - timedelta(minutes=max(1, inactivity_minutes))
    if session is not None:
        last_activity = _aware(session.last_activity_at, now=now)
        if session.ended_at is None and last_activity >= cutoff:
            session.last_activity_at = now
            await db.commit()
            return session
        if session.ended_at is None:
            session.ended_at = now
            session.last_activity_at = now
    new_session = Session(
        id=f"ses_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        chat_id=chat_id,
        started_at=now,
        last_activity_at=now,
        ended_at=None,
        current_mode=None,
        active_entity_refs_json=[],
        pending_draft_id=None,
        pending_clarification_json={},
        summary_metadata_json={},
    )
    db.add(new_session)
    await db.commit()
    return new_session


async def update_session_state(
    db,
    session: Optional[Session],
    *,
    now: datetime,
    current_mode: Any = _UNSET,
    active_entity_refs: Any = _UNSET,
    pending_draft_id: Any = _UNSET,
    pending_clarification: Any = _UNSET,
    summary_metadata: Optional[Dict[str, Any]] = None,
    touch: bool = True,
) -> Optional[Session]:
    if session is None:
        return None
    if touch:
        session.last_activity_at = now
    if current_mode is not _UNSET:
        session.current_mode = str(current_mode).strip() if isinstance(current_mode, str) and str(current_mode).strip() else None
    if active_entity_refs is not _UNSET:
        session.active_entity_refs_json = copy.deepcopy(active_entity_refs) if isinstance(active_entity_refs, list) else []
    if pending_draft_id is not _UNSET:
        session.pending_draft_id = (
            pending_draft_id.strip() if isinstance(pending_draft_id, str) and pending_draft_id.strip() else None
        )
    if pending_clarification is not _UNSET:
        session.pending_clarification_json = (
            copy.deepcopy(pending_clarification)
            if isinstance(pending_clarification, dict) and pending_clarification
            else {}
        )
    if isinstance(summary_metadata, dict) and summary_metadata:
        merged = copy.deepcopy(session.summary_metadata_json) if isinstance(session.summary_metadata_json, dict) else {}
        merged.update(summary_metadata)
        session.summary_metadata_json = merged
    await db.commit()
    return session
