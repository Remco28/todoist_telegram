from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)

from common.models import Base, entity_type_enum, link_type_enum


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


task_status_enum = Enum(TaskStatus, name="task_status")
goal_status_enum = Enum(GoalStatus, name="goal_status")
problem_status_enum = Enum(ProblemStatus, name="problem_status")


class Goal(Base):
    __tablename__ = "goals"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    title = Column(Text, nullable=False)
    title_norm = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(goal_status_enum, nullable=False, default=GoalStatus.active)
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
    status = Column(problem_status_enum, nullable=False, default=ProblemStatus.active)
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
    status = Column(task_status_enum, nullable=False, default=TaskStatus.open)
    priority = Column(SmallInteger, CheckConstraint("priority BETWEEN 1 AND 4"), nullable=True)
    impact_score = Column(SmallInteger, CheckConstraint("impact_score BETWEEN 1 AND 5"), nullable=True)
    urgency_score = Column(SmallInteger, CheckConstraint("urgency_score BETWEEN 1 AND 5"), nullable=True)
    due_date = Column(Date, nullable=True)
    source_inbox_item_id = Column(String, ForeignKey("inbox_items.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_tasks_user_status_due", "user_id", "status", "due_date"),
        Index("idx_tasks_user_title_norm", "user_id", "title_norm"),
        Index("idx_tasks_user_updated", "user_id", updated_at.desc()),
    )


class EntityLink(Base):
    __tablename__ = "entity_links"

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    from_entity_type = Column(entity_type_enum, nullable=False)
    from_entity_id = Column(String, nullable=False)
    to_entity_type = Column(entity_type_enum, nullable=False)
    to_entity_id = Column(String, nullable=False)
    link_type = Column(link_type_enum, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "from_entity_type",
            "from_entity_id",
            "to_entity_type",
            "to_entity_id",
            "link_type",
        ),
        Index("idx_entity_links_to", "user_id", "to_entity_type", "to_entity_id"),
    )
