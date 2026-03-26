import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from common.models import EntityType, RecentContextItem


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def remember_recent_entities(
    db: AsyncSession,
    *,
    user_id: str,
    chat_id: str,
    entity_type: EntityType,
    entity_ids: Iterable[str],
    reason: str,
    ttl_hours: int = 24,
) -> None:
    now = _utc_now()
    expires_at = now + timedelta(hours=max(1, ttl_hours))
    seen: set[str] = set()
    unique_ids: list[str] = []
    for entity_id in entity_ids:
        if isinstance(entity_id, str) and entity_id and entity_id not in seen:
            seen.add(entity_id)
            unique_ids.append(entity_id)
    for entity_id in unique_ids[:12]:
        db.add(
            RecentContextItem(
                id=f"rcx_{uuid.uuid4().hex[:12]}",
                user_id=user_id,
                chat_id=chat_id,
                entity_type=entity_type,
                entity_id=entity_id,
                reason=reason,
                surfaced_at=now,
                expires_at=expires_at,
            )
        )


async def remember_recent_tasks(
    db: AsyncSession,
    *,
    user_id: str,
    chat_id: str,
    task_ids: Iterable[str],
    reason: str,
    ttl_hours: int = 24,
) -> None:
    await remember_recent_entities(
        db,
        user_id=user_id,
        chat_id=chat_id,
        entity_type=EntityType.work_item,
        entity_ids=task_ids,
        reason=reason,
        ttl_hours=ttl_hours,
    )


async def remember_recent_reminders(
    db: AsyncSession,
    *,
    user_id: str,
    chat_id: str,
    reminder_ids: Iterable[str],
    reason: str,
    ttl_hours: int = 24,
) -> None:
    await remember_recent_entities(
        db,
        user_id=user_id,
        chat_id=chat_id,
        entity_type=EntityType.reminder,
        entity_ids=reminder_ids,
        reason=reason,
        ttl_hours=ttl_hours,
    )
