import uuid
import hashlib
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
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
from api.schemas import (
    ThoughtCaptureRequest, ThoughtCaptureResponse, AppliedChanges,
    TaskUpdate, GoalUpdate, ProblemUpdate, LinkCreate
)

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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header"
        )
    token = auth_header.split(" ")[1]
    if token not in settings.auth_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    # Simulation: different tokens represent different users for testing Revision 3
    if token == "test_user_2":
        return "usr_2"
    return "usr_dev"

async def check_idempotency(request: Request, user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    if request.method not in ["POST", "PATCH", "PUT", "DELETE"]:
        return

    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Idempotency-Key header"
        )
    
    body = await request.body()
    identity_string = f"{request.method}|{request.url.path}|{user_id}|{body.decode('utf-8', errors='ignore')}"
    body_hash = hashlib.sha256(identity_string.encode("utf-8")).hexdigest()
    
    stmt = select(IdempotencyKey).where(
        IdempotencyKey.user_id == user_id,
        IdempotencyKey.idempotency_key == idempotency_key
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    
    if existing:
        if existing.request_hash != body_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key collision: different identity payload"
            )
        request.state.idempotent_response = existing.response_body
    
    request.state.idempotency_key = idempotency_key
    request.state.request_hash = body_hash

async def save_idempotency(user_id: str, idempotency_key: str, request_hash: str, status_code: int, response_body: dict):
    async with AsyncSessionLocal() as db:
        ik = IdempotencyKey(
            id=str(uuid.uuid4()),
            user_id=user_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            response_status=status_code,
            response_body=response_body,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(hours=settings.IDEMPOTENCY_TTL_HOURS)
        )
        db.add(ik)
        await db.commit()

# --- Endpoints ---

@app.get("/health/live")
async def health_live():
    return {"status": "ok"}

@app.get("/health/ready")
async def health_ready(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        await redis_client.ping()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Infrastructure unreachable"
        )
    return {"status": "ready"}

@app.post("/v1/capture/thought", 
          response_model=ThoughtCaptureResponse,
          dependencies=[Depends(check_idempotency)])
