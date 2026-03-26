from datetime import datetime, date
from typing import List, Optional
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, ForeignKey,
    Index, UniqueConstraint, SmallInteger, CheckConstraint, Enum,
    Float, JSON
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# --- Enums ---

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
    work_item = "work_item"
    reminder = "reminder"


class WorkItemKind(PyEnum):
    project = "project"
    task = "task"
    subtask = "subtask"


class WorkItemStatus(PyEnum):
    open = "open"
    blocked = "blocked"
    done = "done"
    archived = "archived"


class WorkItemLinkType(PyEnum):
    blocks = "blocks"
    depends_on = "depends_on"
    related_to = "related_to"
    part_of = "part_of"


class WorkItemPersonRole(PyEnum):
    owner = "owner"
    waiting_on = "waiting_on"
    collaborator = "collaborator"
    mentioned = "mentioned"


class ReminderKind(PyEnum):
    one_off = "one_off"
    follow_up = "follow_up"
    recurring = "recurring"


class ReminderStatus(PyEnum):
    pending = "pending"
    sent = "sent"
    completed = "completed"
    dismissed = "dismissed"
    canceled = "canceled"


class PlanSnapshotType(PyEnum):
    today = "today"
    urgent = "urgent"
    daily_brief = "daily_brief"
    weekly_review = "weekly_review"


class ConversationSource(PyEnum):
    telegram = "telegram"
    web = "web"
    system = "system"


class ConversationDirection(PyEnum):
    inbound = "inbound"
    outbound = "outbound"
    system = "system"


class ActionBatchStatus(PyEnum):
    applied = "applied"
    reverted = "reverted"
    failed = "failed"


class VersionOperation(PyEnum):
    create = "create"
    update = "update"
    complete = "complete"
    archive = "archive"
    restore = "restore"
    reparent = "reparent"
    reminder = "reminder"


link_type_enum = Enum(LinkType, name="link_type")
entity_type_enum = Enum(EntityType, name="entity_type")
work_item_kind_enum = Enum(WorkItemKind, name="work_item_kind")
work_item_status_enum = Enum(WorkItemStatus, name="work_item_status")
work_item_link_type_enum = Enum(WorkItemLinkType, name="work_item_link_type")
work_item_person_role_enum = Enum(WorkItemPersonRole, name="work_item_person_role")
reminder_kind_enum = Enum(ReminderKind, name="reminder_kind")
reminder_status_enum = Enum(ReminderStatus, name="reminder_status")
plan_snapshot_type_enum = Enum(PlanSnapshotType, name="plan_snapshot_type")
conversation_source_enum = Enum(ConversationSource, name="conversation_source")
conversation_direction_enum = Enum(ConversationDirection, name="conversation_direction")
action_batch_status_enum = Enum(ActionBatchStatus, name="action_batch_status")
version_operation_enum = Enum(VersionOperation, name="version_operation")

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
    __table_args__ = (
        UniqueConstraint("source", "client_msg_id", name="uq_source_client_msg_id"),
        Index("idx_inbox_items_user_received", "user_id", received_at.desc()),
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
    entity_type = Column(entity_type_enum, nullable=False)
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
    cached_input_tokens = Column(Integer, nullable=True)
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

class TelegramUserMap(Base):
    __tablename__ = "telegram_user_map"

    id = Column(String, primary_key=True)
    chat_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    telegram_username = Column(String, nullable=True)
    linked_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("chat_id", name="uq_telegram_user_map_chat"),
        Index("idx_telegram_user_map_user", "user_id"),
    )


class TelegramLinkToken(Base):
    __tablename__ = "telegram_link_tokens"

    id = Column(String, primary_key=True)
    token_hash = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_telegram_link_tokens_hash"),
        Index("idx_telegram_link_tokens_user", "user_id"),
        Index("idx_telegram_link_tokens_expires", "expires_at"),
    )


class ActionDraft(Base):
    __tablename__ = "action_drafts"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    chat_id = Column(String, nullable=False)
    source_inbox_item_id = Column(String, ForeignKey("inbox_items.id"), nullable=True)
    source_message = Column(Text, nullable=False)
    proposal_json = Column(JSONB, nullable=False, server_default='{}')
    status = Column(
        String,
        CheckConstraint("status IN ('draft','confirmed','discarded','expired')"),
        nullable=False,
        default="draft",
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_action_drafts_user_chat_status", "user_id", "chat_id", "status"),
        Index("idx_action_drafts_expires", "expires_at"),
    )


class Area(Base):
    __tablename__ = "areas"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    name = Column(Text, nullable=False)
    name_norm = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    work_items = relationship("WorkItem", back_populates="area")

    __table_args__ = (
        UniqueConstraint("user_id", "name_norm", name="uq_areas_user_name_norm"),
        Index("idx_areas_user_name_norm", "user_id", "name_norm"),
    )


