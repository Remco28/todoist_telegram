from datetime import datetime, date
from typing import List, Optional
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, ForeignKey, 
    Index, UniqueConstraint, SmallInteger, CheckConstraint, Enum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()

# --- Enums ---

class TaskStatus(PyEnum):
    open = "open"
    blocked = "blocked"
    done = "done"
    archived = "archived"

class GoalStatus(PyEnum):
    active = "active"
    paused = "paused"
    done = "done"
    archived = "archived"

class ProblemStatus(PyEnum):
    active = "active"
    monitoring = "monitoring"
    resolved = "resolved"
    archived = "archived"

class LinkType(PyEnum):
    depends_on = "depends_on"
    blocks = "blocks"
    supports_goal = "supports_goal"
    related = "related"
    addresses_problem = "addresses_problem"

class EntityType(PyEnum):
    task = "task"
    goal = "goal"
    problem = "problem"

# --- Models ---

class Session(Base):
    __tablename__ = "sessions"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    chat_id = Column(String, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    last_activity_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    ended_at = Column(DateTime(timezone=True), nullable=True)

    inbox_items = relationship("InboxItem", back_populates="session")
    summaries = relationship("MemorySummary", back_populates="session")

    __table_args__ = (
        UniqueConstraint("user_id", "chat_id", "started_at"),
        Index("idx_sessions_user_chat_activity", "user_id", "chat_id", last_activity_at.desc()),
    )

class InboxItem(Base):
    __tablename__ = "inbox_items"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    chat_id = Column(String, nullable=False)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=True)
    source = Column(String, nullable=False)
    client_msg_id = Column(String, nullable=True)
    message_raw = Column(Text, nullable=False)
    message_norm = Column(Text, nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    session = relationship("Session", back_populates="inbox_items")
    tasks = relationship("Task", back_populates="source_inbox_item")

    __table_args__ = (
        UniqueConstraint("source", "client_msg_id", name="uq_source_client_msg_id"),
        Index("idx_inbox_items_user_received", "user_id", received_at.desc()),
    )

class Goal(Base):
    __tablename__ = "goals"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    title = Column(Text, nullable=False)
    title_norm = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(GoalStatus), nullable=False, default=GoalStatus.active)
    horizon = Column(Text, nullable=True)
    target_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_goals_user_status", "user_id", "status"),
        Index("idx_goals_user_title_norm", "user_id", "title_norm"),
    )

class Problem(Base):
    __tablename__ = "problems"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    title = Column(Text, nullable=False)
    title_norm = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(ProblemStatus), nullable=False, default=ProblemStatus.active)
    severity = Column(SmallInteger, CheckConstraint("severity BETWEEN 1 AND 5"), nullable=True)
    horizon = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_problems_user_status", "user_id", "status"),
        Index("idx_problems_user_title_norm", "user_id", "title_norm"),
    )

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    title = Column(Text, nullable=False)
    title_norm = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    status = Column(Enum(TaskStatus), nullable=False, default=TaskStatus.open)
    priority = Column(SmallInteger, CheckConstraint("priority BETWEEN 1 AND 4"), nullable=True)
    impact_score = Column(SmallInteger, CheckConstraint("impact_score BETWEEN 1 AND 5"), nullable=True)
    due_date = Column(Date, nullable=True)
    source_inbox_item_id = Column(String, ForeignKey("inbox_items.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    source_inbox_item = relationship("InboxItem", back_populates="tasks")

    __table_args__ = (
        Index("idx_tasks_user_status_due", "user_id", "status", "due_date"),
        Index("idx_tasks_user_title_norm", "user_id", "title_norm"),
        Index("idx_tasks_user_updated", "user_id", updated_at.desc()),
    )

class EntityLink(Base):
    __tablename__ = "entity_links"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    from_entity_type = Column(Enum(EntityType), nullable=False)
    from_entity_id = Column(String, nullable=False)
    to_entity_type = Column(Enum(EntityType), nullable=False)
    to_entity_id = Column(String, nullable=False)
    link_type = Column(Enum(LinkType), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "from_entity_type", "from_entity_id", "to_entity_type", "to_entity_id", "link_type"),
        Index("idx_entity_links_to", "user_id", "to_entity_type", "to_entity_id"),
    )

class MemorySummary(Base):
    __tablename__ = "memory_summaries"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    chat_id = Column(String, nullable=False)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=True)
    summary_type = Column(String, CheckConstraint("summary_type IN ('session', 'daily', 'weekly')"), nullable=False)
    summary_text = Column(Text, nullable=False)
    facts_json = Column(JSONB, nullable=False, server_default='{}')
    source_event_ids = Column(JSONB, nullable=False, server_default='[]')
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    session = relationship("Session", back_populates="summaries")

    __table_args__ = (
        Index("idx_memory_summaries_user_chat_created", "user_id", "chat_id", created_at.desc()),
    )

class RecentContextItem(Base):
    __tablename__ = "recent_context_items"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    chat_id = Column(String, nullable=False)
    entity_type = Column(Enum(EntityType), nullable=False)
    entity_id = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    surfaced_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_recent_context_user_chat_surfaced", "user_id", "chat_id", surfaced_at.desc()),
        Index("idx_recent_context_expires", "expires_at"),
    )

class PromptRun(Base):
    __tablename__ = "prompt_runs"
    
    id = Column(String, primary_key=True)
    request_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    operation = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    prompt_version = Column(String, nullable=False)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    status = Column(String, nullable=False)
    error_code = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_prompt_runs_user_op_created", "user_id", "operation", created_at.desc()),
    )

class EventLog(Base):
    __tablename__ = "event_log"
    
    id = Column(String, primary_key=True)
    request_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    entity_type = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)
    payload_json = Column(JSONB, nullable=False, server_default='{}')
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_event_log_request", "request_id"),
        Index("idx_event_log_user_created", "user_id", created_at.desc()),
    )

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    idempotency_key = Column(String, nullable=False)
    request_hash = Column(String, nullable=False)
    response_status = Column(Integer, nullable=False)
    response_body = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_idempotency_user_key"),
        Index("idx_idempotency_keys_expires", "expires_at"),
    )

class TodoistTaskMap(Base):
    __tablename__ = "todoist_task_map"
    
    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    local_task_id = Column(String, ForeignKey("tasks.id"), nullable=False)
    todoist_task_id = Column(String, nullable=True)
    sync_state = Column(String, nullable=False, default="pending") # pending|synced|error
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "local_task_id", name="uq_todoist_map_local"),
        # We can't have a unique constraint on nullable todoist_task_id easily if multiple are null
        # but for TodoistTaskMap we only ever want one mapping per local_task_id anyway.
        # Actually, the spec said unique index on (user_id, todoist_task_id).
        # In Postgres, unique index allows multiple nulls.
        Index("idx_todoist_map_remote_lookup", "user_id", "todoist_task_id", unique=True),
    )
