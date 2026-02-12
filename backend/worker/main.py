import asyncio
import logging
import json
import uuid
import time
from datetime import datetime, timedelta, date, timezone

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete, not_, and_, or_

from common.config import settings
from common.models import (
    Base, MemorySummary, EventLog, InboxItem, PromptRun, 
    Task, Goal, Problem, TodoistTaskMap, TaskStatus, ActionDraft
)
from common.adapter import adapter
from common.todoist import todoist_adapter

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
        elif topic == "sync.todoist":
            await handle_todoist_sync(job_id, payload, job_data)
        elif topic == "sync.todoist.reconcile":
            await handle_todoist_reconcile(job_id, payload, job_data)
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

async def handle_todoist_sync(job_id: str, payload: dict, job_data: dict):
    user_id = payload.get("user_id")
    attempt = job_data.get("attempt", 1)
    max_attempts = MAX_ATTEMPTS # Could be from job_data if passed
    
    logger.info(f"Starting Todoist sync for user {user_id} (attempt {attempt}/{max_attempts})...")
    
    any_task_failed = False
    
    async with AsyncSessionLocal() as db:
        # 1. Fetch only tasks that currently need sync.
        stmt = (
            select(Task, TodoistTaskMap)
            .outerjoin(
                TodoistTaskMap,
                and_(
                    TodoistTaskMap.user_id == Task.user_id,
                    TodoistTaskMap.local_task_id == Task.id,
                ),
            )
            .where(
                Task.user_id == user_id,
                Task.status != TaskStatus.archived,
                or_(
                    TodoistTaskMap.local_task_id.is_(None),
                    TodoistTaskMap.todoist_task_id.is_(None),
                    TodoistTaskMap.sync_state != "synced",
                    TodoistTaskMap.last_synced_at.is_(None),
                    Task.updated_at > TodoistTaskMap.last_synced_at,
                ),
            )
        )
        task_mapping_rows = (await db.execute(stmt)).all()

        for task, mapping in task_mapping_rows:
            
            try:
                # Common payload for create/update
                todoist_payload = {
                    "content": task.title,
                    "description": task.notes or "",
                    "priority": 5 - task.priority if task.priority else 1,
                }
                if task.due_date:
                    todoist_payload["due_date"] = task.due_date.isoformat()

                # Requirement 1: Recovery Path. Treat null/empty remote ID as "needs create"
                if not mapping or not mapping.todoist_task_id:
                    # Create in Todoist
                    logger.info(f"Creating Todoist task for local task {task.id}")
                    resp = await todoist_adapter.create_task(todoist_payload)
                    todoist_id = resp["id"]
                    
                    if not mapping:
                        # New mapping row
                        mapping = TodoistTaskMap(
                            id=str(uuid.uuid4()),
                            user_id=user_id,
                            local_task_id=task.id,
                            todoist_task_id=todoist_id,
                            sync_state="synced",
                            last_synced_at=utc_now(),
                            last_attempt_at=utc_now()
                        )
                        db.add(mapping)
                    else:
                        # Update existing error/placeholder mapping
                        mapping.todoist_task_id = todoist_id
                        mapping.sync_state = "synced"
                        mapping.last_synced_at = utc_now()
                        mapping.last_attempt_at = utc_now()
                        mapping.last_error = None
                    
                    # If it's already done, close it now (create then close)
                    if task.status == TaskStatus.done:
                        logger.info(f"Immediately closing new Todoist task {todoist_id}")
                        await todoist_adapter.close_task(todoist_id)
                    
                else:
                    mapping.last_attempt_at = utc_now()
                    # Check if status is done
                    if task.status == TaskStatus.done:
                        logger.info(f"Closing Todoist task {mapping.todoist_task_id}")
                        await todoist_adapter.close_task(mapping.todoist_task_id)
                    else:
                        # Update Todoist
                        logger.info(f"Updating Todoist task {mapping.todoist_task_id}")
                        await todoist_adapter.update_task(mapping.todoist_task_id, todoist_payload)
                    
                    mapping.sync_state = "synced"
                    mapping.last_synced_at = utc_now()
                    mapping.last_error = None
                        
            except Exception as e:
                any_task_failed = True
                logger.error(f"Failed to sync task {task.id}: {e}")
                
                # Requirement 2: Upsert mapping error row
                if not mapping:
                    mapping = TodoistTaskMap(
                        id=str(uuid.uuid4()),
                        user_id=user_id,
                        local_task_id=task.id,
                        todoist_task_id=None, # Explicitly null for create failures
                        sync_state="error",
                        last_error=str(e),
                        last_attempt_at=utc_now()
                    )
                    db.add(mapping)
                else:
                    mapping.sync_state = "error"
                    mapping.last_error = str(e)
                
                # Requirement 4: Retry Metadata in EventLog
                will_retry = attempt < max_attempts
                next_delay = min(2 ** attempt, 60) if will_retry else None
                
                db.add(EventLog(
                    id=str(uuid.uuid4()), request_id=f"job_{job_id}", user_id=user_id,
                    event_type="todoist_sync_task_failed", entity_type="task",
                    entity_id=task.id, 
                    payload_json={
                        "error": str(e),
                        "job_id": job_id,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "will_retry": will_retry,
                        "next_retry_delay_seconds": next_delay
                    }
                ))

        # 3. Log completion
        db.add(EventLog(
            id=str(uuid.uuid4()), request_id=f"job_{job_id}", user_id=user_id,
            event_type="todoist_sync_completed", payload_json={"job_id": job_id, "any_task_failed": any_task_failed}
        ))
        
        await db.commit()
        
        if any_task_failed:
            raise RuntimeError("One or more tasks failed to sync. Triggering job retry.")
            
        logger.info(f"Todoist sync complete for user {user_id}")


