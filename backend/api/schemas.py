from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from common.models import TaskStatus, GoalStatus, ProblemStatus, LinkType, EntityType

class ThoughtCaptureRequest(BaseModel):
    chat_id: str
    message: str
    source: str
    client_msg_id: Optional[str] = None
    requested_mode: str = "auto"

class AppliedChanges(BaseModel):
    tasks_created: int = 0
    tasks_updated: int = 0
    problems_created: int = 0
    goals_created: int = 0
    links_created: int = 0

class ThoughtCaptureResponse(BaseModel):
    status: str
    inbox_item_id: str
    applied: AppliedChanges
    plan_refresh_enqueued: bool = False
    summary_refresh_enqueued: bool = False
    reason: Optional[str] = None

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[int] = Field(None, ge=1, le=4)
    due_date: Optional[str] = None
    notes: Optional[str] = None
    impact_score: Optional[int] = Field(None, ge=1, le=5)
    urgency_score: Optional[int] = Field(None, ge=1, le=5)

class GoalUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[GoalStatus] = None
    target_date: Optional[str] = None
    horizon: Optional[str] = None

class ProblemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[ProblemStatus] = None
    severity: Optional[int] = Field(None, ge=1, le=5)
    horizon: Optional[str] = None

class LinkCreate(BaseModel):
    from_entity_type: EntityType
    from_entity_id: str
    to_entity_type: EntityType
    to_entity_id: str
    link_type: LinkType

class PlanRefreshRequest(BaseModel):
    chat_id: str
    window: str = "today"

class PlanRefreshResponse(BaseModel):
    status: str
    enqueued: bool
    job_id: Optional[str] = None
    reason: Optional[str] = None

# --- Plan Response v1 ---

class PlanItem(BaseModel):
    task_id: str
    rank: int = Field(..., ge=1, le=999)
    title: str = Field(..., min_length=1, max_length=240)
    reason: Optional[str] = Field(None, max_length=240)
    score: Optional[float] = None
    estimated_minutes: Optional[int] = Field(None, ge=0, le=1440)

class BlockedItem(BaseModel):
    task_id: str
    title: str = Field(..., min_length=1, max_length=240)
    blocked_by: List[str] = Field(..., min_length=1, max_length=10)

class OrderReason(BaseModel):
    task_id: str
    factors: List[str] = Field(..., min_length=1, max_length=6)
    # Valid factors: overdue, due_soon, high_impact, goal_alignment, dependency_ready, stale, quick_win

class PlanResponseV1(BaseModel):
    schema_version: str = "plan.v1"
    plan_window: str = Field(..., pattern="^(today|this_week)$")
    generated_at: str # ISO datetime
    today_plan: List[PlanItem] = Field(..., max_length=20)
    next_actions: List[PlanItem] = Field(..., max_length=20)
    blocked_items: List[BlockedItem] = Field(..., max_length=20)
    why_this_order: Optional[List[OrderReason]] = Field(None, max_length=20)
    assumptions: Optional[List[str]] = Field(None, max_length=10)

# --- Query Response v1 ---

class Citation(BaseModel):
    entity_type: str = Field(..., pattern="^(task|problem|goal|summary|inbox_item)$")
    entity_id: str
    label: Optional[str] = Field(None, max_length=120)

class SuggestedAction(BaseModel):
    kind: str = Field(..., pattern="^(ask_clarification|refresh_plan|create_task|update_task|link_entities)$")
    description: str = Field(..., min_length=1, max_length=240)
    payload: Optional[Dict[str, Any]] = None

class QueryAskRequest(BaseModel):
    chat_id: str
    query: str
    max_tokens: Optional[int] = None

class QueryResponseV1(BaseModel):

    schema_version: str = "query.v1"

    mode: str = "query"

    answer: str = Field(..., min_length=1, max_length=4000)

    confidence: float = Field(..., ge=0, le=1)

    highlights: Optional[List[str]] = Field(None, max_length=8)

    citations: Optional[List[Citation]] = Field(None, max_length=30)

    suggested_actions: Optional[List[SuggestedAction]] = Field(None, max_length=6)

    surfaced_entity_ids: Optional[List[str]] = Field(None, max_length=30)

    follow_up_question: Optional[str] = Field(None, max_length=240)



# --- Telegram Webhook ---



class TelegramUpdateEnvelope(BaseModel):

    update_id: int

    message: Optional[Dict[str, Any]] = None

    edited_message: Optional[Dict[str, Any]] = None



class TelegramWebhookResponse(BaseModel):



    status: str = "ok"


class TelegramLinkTokenCreateResponse(BaseModel):
    link_token: str
    expires_at: datetime
    deep_link: Optional[str] = None







# --- Phase 5 Todoist Sync ---







class TodoistSyncStatusResponse(BaseModel):







    total_mapped: int







    pending_sync: int







    error_count: int







    last_synced_at: Optional[str] = None







    last_attempt_at: Optional[str] = None
    last_reconcile_at: Optional[str] = None
    reconcile_error_count: int = 0








