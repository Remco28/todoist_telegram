from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

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

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from common.models import TaskStatus, GoalStatus, ProblemStatus, LinkType, EntityType

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[TaskStatus] = None
    priority: Optional[int] = Field(None, ge=1, le=4)
    due_date: Optional[str] = None
    notes: Optional[str] = None
    impact_score: Optional[int] = Field(None, ge=1, le=5)

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