def _remote_to_local_priority(remote_priority: int | None) -> int | None:
    if not isinstance(remote_priority, int):
        return None
    if remote_priority < 1 or remote_priority > 4:
        return None
    return 5 - remote_priority


def _parse_remote_due_date(remote_due: object) -> date | None:
    if not isinstance(remote_due, dict):
        return None
    due_date = remote_due.get("date")
    if not isinstance(due_date, str) or not due_date.strip():
        return None
    try:
        return date.fromisoformat(due_date.strip()[:10])
    except ValueError:
        return None


async def handle_todoist_reconcile(job_id: str, payload: dict, job_data: dict):
    user_id = payload.get("user_id")
    attempt = job_data.get("attempt", 1)
    max_attempts = MAX_ATTEMPTS
    batch_size = max(settings.TODOIST_RECONCILE_BATCH_SIZE, 1)

    logger.info(f"Starting Todoist reconcile for user {user_id} (attempt {attempt}/{max_attempts})...")

    any_task_failed = False
    applied_updates = 0
    remote_missing = 0

    async with AsyncSessionLocal() as db:
        offset = 0
        while True:
            stmt_map = (
                select(TodoistTaskMap)
                .where(
                    TodoistTaskMap.user_id == user_id,
                    TodoistTaskMap.todoist_task_id.isnot(None),
                )
                .order_by(TodoistTaskMap.id)
                .offset(offset)
                .limit(batch_size)
            )
            mappings = (await db.execute(stmt_map)).scalars().all()
            if not mappings:
                break
            offset += len(mappings)

            for mapping in mappings:
                mapping.last_attempt_at = utc_now()
                try:
                    remote_task = await todoist_adapter.get_task(mapping.todoist_task_id)
                    if remote_task is None:
                        remote_missing += 1
                        mapping.sync_state = "error"
                        mapping.last_error = "remote_task_missing"
                        # Remote-missing is treated as terminal drift in v1 (no retry by itself).
                        db.add(
                            EventLog(
                                id=str(uuid.uuid4()),
                                request_id=f"job_{job_id}",
                                user_id=user_id,
                                event_type="todoist_reconcile_remote_missing",
                                entity_type="task",
                                entity_id=mapping.local_task_id,
                                payload_json={
                                    "job_id": job_id,
                                    "todoist_task_id": mapping.todoist_task_id,
                                },
                            )
                        )
                        continue

                    task_stmt = select(Task).where(
                        Task.id == mapping.local_task_id,
                        Task.user_id == user_id,
                    )
                    local_task = (await db.execute(task_stmt)).scalar_one_or_none()
                    if local_task is None:
                        raise RuntimeError("local_task_missing")

                    changed_fields: list[str] = []
                    now = utc_now()
                    remote_completed = bool(remote_task.get("is_completed"))
                    if remote_completed and local_task.status != TaskStatus.done:
                        local_task.status = TaskStatus.done
                        local_task.completed_at = now
                        local_task.updated_at = now
                        changed_fields.append("status")

                    if local_task.status != TaskStatus.done:
                        remote_title = remote_task.get("content")
                        if isinstance(remote_title, str) and remote_title.strip() and remote_title != local_task.title:
                            local_task.title = remote_title
                            local_task.title_norm = remote_title.lower().strip()
                            local_task.updated_at = now
                            changed_fields.append("title")

                        remote_notes = remote_task.get("description")
                        if not isinstance(remote_notes, str):
                            remote_notes = ""
                        if (local_task.notes or "") != remote_notes:
                            local_task.notes = remote_notes or None
                            local_task.updated_at = now
                            changed_fields.append("notes")

                        local_priority = _remote_to_local_priority(remote_task.get("priority"))
                        if local_priority != local_task.priority:
                            local_task.priority = local_priority
                            local_task.updated_at = now
                            changed_fields.append("priority")

                        remote_due_date = _parse_remote_due_date(remote_task.get("due"))
                        if remote_due_date != local_task.due_date:
                            local_task.due_date = remote_due_date
                            local_task.updated_at = now
                            changed_fields.append("due_date")

                    mapping.sync_state = "synced"
                    mapping.last_synced_at = utc_now()
                    mapping.last_error = None

                    if changed_fields:
                        applied_updates += 1
                        db.add(
                            EventLog(
                                id=str(uuid.uuid4()),
                                request_id=f"job_{job_id}",
                                user_id=user_id,
                                event_type="todoist_reconcile_applied",
                                entity_type="task",
                                entity_id=local_task.id,
                                payload_json={
                                    "job_id": job_id,
                                    "todoist_task_id": mapping.todoist_task_id,
                                    "changed_fields": changed_fields,
                                },
                            )
                        )
                except Exception as e:
                    any_task_failed = True
                    mapping.sync_state = "error"
                    mapping.last_error = str(e)
                    db.add(
                        EventLog(
                            id=str(uuid.uuid4()),
                            request_id=f"job_{job_id}",
                            user_id=user_id,
                            event_type="todoist_reconcile_task_failed",
                            entity_type="task",
                            entity_id=mapping.local_task_id,
                            payload_json={
                                "job_id": job_id,
                                "attempt": attempt,
                                "max_attempts": max_attempts,
                                "todoist_task_id": mapping.todoist_task_id,
                                "error": str(e),
                            },
                        )
                    )

        db.add(
            EventLog(
                id=str(uuid.uuid4()),
                request_id=f"job_{job_id}",
                user_id=user_id,
                event_type="todoist_reconcile_completed",
                payload_json={
                    "job_id": job_id,
                    "applied_updates": applied_updates,
                    "remote_missing": remote_missing,
                    "any_task_failed": any_task_failed,
                },
            )
        )
        await db.commit()

    if any_task_failed:
        raise RuntimeError("One or more mapped tasks failed to reconcile. Triggering job retry.")
    logger.info(f"Todoist reconcile complete for user {user_id}")

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
            referenced_stmt = select(Task.source_inbox_item_id).where(
                Task.source_inbox_item_id.in_(eligible_ids)
            )
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