async def capture_thought(
    request: Request, 
    payload: ThoughtCaptureRequest, 
    user_id: str = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db)
):
    if hasattr(request.state, "idempotent_response"):
        return request.state.idempotent_response

    request_id = request.state.request_id
    
    extraction = None
    max_retries = 2
    for attempt_num in range(1, max_retries + 1):
        start_time = time.time()
        try:
            extraction = await adapter.extract_structured_updates(payload.message)
            latency = int((time.time() - start_time) * 1000)
            
            if not all(k in extraction for k in ["tasks", "goals", "problems", "links"]):
                raise ValueError("Invalid extraction shape")
                
            db.add(PromptRun(
                id=str(uuid.uuid4()), request_id=request_id, user_id=user_id,
                operation="extract", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_EXTRACT,
                prompt_version=settings.PROMPT_VERSION_EXTRACT, latency_ms=latency, status="success",
                created_at=datetime.utcnow()
            ))
            break
        except Exception as e:
            db.add(PromptRun(
                id=str(uuid.uuid4()), request_id=request_id, user_id=user_id,
                operation="extract", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL_EXTRACT,
                prompt_version=settings.PROMPT_VERSION_EXTRACT, status="error", error_code=type(e).__name__,
                created_at=datetime.utcnow()
            ))
            if attempt_num == max_retries:
                await db.commit()
                raise HTTPException(status_code=422, detail="Extraction failed after retries")
            continue

    applied = AppliedChanges()
    
    inbox_item_id = f"inb_{uuid.uuid4().hex[:12]}"
    inbox_item = InboxItem(
        id=inbox_item_id, user_id=user_id, chat_id=payload.chat_id,
        source=payload.source, client_msg_id=payload.client_msg_id,
        message_raw=payload.message, message_norm=payload.message.strip(),
        received_at=datetime.utcnow()
    )
    db.add(inbox_item)
    
    # Requirement 3: Canonical Entity Map using Enums
    entity_map = {} # (EntityType, title_norm) -> id

    # Tasks
    for t_data in extraction.get("tasks", []):
        title_norm = t_data["title"].lower().strip()
        stmt = select(Task).where(Task.user_id == user_id, Task.title_norm == title_norm, Task.status != TaskStatus.archived)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        
        if existing:
            entity_map[(EntityType.task, title_norm)] = existing.id
            applied.tasks_updated += 1
        else:
            task_id = f"tsk_{uuid.uuid4().hex[:12]}"
            task = Task(
                id=task_id, user_id=user_id, title=t_data["title"], title_norm=title_norm,
                status=t_data.get("status", TaskStatus.open), priority=t_data.get("priority"),
                source_inbox_item_id=inbox_item_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow()
            )
            db.add(task)
            entity_map[(EntityType.task, title_norm)] = task_id
            applied.tasks_created += 1

    # Goals
    for g_data in extraction.get("goals", []):
        title_norm = g_data["title"].lower().strip()
        stmt = select(Goal).where(Goal.user_id == user_id, Goal.title_norm == title_norm)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            entity_map[(EntityType.goal, title_norm)] = existing.id
        else:
            goal_id = f"gol_{uuid.uuid4().hex[:12]}"
            goal = Goal(
                id=goal_id, user_id=user_id, title=g_data["title"], title_norm=title_norm,
                status=g_data.get("status", GoalStatus.active), created_at=datetime.utcnow(), updated_at=datetime.utcnow()
            )
            db.add(goal)
            entity_map[(EntityType.goal, title_norm)] = goal_id
            applied.goals_created += 1

    # Problems
    for p_data in extraction.get("problems", []):
        title_norm = p_data["title"].lower().strip()
        stmt = select(Problem).where(Problem.user_id == user_id, Problem.title_norm == title_norm)
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            entity_map[(EntityType.problem, title_norm)] = existing.id
        else:
            prob_id = f"prb_{uuid.uuid4().hex[:12]}"
            prob = Problem(
                id=prob_id, user_id=user_id, title=p_data["title"], title_norm=title_norm,
                status=p_data.get("status", ProblemStatus.active), created_at=datetime.utcnow(), updated_at=datetime.utcnow()
            )
            db.add(prob)
            entity_map[(EntityType.problem, title_norm)] = prob_id
            applied.problems_created += 1

    # Links (Requirement 2 & 3: Explicit Validation + Enum Normalization)
    for l_data in extraction.get("links", []):
        try:
            # 1. Field Validation
            if not all(k in l_data for k in ["from_type", "from_title", "to_type", "to_title", "link_type"]):
                logger.warning(f"Skipping malformed link: {l_data}")
                db.add(EventLog(
                    id=str(uuid.uuid4()), request_id=request_id, user_id=user_id,
                    event_type="link_validation_failed", payload_json={"reason": "missing_fields", "entry": l_data}
                ))
                continue
            
            # 2. Enum Validation / Normalization
            from_type = EntityType(l_data["from_type"])
            to_type = EntityType(l_data["to_type"])
            link_type = LinkType(l_data["link_type"])
            
            from_title_norm = l_data["from_title"].lower().strip()
            to_title_norm = l_data["to_title"].lower().strip()
            
            # 3. Resolution
            from_id = entity_map.get((from_type, from_title_norm))
            to_id = entity_map.get((to_type, to_title_norm))
            
            if from_id and to_id:
                link_id = f"lnk_{uuid.uuid4().hex[:12]}"
                link = EntityLink(
                    id=link_id, user_id=user_id, from_entity_type=from_type, from_entity_id=from_id,
                    to_entity_type=to_type, to_entity_id=to_id, link_type=link_type,
                    created_at=datetime.utcnow()
                )
                db.add(link)
                applied.links_created += 1
            else:
                logger.info(f"Link resolution failed for titles: {from_title_norm} -> {to_title_norm}")
                
        except (ValueError, KeyError) as e:
            logger.warning(f"Skipping invalid link entry: {l_data}. Error: {e}")
            db.add(EventLog(
                id=str(uuid.uuid4()), request_id=request_id, user_id=user_id,
                event_type="link_validation_failed", payload_json={"reason": "invalid_enums", "entry": l_data, "error": str(e)}
            ))
            continue

    db.add(EventLog(
        id=str(uuid.uuid4()), request_id=request_id, user_id=user_id,
        event_type="thought_processed", payload_json=applied.dict()
    ))

    await db.commit()
    
    job_payload = {
        "job_id": str(uuid.uuid4()), "topic": "memory.summarize", "created_at": datetime.utcnow().isoformat(),
        "payload": {"user_id": user_id, "chat_id": payload.chat_id, "inbox_item_id": inbox_item_id}
    }
    await redis_client.rpush("default_queue", json.dumps(job_payload))
    
    resp = ThoughtCaptureResponse(status="ok", inbox_item_id=inbox_item_id, applied=applied, summary_refresh_enqueued=True)
    if all(v == 0 for v in applied.dict().values()):
        resp.reason = "message_logged_no_actionable_changes"

    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp.dict())
    return resp