class Person(Base):
    __tablename__ = "people"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    name = Column(Text, nullable=False)
    name_norm = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    work_item_links = relationship("WorkItemPersonLink", back_populates="person")
    reminders = relationship("Reminder", back_populates="person")

    __table_args__ = (
        UniqueConstraint("user_id", "name_norm", name="uq_people_user_name_norm"),
        Index("idx_people_user_name_norm", "user_id", "name_norm"),
    )


class WorkItem(Base):
    __tablename__ = "work_items"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    kind = Column(work_item_kind_enum, nullable=False)
    parent_id = Column(String, ForeignKey("work_items.id"), nullable=True)
    area_id = Column(String, ForeignKey("areas.id"), nullable=True)
    title = Column(Text, nullable=False)
    title_norm = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    attributes_json = Column(JSON, nullable=False, default=dict, server_default="{}")
    status = Column(work_item_status_enum, nullable=False, default=WorkItemStatus.open)
    priority = Column(SmallInteger, CheckConstraint("priority BETWEEN 1 AND 4"), nullable=True)
    due_at = Column(DateTime(timezone=True), nullable=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    snooze_until = Column(DateTime(timezone=True), nullable=True)
    estimated_minutes = Column(Integer, CheckConstraint("estimated_minutes > 0"), nullable=True)
    source_inbox_item_id = Column(String, ForeignKey("inbox_items.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    parent = relationship("WorkItem", remote_side=[id], back_populates="children")
    children = relationship("WorkItem", back_populates="parent")
    area = relationship("Area", back_populates="work_items")
    aliases = relationship("WorkItemAlias", back_populates="work_item")
    outgoing_links = relationship(
        "WorkItemLink",
        foreign_keys="WorkItemLink.from_work_item_id",
        back_populates="from_work_item",
    )
    incoming_links = relationship(
        "WorkItemLink",
        foreign_keys="WorkItemLink.to_work_item_id",
        back_populates="to_work_item",
    )
    people = relationship("WorkItemPersonLink", back_populates="work_item")
    reminders = relationship("Reminder", back_populates="work_item")
    versions = relationship("WorkItemVersion", back_populates="work_item")

    __table_args__ = (
        Index("idx_work_items_user_kind_status", "user_id", "kind", "status"),
        Index("idx_work_items_user_title_norm", "user_id", "title_norm"),
        Index("idx_work_items_user_status_due", "user_id", "status", "due_at"),
        Index("idx_work_items_user_parent", "user_id", "parent_id"),
        Index("idx_work_items_user_source_inbox", "user_id", "source_inbox_item_id"),
        Index("idx_work_items_user_updated", "user_id", updated_at.desc()),
    )


class WorkItemAlias(Base):
    __tablename__ = "work_item_aliases"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    work_item_id = Column(String, ForeignKey("work_items.id"), nullable=False)
    alias = Column(Text, nullable=False)
    alias_norm = Column(Text, nullable=False)
    source = Column(String, nullable=False, default="user")
    confidence = Column(Float, CheckConstraint("confidence >= 0 AND confidence <= 1"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    work_item = relationship("WorkItem", back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("user_id", "work_item_id", "alias_norm", name="uq_work_item_aliases_item_alias"),
        Index("idx_work_item_aliases_user_alias_norm", "user_id", "alias_norm"),
    )


class WorkItemLink(Base):
    __tablename__ = "work_item_links"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    from_work_item_id = Column(String, ForeignKey("work_items.id"), nullable=False)
    to_work_item_id = Column(String, ForeignKey("work_items.id"), nullable=False)
    link_type = Column(work_item_link_type_enum, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    from_work_item = relationship(
        "WorkItem",
        foreign_keys=[from_work_item_id],
        back_populates="outgoing_links",
    )
    to_work_item = relationship(
        "WorkItem",
        foreign_keys=[to_work_item_id],
        back_populates="incoming_links",
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "from_work_item_id",
            "to_work_item_id",
            "link_type",
            name="uq_work_item_links_user_from_to_type",
        ),
        Index("idx_work_item_links_user_to", "user_id", "to_work_item_id"),
    )


class WorkItemPersonLink(Base):
    __tablename__ = "work_item_people"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    work_item_id = Column(String, ForeignKey("work_items.id"), nullable=False)
    person_id = Column(String, ForeignKey("people.id"), nullable=False)
    role = Column(work_item_person_role_enum, nullable=False, default=WorkItemPersonRole.mentioned)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    work_item = relationship("WorkItem", back_populates="people")
    person = relationship("Person", back_populates="work_item_links")

    __table_args__ = (
        UniqueConstraint("user_id", "work_item_id", "person_id", "role", name="uq_work_item_people_user_item_person_role"),
        Index("idx_work_item_people_user_person", "user_id", "person_id"),
    )


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    work_item_id = Column(String, ForeignKey("work_items.id"), nullable=True)
    person_id = Column(String, ForeignKey("people.id"), nullable=True)
    kind = Column(reminder_kind_enum, nullable=False, default=ReminderKind.one_off)
    status = Column(reminder_status_enum, nullable=False, default=ReminderStatus.pending)
    title = Column(Text, nullable=False)
    message = Column(Text, nullable=True)
    remind_at = Column(DateTime(timezone=True), nullable=False)
    recurrence_rule = Column(Text, nullable=True)
    last_sent_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    dismissed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    work_item = relationship("WorkItem", back_populates="reminders")
    person = relationship("Person", back_populates="reminders")
    versions = relationship("ReminderVersion", back_populates="reminder")

    __table_args__ = (
        Index("idx_reminders_user_status_remind_at", "user_id", "status", "remind_at"),
        Index("idx_reminders_user_work_item", "user_id", "work_item_id"),
    )


class PlanSnapshot(Base):
    __tablename__ = "plan_snapshots"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    snapshot_type = Column(plan_snapshot_type_enum, nullable=False)
    summary_text = Column(Text, nullable=True)
    item_ids_json = Column(JSON, nullable=False, server_default="[]")
    payload_json = Column(JSON, nullable=False, server_default="{}")
    generated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_plan_snapshots_user_type_generated", "user_id", "snapshot_type", generated_at.desc()),
    )


class ConversationEvent(Base):
    __tablename__ = "conversation_events"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    chat_id = Column(String, nullable=True)
    source = Column(conversation_source_enum, nullable=False, default=ConversationSource.telegram)
    direction = Column(conversation_direction_enum, nullable=False)
    content_text = Column(Text, nullable=False)
    normalized_text = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=False, server_default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    action_batches = relationship("ActionBatch", back_populates="conversation_event")

    __table_args__ = (
        Index("idx_conversation_events_user_created", "user_id", created_at.desc()),
        Index("idx_conversation_events_user_chat_created", "user_id", "chat_id", created_at.desc()),
    )


class ActionBatch(Base):
    __tablename__ = "action_batches"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    conversation_event_id = Column(String, ForeignKey("conversation_events.id"), nullable=True)
    source_message = Column(Text, nullable=False)
    status = Column(action_batch_status_enum, nullable=False, default=ActionBatchStatus.applied)
    proposal_json = Column(JSON, nullable=False, server_default="{}")
    applied_item_ids_json = Column(JSON, nullable=False, server_default="[]")
    before_summary = Column(Text, nullable=True)
    after_summary = Column(Text, nullable=True)
    undo_window_expires_at = Column(DateTime(timezone=True), nullable=True)
    reverted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    conversation_event = relationship("ConversationEvent", back_populates="action_batches")
    versions = relationship("WorkItemVersion", back_populates="action_batch")
    reminder_versions = relationship("ReminderVersion", back_populates="action_batch")

    __table_args__ = (
        Index("idx_action_batches_user_created", "user_id", created_at.desc()),
        Index("idx_action_batches_user_status", "user_id", "status"),
    )


class WorkItemVersion(Base):
    __tablename__ = "work_item_versions"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    work_item_id = Column(String, ForeignKey("work_items.id"), nullable=False)
    action_batch_id = Column(String, ForeignKey("action_batches.id"), nullable=True)
    operation = Column(version_operation_enum, nullable=False)
    before_json = Column(JSON, nullable=False, server_default="{}")
    after_json = Column(JSON, nullable=False, server_default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    work_item = relationship("WorkItem", back_populates="versions")
    action_batch = relationship("ActionBatch", back_populates="versions")

    __table_args__ = (
        Index("idx_work_item_versions_item_created", "work_item_id", created_at.desc()),
        Index("idx_work_item_versions_user_created", "user_id", created_at.desc()),
    )


class ReminderVersion(Base):
    __tablename__ = "reminder_versions"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    reminder_id = Column(String, ForeignKey("reminders.id"), nullable=False)
    action_batch_id = Column(String, ForeignKey("action_batches.id"), nullable=True)
    operation = Column(version_operation_enum, nullable=False)
    before_json = Column(JSON, nullable=False, server_default="{}")
    after_json = Column(JSON, nullable=False, server_default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    reminder = relationship("Reminder", back_populates="versions")
    action_batch = relationship("ActionBatch", back_populates="reminder_versions")

    __table_args__ = (
        Index("idx_reminder_versions_item_created", "reminder_id", created_at.desc()),
        Index("idx_reminder_versions_user_created", "user_id", created_at.desc()),
    )
