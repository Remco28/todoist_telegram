from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from common.models import (
    LinkType,
    EntityType,
    WorkItemKind,
    WorkItemStatus,
    ReminderKind,
    ReminderStatus,
)

class ThoughtCaptureRequest(BaseModel):
    chat_id: str
    message: str
    source: str
    client_msg_id: Optional[str] = None
    requested_mode: str = "auto"

class AppliedChangeItem(BaseModel):
    group: str = Field(..., min_length=1, max_length=40)
    label: str = Field(..., min_length=1, max_length=240)

class AppliedChanges(BaseModel):
    tasks_created: int = 0
    tasks_updated: int = 0
    reminders_created: int = 0
    reminders_updated: int = 0
    problems_created: int = 0
    goals_created: int = 0
    links_created: int = 0
    items: List[AppliedChangeItem] = Field(default_factory=list, max_length=40)
    work_item_action_batch_id: Optional[str] = None
    reminder_action_batch_id: Optional[str] = None
    work_item_subtasks_count: int = 0

class ThoughtCaptureResponse(BaseModel):
    status: str
    inbox_item_id: str
    applied: AppliedChanges
    plan_refresh_enqueued: bool = False
    summary_refresh_enqueued: bool = False
    reason: Optional[str] = None

class WorkItemCreate(BaseModel):
    kind: WorkItemKind
    title: str = Field(..., min_length=1, max_length=240)
    parent_id: Optional[str] = None
    area_id: Optional[str] = None
    notes: Optional[str] = None
    status: WorkItemStatus = WorkItemStatus.open
    priority: Optional[int] = Field(None, ge=1, le=4)
    due_at: Optional[str] = None
    scheduled_for: Optional[str] = None
    snooze_until: Optional[str] = None
    estimated_minutes: Optional[int] = Field(None, ge=1, le=1440)


class WorkItemUpdate(BaseModel):
    kind: Optional[WorkItemKind] = None
    title: Optional[str] = None
    parent_id: Optional[str] = None
    area_id: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[WorkItemStatus] = None
    priority: Optional[int] = Field(None, ge=1, le=4)
    due_at: Optional[str] = None
    scheduled_for: Optional[str] = None
    snooze_until: Optional[str] = None
    estimated_minutes: Optional[int] = Field(None, ge=1, le=1440)


class ReminderCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=240)
    remind_at: str = Field(..., min_length=1, max_length=80)
    kind: ReminderKind = ReminderKind.one_off
    status: ReminderStatus = ReminderStatus.pending
    message: Optional[str] = None
    work_item_id: Optional[str] = None
    person_id: Optional[str] = None
    recurrence_rule: Optional[str] = None


class ReminderUpdate(BaseModel):
    title: Optional[str] = None
    remind_at: Optional[str] = None
    kind: Optional[ReminderKind] = None
    status: Optional[ReminderStatus] = None
    message: Optional[str] = None
    work_item_id: Optional[str] = None
    person_id: Optional[str] = None
    recurrence_rule: Optional[str] = None


class ReminderSnoozeRequest(BaseModel):
    preset: str = Field(..., min_length=1, max_length=40)

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


class ReminderPlanItem(BaseModel):
    reminder_id: str
    title: str = Field(..., min_length=1, max_length=240)
    remind_at: str
    message: Optional[str] = Field(None, max_length=500)
    work_item_id: Optional[str] = None

class PlanResponseV1(BaseModel):
    schema_version: str = "plan.v1"
    plan_window: str = Field(..., pattern="^(today|this_week)$")
    generated_at: str # ISO datetime
    today_plan: List[PlanItem] = Field(..., max_length=20)
    next_actions: List[PlanItem] = Field(..., max_length=20)
    blocked_items: List[BlockedItem] = Field(..., max_length=20)
    due_reminders: Optional[List[ReminderPlanItem]] = Field(None, max_length=20)
    why_this_order: Optional[List[OrderReason]] = Field(None, max_length=20)
    assumptions: Optional[List[str]] = Field(None, max_length=10)

# --- Query Response v1 ---

class Citation(BaseModel):
    entity_type: str = Field(..., pattern="^(task|problem|goal|reminder|summary|inbox_item)$")
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