@app.get("/v1/tasks")
async def list_tasks(
    status: Optional[TaskStatus] = None, 
    goal_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 50, 
    user_id: str = Depends(get_authenticated_user), 
    db: AsyncSession = Depends(get_db)
):
    limit = min(limit, 200)
    query = select(Task).where(Task.user_id == user_id).order_by(Task.id)
    
    if status: query = query.where(Task.status == status)
    if goal_id:
        query = query.join(EntityLink, (EntityLink.from_entity_id == Task.id) & (EntityLink.from_entity_type == EntityType.task))
        query = query.where(EntityLink.to_entity_id == goal_id, EntityLink.to_entity_type == EntityType.goal)
        
    if cursor: query = query.where(Task.id > cursor)
    
    result = await db.execute(query.limit(limit))
    return result.scalars().all()

@app.patch("/v1/tasks/{task_id}", dependencies=[Depends(check_idempotency)])
async def update_task(
    request: Request, task_id: str, payload: TaskUpdate, 
    user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)
):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    
    update_data = payload.dict(exclude_unset=True)
    if not update_data: raise HTTPException(status_code=400, detail="No fields to update")
    
    if "status" in update_data:
        if update_data["status"] == TaskStatus.done:
            update_data["completed_at"] = datetime.utcnow()
        else:
            update_data["completed_at"] = None

    stmt = update(Task).where(Task.id == task_id, Task.user_id == user_id).values(**update_data)
    res = await db.execute(stmt)
    if res.rowcount == 0: raise HTTPException(status_code=404, detail="Task not found")
    await db.commit()
    
    resp = {"status": "ok"}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

@app.get("/v1/problems")
async def list_problems(user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Problem).where(Problem.user_id == user_id))
    return result.scalars().all()

@app.patch("/v1/problems/{problem_id}", dependencies=[Depends(check_idempotency)])
async def update_problem(
    request: Request, problem_id: str, payload: ProblemUpdate, 
    user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)
):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    update_data = payload.dict(exclude_unset=True)
    stmt = update(Problem).where(Problem.id == problem_id, Problem.user_id == user_id).values(**update_data)
    res = await db.execute(stmt)
    if res.rowcount == 0: raise HTTPException(status_code=404, detail="Problem not found")
    await db.commit()
    resp = {"status": "ok"}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

@app.get("/v1/goals")
async def list_goals(user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Goal).where(Goal.user_id == user_id))
    return result.scalars().all()

@app.patch("/v1/goals/{goal_id}", dependencies=[Depends(check_idempotency)])
async def update_goal(
    request: Request, goal_id: str, payload: GoalUpdate, 
    user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)
):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    update_data = payload.dict(exclude_unset=True)
    stmt = update(Goal).where(Goal.id == goal_id, Goal.user_id == user_id).values(**update_data)
    res = await db.execute(stmt)
    if res.rowcount == 0: raise HTTPException(status_code=404, detail="Goal not found")
    await db.commit()
    resp = {"status": "ok"}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

@app.post("/v1/links", dependencies=[Depends(check_idempotency)])
async def create_link(
    request: Request, payload: LinkCreate, 
    user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)
):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    link_id = f"lnk_{uuid.uuid4().hex[:12]}"
    link = EntityLink(
        id=link_id, user_id=user_id, from_entity_type=payload.from_entity_type, from_entity_id=payload.from_entity_id,
        to_entity_type=payload.to_entity_type, to_entity_id=payload.to_entity_id, link_type=payload.link_type,
        created_at=datetime.utcnow()
    )
    db.add(link)
    await db.commit()
    resp = {"id": link_id}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp

@app.delete("/v1/links/{link_id}", dependencies=[Depends(check_idempotency)])
async def delete_link(
    request: Request, link_id: str, 
    user_id: str = Depends(get_authenticated_user), db: AsyncSession = Depends(get_db)
):
    if hasattr(request.state, "idempotent_response"): return request.state.idempotent_response
    stmt = delete(EntityLink).where(EntityLink.id == link_id, EntityLink.user_id == user_id)
    await db.execute(stmt)
    await db.commit()
    resp = {"status": "ok"}
    await save_idempotency(user_id, request.state.idempotency_key, request.state.request_hash, 200, resp)
    return resp
    