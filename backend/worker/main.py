import asyncio
import logging
import json
import uuid
import time
from datetime import datetime, timedelta, date, timezone

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete

from common.config import settings
from common.models import (
    Base, MemorySummary, EventLog, InboxItem, PromptRun,
    ActionDraft, Reminder, ReminderStatus, TelegramUserMap, WorkItem,
    ConversationEvent, ConversationSource, ConversationDirection,
)
from common.adapter import adapter
from common.recent_context import remember_recent_reminders
from common.reminders import next_recurrence_time, normalize_recurrence_rule
from common.telegram import send_message, escape_html

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

# DB Setup
engine = create_async_engine(settings.DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Redis Setup
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

DEFAULT_QUEUE = "default_queue"
DLQ = "dead_letter_queue"
MAX_ATTEMPTS = 5

from common.planner import collect_planning_state, build_plan_payload, render_fallback_plan_explanation

async def _emit_worker_event(
    event_type: str,
    topic: str,
    job_id: str,
    attempt: int,
    queue: str,
    user_id: str = "system",
    max_attempts: int = MAX_ATTEMPTS,
    extra: dict | None = None,
):
    payload = {
        "topic": topic,
        "job_id": job_id,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "queue": queue,
    }
    if extra:
        payload.update(extra)
    try:
        async with AsyncSessionLocal() as db:
            db.add(EventLog(
                id=str(uuid.uuid4()),
                request_id=f"job_{job_id}",
                user_id=user_id,
                event_type=event_type,
                payload_json=payload,
            ))
            await db.commit()
    except Exception as log_error:
        logger.error(f"Failed to emit worker event {event_type} for {job_id}: {log_error}")

async def process_job(job_data: dict):
    topic = job_data.get("topic")
    payload = job_data.get("payload", {})
    job_id = job_data.get("job_id")
    attempt = job_data.get("attempt", 1)
    user_id = payload.get("user_id", "system")
    
    logger.info(f"Processing job: {topic} (id: {job_id}, attempt: {attempt})")
    
    try:
        if topic == "memory.summarize":
            await handle_memory_summarize(job_id, payload)
        elif topic == "memory.compact":
            await handle_memory_compact(job_id, payload)
        elif topic == "plan.refresh":
            await handle_plan_refresh(job_id, payload)
        elif topic == "reminders.dispatch":
            await handle_reminder_dispatch(job_id, payload)
        else:
            logger.warning(f"Unknown topic: {topic}")
            return
        await _emit_worker_event(
            event_type="worker_topic_completed",
            topic=topic,
            job_id=job_id,
            attempt=attempt,
            max_attempts=MAX_ATTEMPTS,
            queue=DEFAULT_QUEUE,
            user_id=user_id,
        )
            
    except Exception as e:
        logger.error(f"Job failed (attempt {attempt}): {e}")
        if attempt < MAX_ATTEMPTS:
            job_data["attempt"] = attempt + 1
            wait_time = min(2 ** attempt, 60)
            logger.info(f"Retrying in {wait_time}s...")
            await _emit_worker_event(
                event_type="worker_retry_scheduled",
                topic=topic,
                job_id=job_id,
                attempt=attempt,
                max_attempts=MAX_ATTEMPTS,
                queue=DEFAULT_QUEUE,
                user_id=user_id,
                extra={"delay_seconds": wait_time, "error": str(e)},
            )
            await asyncio.sleep(wait_time)
            await redis_client.rpush(DEFAULT_QUEUE, json.dumps(job_data))
        else:
            logger.error(f"Job exceeded max attempts, moving to DLQ: {job_id}")
            await _emit_worker_event(
                event_type="worker_moved_to_dlq",
                topic=topic,
                job_id=job_id,
                attempt=attempt,
                max_attempts=MAX_ATTEMPTS,
                queue=DLQ,
                user_id=user_id,
                extra={"error": str(e)},
            )
            await redis_client.rpush(DLQ, json.dumps(job_data))

async def handle_plan_refresh(job_id: str, payload: dict):
    user_id = payload.get("user_id")
    chat_id = payload.get("chat_id")
    logger.info(f"Refreshing plan for user {user_id}...")
    
    async with AsyncSessionLocal() as db:
        # 1. Collect state
        state = await collect_planning_state(db, user_id)
        
        # 2. Build deterministic payload
        now = utc_now()
        plan_payload = build_plan_payload(state, now)
        
        # 3. Call adapter rewrite
        start_time = time.time()
        try:
            plan_payload = await adapter.rewrite_plan(plan_payload)
            latency = int((time.time() - start_time) * 1000)
            
            db.add(PromptRun(
                id=str(uuid.uuid4()), request_id=f"job_{job_id}", user_id=user_id,
                operation="plan", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_PLAN,
                prompt_version=settings.PROMPT_VERSION_PLAN, latency_ms=latency, status="success",
                created_at=utc_now()
            ))
        except Exception as e:
            logger.error(f"Plan rewrite failed in worker: {e}")
            plan_payload = render_fallback_plan_explanation(plan_payload)
            
            # Requirement 4: Observability for failure
            db.add(PromptRun(
                id=str(uuid.uuid4()), request_id=f"job_{job_id}", user_id=user_id,
                operation="plan", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_PLAN,
                prompt_version=settings.PROMPT_VERSION_PLAN, status="error", error_code=type(e).__name__,
                created_at=utc_now()
            ))
            db.add(EventLog(
                id=str(uuid.uuid4()), request_id=f"job_{job_id}", user_id=user_id,
                event_type="plan_rewrite_fallback", payload_json={"error": str(e)}
            ))
            
        # 4. Cache in Redis (Requirement 4: Strict Validation)
        try:
            from api.schemas import PlanResponseV1
            validated_payload = PlanResponseV1(**plan_payload)
            cache_key = f"plan:today:{user_id}:{chat_id}"
            await redis_client.setex(cache_key, 86400, validated_payload.model_dump_json())
        except Exception as e:
            logger.error(f"Generated plan failed validation: {e}")
            db.add(EventLog(
                id=str(uuid.uuid4()), request_id=f"job_{job_id}", user_id=user_id,
                event_type="plan_rewrite_fallback", payload_json={"error": str(e), "context": "worker_refresh"}
            ))
            # Fallback: cache a minimal valid deterministic version if rewrite was the cause
            try:
                # Re-build deterministic to be safe
                state_fb = await collect_planning_state(db, user_id)
                payload_fb = build_plan_payload(state_fb, utc_now())
                validated_fb = PlanResponseV1(**payload_fb)
                await redis_client.setex(f"plan:today:{user_id}:{chat_id}", 86400, validated_fb.model_dump_json())
            except Exception as e2:
                logger.error(f"Worker fallback validation failed: {e2}")
        
        # 5. Log event
        db.add(EventLog(
            id=str(uuid.uuid4()), request_id=f"job_{job_id}", user_id=user_id,
            event_type="plan_refresh_completed", payload_json={"job_id": job_id}
        ))
        
        await db.commit()
        logger.info(f"Plan refresh complete for user {user_id}")

async def handle_memory_summarize(job_id, payload):
    user_id = payload.get("user_id")
    chat_id = payload.get("chat_id")
    
    async with AsyncSessionLocal() as db:
        # 1. Fetch recent context and event logs
        stmt = select(InboxItem).where(
            InboxItem.user_id == user_id,
            InboxItem.chat_id == chat_id
        ).order_by(InboxItem.received_at.desc()).limit(15)
        result = await db.execute(stmt)
        messages = result.scalars().all()
        
        stmt_events = select(EventLog).where(
            EventLog.user_id == user_id
        ).order_by(EventLog.created_at.desc()).limit(20)
        events = (await db.execute(stmt_events)).scalars().all()
        source_event_ids = [e.id for e in events]
        
        context_text = "\n".join([f"{m.source}: {m.message_raw}" for m in reversed(messages)])
        
        # 2. Call adapter
        start_time = time.time()
        summary = await adapter.summarize_memory(context_text)
        latency = int((time.time() - start_time) * 1000)
        
        # Record prompt run
        db.add(PromptRun(
            id=str(uuid.uuid4()), request_id=f"job_{job_id}", user_id=user_id,
            operation="summarize", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_SUMMARIZE,
            prompt_version=settings.PROMPT_VERSION_SUMMARIZE, latency_ms=latency, status="success",
            created_at=utc_now()
        ))
        
        # 3. Write MemorySummary
        summary_id = f"sum_{uuid.uuid4().hex[:12]}"
        db.add(MemorySummary(
            id=summary_id, user_id=user_id, chat_id=chat_id,
            summary_type="session", summary_text=summary["summary_text"],
            facts_json=summary.get("facts", []), 
            source_event_ids=source_event_ids,
            created_at=utc_now()
        ))
        
        # 4. Log event
        db.add(EventLog(
            id=str(uuid.uuid4()), request_id=f"job_{job_id}", user_id=user_id,
            event_type="memory_summary_created", entity_type="memory_summary",
            entity_id=summary_id, payload_json={"job_id": job_id, "source_count": len(source_event_ids)}
        ))
        
        await db.commit()
        logger.info(f"Summarization complete for user {user_id}")

async def handle_memory_compact(job_id, payload):
    target_user_id = payload.get("user_id")
    scope = "user" if target_user_id else "global"
    logger.info(f"Starting memory compaction (scope: {scope})...")
    
    retention_cutoff = utc_now() - timedelta(days=settings.TRANSCRIPT_RETENTION_DAYS)
    
    async with AsyncSessionLocal() as db:
        # 1. Identify eligible old rows (older than cutoff)
        eligible_stmt = select(InboxItem).where(InboxItem.received_at < retention_cutoff)
        if target_user_id:
            eligible_stmt = eligible_stmt.where(InboxItem.user_id == target_user_id)
        
        eligible_rows = (await db.execute(eligible_stmt)).scalars().all()
        eligible_old_rows = len(eligible_rows)
        eligible_ids = [r.id for r in eligible_rows]
        
        deleted_rows = 0
        skipped_referenced_rows = 0

        if eligible_ids:
            # 2. Identify referenced rows
            referenced_stmt = select(WorkItem.source_inbox_item_id).where(WorkItem.source_inbox_item_id.in_(eligible_ids))
            if target_user_id:
                referenced_stmt = referenced_stmt.where(WorkItem.user_id == target_user_id)
            referenced_ids = set((await db.execute(referenced_stmt)).scalars().all())
            draft_ref_stmt = select(ActionDraft.source_inbox_item_id).where(
                ActionDraft.source_inbox_item_id.in_(eligible_ids),
                ActionDraft.status == "draft",
                ActionDraft.expires_at >= utc_now(),
            )
            draft_referenced_ids = set((await db.execute(draft_ref_stmt)).scalars().all())
            referenced_ids.update(draft_referenced_ids)
            skipped_referenced_rows = len(referenced_ids)
            
            # 3. Delete only non-referenced rows
            delete_ids = [eid for eid in eligible_ids if eid not in referenced_ids]
            if delete_ids:
                delete_stmt = delete(InboxItem).where(InboxItem.id.in_(delete_ids))
                result = await db.execute(delete_stmt)
                deleted_rows = result.rowcount
        
        # 4. Log stats (Always execute this, Requirement 1 & 6)
        db.add(EventLog(
            id=str(uuid.uuid4()), request_id=f"job_{job_id}", user_id=target_user_id or "system",
            event_type="memory_compaction_completed", 
            payload_json={
                "scope": scope,
                "user_id": target_user_id,
                "eligible_old_rows": eligible_old_rows,
                "deleted_rows": deleted_rows,
                "skipped_referenced_rows": skipped_referenced_rows,
                "cutoff": retention_cutoff.isoformat()
            }
        ))
        
        await db.commit()
        logger.info(f"Compaction complete (scope: {scope}). Deleted: {deleted_rows}, Skipped: {skipped_referenced_rows}")


async def handle_reminder_dispatch(job_id: str, payload: dict):
    target_user_id = payload.get("user_id")
    now = utc_now()

    async with AsyncSessionLocal() as db:
        stmt = (
            select(Reminder)
            .where(
                Reminder.status == ReminderStatus.pending,
                Reminder.remind_at <= now,
            )
            .order_by(Reminder.remind_at.asc())
            .limit(100)
        )
        if target_user_id:
            stmt = stmt.where(Reminder.user_id == target_user_id)
        reminders = (await db.execute(stmt)).scalars().all()

        dispatched = 0
        skipped_no_chat = 0
        failed = 0

        for reminder in reminders:
            mapping_stmt = (
                select(TelegramUserMap)
                .where(TelegramUserMap.user_id == reminder.user_id)
                .order_by(TelegramUserMap.last_seen_at.desc())
                .limit(1)
            )
            mapping = (await db.execute(mapping_stmt)).scalar_one_or_none()
            if mapping is None:
                skipped_no_chat += 1
                db.add(
                    EventLog(
                        id=str(uuid.uuid4()),
                        request_id=f"job_{job_id}",
                        user_id=reminder.user_id,
                        event_type="reminder_dispatch_skipped_no_chat",
                        entity_type="reminder",
                        entity_id=reminder.id,
                        payload_json={"job_id": job_id},
                    )
                )
                continue

            text = f"<b>Reminder</b>\n{escape_html(reminder.title)}"
            if reminder.message:
                text += f"\n\n{escape_html(reminder.message)}"
            try:
                sent = await send_message(mapping.chat_id, text)
                if not (isinstance(sent, dict) and sent.get("ok") is True):
                    raise RuntimeError(f"telegram_send_failed:{sent}")
                recurrence_rule = normalize_recurrence_rule(reminder.recurrence_rule)
                next_remind_at = next_recurrence_time(reminder.remind_at, recurrence_rule) if recurrence_rule else None
                if next_remind_at is not None:
                    reminder.status = ReminderStatus.pending
                    reminder.remind_at = next_remind_at
                else:
                    reminder.status = ReminderStatus.sent
                reminder.last_sent_at = now
                reminder.updated_at = now
                dispatched += 1
                db.add(
                    ConversationEvent(
                        id=f"cev_{uuid.uuid4().hex[:12]}",
                        user_id=reminder.user_id,
                        chat_id=mapping.chat_id,
                        source=ConversationSource.telegram,
                        direction=ConversationDirection.outbound,
                        content_text=f"Reminder: {reminder.title}" + (f"\n\n{reminder.message}" if reminder.message else ""),
                        normalized_text=reminder.title,
                        metadata_json={
                            "job_id": job_id,
                            "entity_type": "reminder",
                            "entity_id": reminder.id,
                        },
                        created_at=now,
                    )
                )
                await remember_recent_reminders(
                    db,
                    user_id=reminder.user_id,
                    chat_id=mapping.chat_id,
                    reminder_ids=[reminder.id],
                    reason="reminder_dispatch",
                    ttl_hours=24,
                )
                db.add(
                    EventLog(
                        id=str(uuid.uuid4()),
                        request_id=f"job_{job_id}",
                        user_id=reminder.user_id,
                        event_type="reminder_dispatched",
                        entity_type="reminder",
                        entity_id=reminder.id,
                        payload_json={
                            "job_id": job_id,
                            "chat_id": mapping.chat_id,
                            "recurrence_rule": recurrence_rule,
                            "next_remind_at": next_remind_at.isoformat() if next_remind_at else None,
                        },
                    )
                )
            except Exception as exc:
                failed += 1
                logger.error("Failed to dispatch reminder %s: %s", reminder.id, exc)
                db.add(
                    EventLog(
                        id=str(uuid.uuid4()),
                        request_id=f"job_{job_id}",
                        user_id=reminder.user_id,
                        event_type="reminder_dispatch_failed",
                        entity_type="reminder",
                        entity_id=reminder.id,
                        payload_json={"job_id": job_id, "error": str(exc)},
                    )
                )

        db.add(
            EventLog(
                id=str(uuid.uuid4()),
                request_id=f"job_{job_id}",
                user_id=target_user_id or "system",
                event_type="reminder_dispatch_completed",
                payload_json={
                    "job_id": job_id,
                    "dispatched": dispatched,
                    "skipped_no_chat": skipped_no_chat,
                    "failed": failed,
                },
            )
        )
        await db.commit()
        if failed:
            raise RuntimeError("One or more reminders failed to dispatch.")

async def worker_loop():
    logger.info("Worker started, listening for jobs...")
    while True:
        try:
            result = await redis_client.blpop(DEFAULT_QUEUE, timeout=5)
            if result:
                _, raw_data = result
                job_data = json.loads(raw_data)
                await process_job(job_data)
        except Exception as e:
            logger.error(f"Error in worker loop: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(worker_loop())
