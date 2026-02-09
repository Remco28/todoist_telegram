import uuid
import hashlib
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, select, update, delete

import redis.asyncio as redis

from common.config import settings
from common.models import (
    Base, IdempotencyKey, InboxItem, Task, Goal, Problem, 
    EntityLink, EventLog, PromptRun, TaskStatus, GoalStatus, 
    ProblemStatus, LinkType, EntityType
)
from common.adapter import adapter
from common.memory import assemble_context
from common.planner import collect_planning_state, build_plan_payload, render_fallback_plan_explanation
from api.schemas import (
    ThoughtCaptureRequest, ThoughtCaptureResponse, AppliedChanges,
    TaskUpdate, GoalUpdate, ProblemUpdate, LinkCreate,
    PlanRefreshRequest, PlanRefreshResponse, PlanResponseV1,
    QueryAskRequest, QueryResponseV1,
    TelegramUpdateEnvelope, TelegramWebhookResponse
)
from common.telegram import (
    verify_telegram_secret, parse_update, extract_command, send_message,
    format_today_plan, format_plan_refresh_ack, format_focus_mode, format_capture_ack,
    escape_html
)

# --- Shared Capture Pipeline ---

async def _apply_capture(db: AsyncSession, user_id: str, chat_id: str, source: str,
                         message: str, extraction: dict, request_id: str,
                         client_msg_id: Optional[str] = None) -> tuple:
    """Core capture pipeline used by both API and Telegram paths.
    Returns (inbox_item_id, applied: AppliedChanges)."""
    applied = AppliedChanges()
    inbox_item_id = f"inb_{uuid.uuid4().hex[:12]}"
    db.add(InboxItem(
        id=inbox_item_id, user_id=user_id, chat_id=chat_id, source=source,
        client_msg_id=client_msg_id, message_raw=message, message_norm=message.strip(),
        received_at=datetime.utcnow()
    ))

    entity_map = {}
    for t_data in extraction.get("tasks", []):
        title_norm = t_data["title"].lower().strip()
        stmt = select(Task).where(Task.user_id == user_id, Task.title_norm == title_norm, Task.status != TaskStatus.archived)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            entity_map[(EntityType.task, title_norm)] = existing.id
            applied.tasks_updated += 1
        else:
            task_id = f"tsk_{uuid.uuid4().hex[:12]}"
            db.add(Task(
                id=task_id, user_id=user_id, title=t_data["title"], title_norm=title_norm,
                status=t_data.get("status", TaskStatus.open), priority=t_data.get("priority"),
                source_inbox_item_id=inbox_item_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow()
            ))
            entity_map[(EntityType.task, title_norm)] = task_id
            applied.tasks_created += 1

    for g_data in extraction.get("goals", []):
        title_norm = g_data["title"].lower().strip()
        stmt = select(Goal).where(Goal.user_id == user_id, Goal.title_norm == title_norm)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing: entity_map[(EntityType.goal, title_norm)] = existing.id
        else:
            goal_id = f"gol_{uuid.uuid4().hex[:12]}"
            db.add(Goal(id=goal_id, user_id=user_id, title=g_data["title"], title_norm=title_norm, created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
            entity_map[(EntityType.goal, title_norm)] = goal_id
            applied.goals_created += 1

    for p_data in extraction.get("problems", []):
        title_norm = p_data["title"].lower().strip()
        stmt = select(Problem).where(Problem.user_id == user_id, Problem.title_norm == title_norm)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing: entity_map[(EntityType.problem, title_norm)] = existing.id
        else:
            prob_id = f"prb_{uuid.uuid4().hex[:12]}"
            db.add(Problem(id=prob_id, user_id=user_id, title=p_data["title"], title_norm=title_norm, created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
            entity_map[(EntityType.problem, title_norm)] = prob_id
            applied.problems_created += 1

    for l_data in extraction.get("links", []):
        try:
            from_type = EntityType(l_data["from_type"])
            to_type = EntityType(l_data["to_type"])
            link_type = LinkType(l_data["link_type"])
            from_id = entity_map.get((from_type, l_data["from_title"].lower().strip()))
            to_id = entity_map.get((to_type, l_data["to_title"].lower().strip()))
            if from_id and to_id:
                db.add(EntityLink(id=f"lnk_{uuid.uuid4().hex[:12]}", user_id=user_id, from_entity_type=from_type, from_entity_id=from_id, to_entity_type=to_type, to_entity_id=to_id, link_type=link_type, created_at=datetime.utcnow()))
                applied.links_created += 1
        except Exception as e:
            db.add(EventLog(id=str(uuid.uuid4()), request_id=request_id, user_id=user_id, event_type="link_validation_failed", payload_json={"entry": l_data, "error": str(e)}))

    await db.commit()
    job_payload = {"job_id": str(uuid.uuid4()), "topic": "memory.summarize", "payload": {"user_id": user_id, "chat_id": chat_id, "inbox_item_id": inbox_item_id}}
    await redis_client.rpush("default_queue", json.dumps(job_payload))
    return inbox_item_id, applied

# --- Internal Helpers for Integration Routing ---

async def handle_telegram_command(command: str, args: Optional[str], chat_id: str, db: AsyncSession):
    user_id = "usr_dev" # Phase 4 default

    if command == "/today":
        # Simulate GET /v1/plan/get_today logic
        cache_key = f"plan:today:{user_id}:{chat_id}"
        cached = await redis_client.get(cache_key)
        if cached:
            payload = json.loads(cached)
        else:
            state = await collect_planning_state(db, user_id)
            payload = build_plan_payload(state, datetime.utcnow())
            payload = render_fallback_plan_explanation(payload)
        
        await send_message(chat_id, format_today_plan(payload))

    elif command == "/plan":
        job_id = str(uuid.uuid4())
        await redis_client.rpush("default_queue", json.dumps({"job_id": job_id, "topic": "plan.refresh", "payload": {"user_id": user_id, "chat_id": chat_id}}))
        await send_message(chat_id, format_plan_refresh_ack(job_id))

    elif command == "/focus":
        cache_key = f"plan:today:{user_id}:{chat_id}"
        cached = await redis_client.get(cache_key)
        if cached:
            payload = json.loads(cached)
        else:
            state = await collect_planning_state(db, user_id)
            payload = build_plan_payload(state, datetime.utcnow())
        
        await send_message(chat_id, format_focus_mode(payload))

    elif command == "/done":
        if not args:
            await send_message(chat_id, "Please provide a task ID. Example: <code>/done tsk_123</code>")
            return
        
        task_id = args.strip()
        stmt = update(Task).where(Task.id == task_id, Task.user_id == user_id).values(status=TaskStatus.done, completed_at=datetime.utcnow())
        res = await db.execute(stmt)
        if res.rowcount > 0:
            await db.commit()
            await send_message(chat_id, f"Task <code>{escape_html(task_id)}</code> marked as done.")
        else:
            await send_message(chat_id, f"Task <code>{escape_html(task_id)}</code> not found or not owned by you.")

    else:
        supported = "/today - Show today's plan\n/plan - Refresh plan\n/focus - Show top 3 tasks\n/done &lt;id&gt; - Mark task as done"
        await send_message(chat_id, f"Unknown command. Supported:\n{supported}")

logger = logging.getLogger(__name__)
app = FastAPI(title="Todoist MCP API")

# DB Setup
engine = create_async_engine(settings.DATABASE_URL, echo=settings.APP_ENV == "dev")
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Redis Setup
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# --- Middleware & Dependencies ---

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

async def get_authenticated_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid authorization header")
    token = auth_header.split(" ")[1]
    if token not in settings.auth_tokens:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    # Restore mapping (Requirement 3)
    if token == "test_user_2": return "usr_2"
    return "usr_dev"

async def check_idempotency(request: Request, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if request.method not in ["POST", "PATCH", "PUT", "DELETE"]:
        return
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Idempotency-Key header")
    
    body = await request.body()
    identity_string = f"{request.method}|{request.url.path}|{user_id}|{body.decode('utf-8', errors='ignore')}"
    body_hash = hashlib.sha256(identity_string.encode("utf-8")).hexdigest()
    
    stmt = select(IdempotencyKey).where(IdempotencyKey.user_id == user_id, IdempotencyKey.idempotency_key == idempotency_key)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    
    if existing:
        if existing.request_hash != body_hash:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Idempotency key collision")
        request.state.idempotent_response = existing.response_body
    
    request.state.idempotency_key = idempotency_key
    request.state.request_hash = body_hash

async def save_idempotency(user_id: str, idempotency_key: str, request_hash: str, status_code: int, response_body: dict):
    async with AsyncSessionLocal() as db:
        ik = IdempotencyKey(
            id=str(uuid.uuid4()), user_id=user_id, idempotency_key=idempotency_key,
            request_hash=request_hash, response_status=status_code, response_body=response_body,
            created_at=datetime.utcnow(), expires_at=datetime.utcnow() + timedelta(hours=settings.IDEMPOTENCY_TTL_HOURS)
        )
        db.add(ik)
        await db.commit()

# --- Health Endpoints ---

@app.get("/health/live")
async def health_live():
    return {"status": "ok"}

@app.get("/health/ready")
async def health_ready(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        await redis_client.ping()
    except Exception:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Infrastructure unreachable")
    return {"status": "ready"}

# --- Telegram Integration ---

@app.post("/v1/integrations/telegram/webhook", response_model=TelegramWebhookResponse)
async def telegram_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    # 1. Validate secret
    if not verify_telegram_secret(request.headers):
        raise HTTPException(status_code=403, detail="Unauthorized webhook source")
    
    # 2. Parse update
    try:
        update_json = await request.json()
    except Exception:
        return {"status": "ignored"}
        
    data = parse_update(update_json)
    if not data:
        return {"status": "ignored"}
    
    chat_id = data["chat_id"]
    text = data["text"]
    
    # 3. Command Routing
    command, args = extract_command(text)
    if command:
        await handle_telegram_command(command, args, chat_id, db)
    else:
        # 4. Non-command text -> Full Capture Flow
        user_id = "usr_dev"
        request_id = f"tg_{uuid.uuid4().hex[:8]}"
        try:
            extraction = await adapter.extract_structured_updates(text)
            if not all(k in extraction for k in ["tasks", "goals", "problems", "links"]):
                raise ValueError("Invalid extraction shape")
            _, applied = await _apply_capture(
                db=db, user_id=user_id, chat_id=chat_id,
                source=settings.TELEGRAM_DEFAULT_SOURCE, message=text,
                extraction=extraction, request_id=request_id
            )
            await send_message(chat_id, format_capture_ack(applied.dict()))
        except Exception as e:
            logger.error(f"Telegram capture failed: {e}")
            await send_message(chat_id, "Sorry, I had trouble processing that thought. Please try again later.")

    return {"status": "ok"}

# --- Capture Endpoints ---

@app.post("/v1/capture/thought", response_model=ThoughtCaptureResponse, dependencies=[Depends(check_idempotency)])
async def capture_thought(request: Request, payload: ThoughtCaptureRequest, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    request_id = request.state.request_id
    
    extraction = None
    for attempt_num in range(1, 3):
        start_time = time.time()
        try:
            extraction = await adapter.extract_structured_updates(payload.message)
            latency = int((time.time() - start_time) * 1000)
            if not all(k in extraction for k in ["tasks", "goals", "problems", "links"]):
                raise ValueError("Invalid extraction shape")
            db.add(PromptRun(
                id=str(uuid.uuid4()), request_id=request_id, user_id=user_id, operation="extract",
                provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_EXTRACT,
                prompt_version=settings.PROMPT_VERSION_EXTRACT, latency_ms=latency, status="success", created_at=datetime.utcnow()
            ))
            break
        except Exception as e:
            db.add(PromptRun(
                id=str(uuid.uuid4()), request_id=request_id, user_id=user_id, operation="extract",
                provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_EXTRACT,
                prompt_version=settings.PROMPT_VERSION_EXTRACT, status="error", error_code=type(e).__name__, created_at=datetime.utcnow()
            ))
            if attempt_num == 2:
                await db.commit()
                raise HTTPException(status_code=422, detail="Extraction failed after retries")

    inbox_item_id, applied = await _apply_capture(
        db=db, user_id=user_id, chat_id=payload.chat_id, source=payload.source,
        message=payload.message, extraction=extraction, request_id=request_id,
        client_msg_id=payload.client_msg_id
    )
    resp = ThoughtCaptureResponse(status="ok", inbox_item_id=inbox_item_id, applied=applied, summary_refresh_enqueued=True)
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp.dict())
    return resp

# --- Entity CRUD ---

@app.get("/v1/tasks")
async def list_tasks(status: Optional[TaskStatus] = None, goal_id: Optional[str] = None, cursor: Optional[str] = None, limit: int = 50, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    query = select(Task).where(Task.user_id == user_id).order_by(Task.id).limit(min(limit, 200))
    if status: query = query.where(Task.status == status)
    if goal_id:
        query = query.join(EntityLink, (EntityLink.from_entity_id == Task.id) & (EntityLink.from_entity_type == EntityType.task))
        query = query.where(EntityLink.to_entity_id == goal_id, EntityLink.to_entity_type == EntityType.goal)
    if cursor: query = query.where(Task.id > cursor)
    return (await db.execute(query)).scalars().all()

@app.patch("/v1/tasks/{task_id}", dependencies=[Depends(check_idempotency)])
async def update_task(request: Request, task_id: str, payload: TaskUpdate, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    update_data = payload.dict(exclude_unset=True)
    if not update_data: raise HTTPException(status_code=400, detail="No fields to update")
    if "status" in update_data: update_data["completed_at"] = datetime.utcnow() if update_data["status"] == TaskStatus.done else None
    stmt = update(Task).where(Task.id == task_id, Task.user_id == user_id).values(**update_data)
    if (await db.execute(stmt)).rowcount == 0: raise HTTPException(status_code=404, detail="Task not found")
    await db.commit()
    resp = {"status": "ok"}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

@app.get("/v1/problems")
async def list_problems(user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Problem).where(Problem.user_id == user_id))).scalars().all()

@app.patch("/v1/problems/{problem_id}", dependencies=[Depends(check_idempotency)])
async def update_problem(request: Request, problem_id: str, payload: ProblemUpdate, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    stmt = update(Problem).where(Problem.id == problem_id, Problem.user_id == user_id).values(**payload.dict(exclude_unset=True))
    if (await db.execute(stmt)).rowcount == 0: raise HTTPException(status_code=404, detail="Problem not found")
    await db.commit()
    resp = {"status": "ok"}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

@app.get("/v1/goals")
async def list_goals(user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(Goal).where(Goal.user_id == user_id))).scalars().all()

@app.patch("/v1/goals/{goal_id}", dependencies=[Depends(check_idempotency)])
async def update_goal(request: Request, goal_id: str, payload: GoalUpdate, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    stmt = update(Goal).where(Goal.id == goal_id, Goal.user_id == user_id).values(**payload.dict(exclude_unset=True))
    if (await db.execute(stmt)).rowcount == 0: raise HTTPException(status_code=404, detail="Goal not found")
    await db.commit()
    resp = {"status": "ok"}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

@app.post("/v1/links", dependencies=[Depends(check_idempotency)])
async def create_link(request: Request, payload: LinkCreate, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    link_id = f"lnk_{uuid.uuid4().hex[:12]}"
    db.add(EntityLink(id=link_id, user_id=user_id, from_entity_type=payload.from_entity_type, from_entity_id=payload.from_entity_id, to_entity_type=payload.to_entity_type, to_entity_id=payload.to_entity_id, link_type=payload.link_type, created_at=datetime.utcnow()))
    await db.commit()
    resp = {"id": link_id}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

@app.delete("/v1/links/{link_id}", dependencies=[Depends(check_idempotency)])
async def delete_link(request: Request, link_id: str, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    if (await db.execute(delete(EntityLink).where(EntityLink.id == link_id, EntityLink.user_id == user_id))).rowcount > 0: await db.commit()
    resp = {"status": "ok"}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

# --- Planning & Query (Phase 3) ---

@app.post("/v1/plan/refresh", response_model=PlanRefreshResponse, dependencies=[Depends(check_idempotency)])
async def plan_refresh(request: Request, payload: PlanRefreshRequest, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    job_id = str(uuid.uuid4())
    await redis_client.rpush("default_queue", json.dumps({"job_id": job_id, "topic": "plan.refresh", "payload": {"user_id": user_id, "chat_id": payload.chat_id}}))
    resp = PlanRefreshResponse(status="ok", enqueued=True, job_id=job_id)
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp.dict())
    return resp

@app.get("/v1/plan/get_today", response_model=PlanResponseV1, dependencies=[Depends(get_authenticated_user)])
async def get_today_plan(chat_id: str, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    cached = await redis_client.get(f"plan:today:{user_id}:{chat_id}")
    if cached:
        try:
            return PlanResponseV1(**json.loads(cached))
        except Exception as e:
            logger.warning(f"Cached plan invalid: {e}")
    
    state = await collect_planning_state(db, user_id)
    payload = build_plan_payload(state, datetime.utcnow())
    try:
        validated = PlanResponseV1(**render_fallback_plan_explanation(payload))
        return validated
    except Exception as e:
        logger.error(f"Plan validation failed: {e}")
        db.add(EventLog(
            id=str(uuid.uuid4()), request_id=f"req_{uuid.uuid4().hex[:8]}", user_id=user_id,
            event_type="plan_rewrite_fallback", payload_json={"error": str(e), "context": "api_get_today"}
        ))
        await db.commit()
        # Create a emergency minimal valid payload if even the deterministic builder failed somehow
        emergency_payload = {
            "schema_version": "plan.v1", "plan_window": "today", 
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "today_plan": [], "next_actions": [], "blocked_items": []
        }
        return PlanResponseV1(**emergency_payload)

@app.post("/v1/query/ask", response_model=QueryResponseV1, dependencies=[Depends(get_authenticated_user)])
async def query_ask(payload: QueryAskRequest, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    ctx = await assemble_context(db=db, user_id=user_id, chat_id=payload.chat_id, query=payload.query, max_tokens=payload.max_tokens or settings.QUERY_MAX_TOKENS)
    start_time = time.time()
    request_id = str(uuid.uuid4())
    try:
        raw_resp = await adapter.answer_query(payload.query, ctx)
        query_response = QueryResponseV1(**raw_resp) # Requirement 2: Strict Validation
        db.add(PromptRun(id=str(uuid.uuid4()), request_id=request_id, user_id=user_id, operation="query", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_QUERY, prompt_version=settings.PROMPT_VERSION_QUERY, latency_ms=int((time.time()-start_time)*1000), status="success", created_at=datetime.utcnow()))
    except Exception as e:
        logger.error(f"Query failure: {e}")
        db.add(PromptRun(id=str(uuid.uuid4()), request_id=request_id, user_id=user_id, operation="query", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_QUERY, prompt_version=settings.PROMPT_VERSION_QUERY, status="error", error_code=type(e).__name__, created_at=datetime.utcnow()))
        db.add(EventLog(id=str(uuid.uuid4()), request_id=request_id, user_id=user_id, event_type="query_fallback_used", payload_json={"error": str(e)}))
        query_response = QueryResponseV1(answer="I'm sorry, I couldn't process your request.", confidence=0.0)
    await db.commit()
    return query_response

@app.get("/v1/memory/context", dependencies=[Depends(get_authenticated_user)])
async def get_memory_context(chat_id: str, query: str, max_tokens: Optional[int] = None, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    return await assemble_context(db=db, user_id=user_id, chat_id=chat_id, query=query, max_tokens=max_tokens)