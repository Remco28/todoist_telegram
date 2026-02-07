import asyncio
import logging
import json
import uuid
import time
from datetime import datetime, timedelta

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, delete, not_

from common.config import settings
from common.models import (
    Base, MemorySummary, EventLog, InboxItem, PromptRun, 
    Task, Goal, Problem
)
from common.adapter import adapter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

# DB Setup
engine = create_async_engine(settings.DATABASE_URL)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Redis Setup
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

DEFAULT_QUEUE = "default_queue"
DLQ = "dead_letter_queue"
MAX_ATTEMPTS = 5

from common.planner import collect_planning_state, build_plan_payload, render_fallback_plan_explanation

async def process_job(job_data: dict):
    topic = job_data.get("topic")
    payload = job_data.get("payload", {})
    job_id = job_data.get("job_id")
    attempt = job_data.get("attempt", 1)
    
    logger.info(f"Processing job: {topic} (id: {job_id}, attempt: {attempt})")
    
    try:
        if topic == "memory.summarize":
            await handle_memory_summarize(job_id, payload)
        elif topic == "memory.compact":
            await handle_memory_compact(job_id, payload)
        elif topic == "plan.refresh":
            await handle_plan_refresh(job_id, payload)
        elif topic == "sync.todoist":
            logger.info("Todoist sync placeholder")
        else:
            logger.warning(f"Unknown topic: {topic}")
            
    except Exception as e:
        logger.error(f"Job failed (attempt {attempt}): {e}")
        if attempt < MAX_ATTEMPTS:
            job_data["attempt"] = attempt + 1
            wait_time = min(2 ** attempt, 60)
            logger.info(f"Retrying in {wait_time}s...")
            await asyncio.sleep(wait_time)
            await redis_client.rpush(DEFAULT_QUEUE, json.dumps(job_data))
        else:
            logger.error(f"Job exceeded max attempts, moving to DLQ: {job_id}")
            await redis_client.rpush(DLQ, json.dumps(job_data))

async def handle_plan_refresh(job_id: str, payload: dict):
    user_id = payload.get("user_id")
    chat_id = payload.get("chat_id")
    logger.info(f"Refreshing plan for user {user_id}...")
    
    async with AsyncSessionLocal() as db:
        # 1. Collect state
        state = await collect_planning_state(db, user_id)
        
        # 2. Build deterministic payload
        now = datetime.utcnow()
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
                created_at=datetime.utcnow()
            ))
        except Exception as e:
            logger.error(f"Plan rewrite failed in worker: {e}")
            plan_payload = render_fallback_plan_explanation(plan_payload)
            
            # Requirement 4: Observability for failure
            db.add(PromptRun(
                id=str(uuid.uuid4()), request_id=f"job_{job_id}", user_id=user_id,
                operation="plan", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_PLAN,
                prompt_version=settings.PROMPT_VERSION_PLAN, status="error", error_code=type(e).__name__,
                created_at=datetime.utcnow()
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
            await redis_client.setex(cache_key, 86400, validated_payload.json())
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
                payload_fb = build_plan_payload(state_fb, datetime.utcnow())
                validated_fb = PlanResponseV1(**payload_fb)
                await redis_client.setex(f"plan:today:{user_id}:{chat_id}", 86400, validated_fb.json())
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
            created_at=datetime.utcnow()
        ))
        
        # 3. Write MemorySummary
        summary_id = f"sum_{uuid.uuid4().hex[:12]}"
        db.add(MemorySummary(
            id=summary_id, user_id=user_id, chat_id=chat_id,
            summary_type="session", summary_text=summary["summary_text"],
            facts_json=summary.get("facts", []), 
            source_event_ids=source_event_ids,
            created_at=datetime.utcnow()
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
    
    retention_cutoff = datetime.utcnow() - timedelta(days=settings.TRANSCRIPT_RETENTION_DAYS)
    
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
