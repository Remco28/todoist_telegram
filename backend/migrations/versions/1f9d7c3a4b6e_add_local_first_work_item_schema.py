"""add_local_first_work_item_schema

Revision ID: 1f9d7c3a4b6e
Revises: f2b6c1d9a4e7
Create Date: 2026-03-25 11:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "1f9d7c3a4b6e"
down_revision: Union[str, Sequence[str], None] = "f2b6c1d9a4e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE entity_type ADD VALUE IF NOT EXISTS 'work_item'")

    work_item_kind_enum = postgresql.ENUM("project", "task", "subtask", name="work_item_kind", create_type=False)
    work_item_status_enum = postgresql.ENUM(
        "open", "blocked", "done", "archived", name="work_item_status", create_type=False
    )
    work_item_link_type_enum = postgresql.ENUM(
        "blocks", "depends_on", "related_to", "part_of", name="work_item_link_type", create_type=False
    )
    work_item_person_role_enum = postgresql.ENUM(
        "owner", "waiting_on", "collaborator", "mentioned", name="work_item_person_role", create_type=False
    )
    reminder_kind_enum = postgresql.ENUM("one_off", "follow_up", "recurring", name="reminder_kind", create_type=False)
    reminder_status_enum = postgresql.ENUM(
        "pending", "sent", "completed", "dismissed", "canceled", name="reminder_status", create_type=False
    )
    plan_snapshot_type_enum = postgresql.ENUM(
        "today", "urgent", "daily_brief", "weekly_review", name="plan_snapshot_type", create_type=False
    )
    conversation_source_enum = postgresql.ENUM(
        "telegram", "web", "system", name="conversation_source", create_type=False
    )
    conversation_direction_enum = postgresql.ENUM(
        "inbound", "outbound", "system", name="conversation_direction", create_type=False
    )
    action_batch_status_enum = postgresql.ENUM(
        "applied", "reverted", "failed", name="action_batch_status", create_type=False
    )
    version_operation_enum = postgresql.ENUM(
        "create", "update", "complete", "archive", "restore", "reparent", "reminder",
        name="version_operation",
        create_type=False,
    )

    work_item_kind_enum.create(op.get_bind(), checkfirst=True)
    work_item_status_enum.create(op.get_bind(), checkfirst=True)
    work_item_link_type_enum.create(op.get_bind(), checkfirst=True)
    work_item_person_role_enum.create(op.get_bind(), checkfirst=True)
    reminder_kind_enum.create(op.get_bind(), checkfirst=True)
    reminder_status_enum.create(op.get_bind(), checkfirst=True)
    plan_snapshot_type_enum.create(op.get_bind(), checkfirst=True)
    conversation_source_enum.create(op.get_bind(), checkfirst=True)
    conversation_direction_enum.create(op.get_bind(), checkfirst=True)
    action_batch_status_enum.create(op.get_bind(), checkfirst=True)
    version_operation_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "areas",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_norm", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "name_norm", name="uq_areas_user_name_norm"),
    )
    op.create_index("idx_areas_user_name_norm", "areas", ["user_id", "name_norm"])

    op.create_table(
        "people",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_norm", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "name_norm", name="uq_people_user_name_norm"),
    )
    op.create_index("idx_people_user_name_norm", "people", ["user_id", "name_norm"])

    op.create_table(
        "work_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("kind", work_item_kind_enum, nullable=False),
        sa.Column("parent_id", sa.String(), sa.ForeignKey("work_items.id"), nullable=True),
        sa.Column("area_id", sa.String(), sa.ForeignKey("areas.id"), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_norm", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", work_item_status_enum, nullable=False, server_default="open"),
        sa.Column("priority", sa.SmallInteger(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("priority BETWEEN 1 AND 4", name="check_work_items_priority"),
        sa.CheckConstraint("estimated_minutes > 0", name="check_work_items_estimated_minutes"),
    )
    op.create_index("idx_work_items_user_kind_status", "work_items", ["user_id", "kind", "status"])
    op.create_index("idx_work_items_user_title_norm", "work_items", ["user_id", "title_norm"])
    op.create_index("idx_work_items_user_status_due", "work_items", ["user_id", "status", "due_at"])
    op.create_index("idx_work_items_user_parent", "work_items", ["user_id", "parent_id"])
    op.create_index("idx_work_items_user_updated", "work_items", ["user_id", sa.text("updated_at DESC")])

    op.create_table(
        "work_item_aliases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("work_item_id", sa.String(), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("alias_norm", sa.Text(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="user"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="check_work_item_aliases_confidence"),
        sa.UniqueConstraint("user_id", "work_item_id", "alias_norm", name="uq_work_item_aliases_item_alias"),
    )
    op.create_index("idx_work_item_aliases_user_alias_norm", "work_item_aliases", ["user_id", "alias_norm"])

    op.create_table(
        "work_item_links",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("from_work_item_id", sa.String(), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("to_work_item_id", sa.String(), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("link_type", work_item_link_type_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "from_work_item_id", "to_work_item_id", "link_type",
            name="uq_work_item_links_user_from_to_type",
        ),
    )
    op.create_index("idx_work_item_links_user_to", "work_item_links", ["user_id", "to_work_item_id"])

    op.create_table(
        "work_item_people",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("work_item_id", sa.String(), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("person_id", sa.String(), sa.ForeignKey("people.id"), nullable=False),
        sa.Column("role", work_item_person_role_enum, nullable=False, server_default="mentioned"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "work_item_id", "person_id", "role",
            name="uq_work_item_people_user_item_person_role",
        ),
    )
    op.create_index("idx_work_item_people_user_person", "work_item_people", ["user_id", "person_id"])

    op.create_table(
        "conversation_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("chat_id", sa.String(), nullable=True),
        sa.Column("source", conversation_source_enum, nullable=False, server_default="telegram"),
        sa.Column("direction", conversation_direction_enum, nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_conversation_events_user_created", "conversation_events", ["user_id", sa.text("created_at DESC")])
    op.create_index(
        "idx_conversation_events_user_chat_created",
        "conversation_events",
        ["user_id", "chat_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "action_batches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("conversation_event_id", sa.String(), sa.ForeignKey("conversation_events.id"), nullable=True),
        sa.Column("source_message", sa.Text(), nullable=False),
        sa.Column("status", action_batch_status_enum, nullable=False, server_default="applied"),
        sa.Column("proposal_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("applied_item_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("before_summary", sa.Text(), nullable=True),
        sa.Column("after_summary", sa.Text(), nullable=True),
        sa.Column("undo_window_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_action_batches_user_created", "action_batches", ["user_id", sa.text("created_at DESC")])
    op.create_index("idx_action_batches_user_status", "action_batches", ["user_id", "status"])

    op.create_table(
        "work_item_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("work_item_id", sa.String(), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("action_batch_id", sa.String(), sa.ForeignKey("action_batches.id"), nullable=True),
        sa.Column("operation", version_operation_enum, nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("after_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_work_item_versions_item_created", "work_item_versions", ["work_item_id", sa.text("created_at DESC")])
    op.create_index("idx_work_item_versions_user_created", "work_item_versions", ["user_id", sa.text("created_at DESC")])

    op.create_table(
        "reminders",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("work_item_id", sa.String(), sa.ForeignKey("work_items.id"), nullable=True),
        sa.Column("person_id", sa.String(), sa.ForeignKey("people.id"), nullable=True),
        sa.Column("kind", reminder_kind_enum, nullable=False, server_default="one_off"),
        sa.Column("status", reminder_status_enum, nullable=False, server_default="pending"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recurrence_rule", sa.Text(), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_reminders_user_status_remind_at", "reminders", ["user_id", "status", "remind_at"])
    op.create_index("idx_reminders_user_work_item", "reminders", ["user_id", "work_item_id"])

    op.create_table(
        "plan_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("snapshot_type", plan_snapshot_type_enum, nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("item_ids_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_plan_snapshots_user_type_generated",
        "plan_snapshots",
        ["user_id", "snapshot_type", sa.text("generated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_plan_snapshots_user_type_generated", table_name="plan_snapshots")
    op.drop_table("plan_snapshots")

    op.drop_index("idx_reminders_user_work_item", table_name="reminders")
    op.drop_index("idx_reminders_user_status_remind_at", table_name="reminders")
    op.drop_table("reminders")

    op.drop_index("idx_work_item_versions_user_created", table_name="work_item_versions")
    op.drop_index("idx_work_item_versions_item_created", table_name="work_item_versions")
    op.drop_table("work_item_versions")

    op.drop_index("idx_action_batches_user_status", table_name="action_batches")
    op.drop_index("idx_action_batches_user_created", table_name="action_batches")
    op.drop_table("action_batches")

    op.drop_index("idx_conversation_events_user_chat_created", table_name="conversation_events")
    op.drop_index("idx_conversation_events_user_created", table_name="conversation_events")
    op.drop_table("conversation_events")

    op.drop_index("idx_work_item_people_user_person", table_name="work_item_people")
    op.drop_table("work_item_people")

    op.drop_index("idx_work_item_links_user_to", table_name="work_item_links")
    op.drop_table("work_item_links")

    op.drop_index("idx_work_item_aliases_user_alias_norm", table_name="work_item_aliases")
    op.drop_table("work_item_aliases")

    op.drop_index("idx_work_items_user_updated", table_name="work_items")
    op.drop_index("idx_work_items_user_parent", table_name="work_items")
    op.drop_index("idx_work_items_user_status_due", table_name="work_items")
    op.drop_index("idx_work_items_user_title_norm", table_name="work_items")
    op.drop_index("idx_work_items_user_kind_status", table_name="work_items")
    op.drop_table("work_items")

    op.drop_index("idx_people_user_name_norm", table_name="people")
    op.drop_table("people")

    op.drop_index("idx_areas_user_name_norm", table_name="areas")
    op.drop_table("areas")

    version_operation_enum = postgresql.ENUM(name="version_operation")
    action_batch_status_enum = postgresql.ENUM(name="action_batch_status")
    conversation_direction_enum = postgresql.ENUM(name="conversation_direction")
    conversation_source_enum = postgresql.ENUM(name="conversation_source")
    plan_snapshot_type_enum = postgresql.ENUM(name="plan_snapshot_type")
    reminder_status_enum = postgresql.ENUM(name="reminder_status")
    reminder_kind_enum = postgresql.ENUM(name="reminder_kind")
    work_item_person_role_enum = postgresql.ENUM(name="work_item_person_role")
    work_item_link_type_enum = postgresql.ENUM(name="work_item_link_type")
    work_item_status_enum = postgresql.ENUM(name="work_item_status")
    work_item_kind_enum = postgresql.ENUM(name="work_item_kind")

    version_operation_enum.drop(op.get_bind(), checkfirst=True)
    action_batch_status_enum.drop(op.get_bind(), checkfirst=True)
    conversation_direction_enum.drop(op.get_bind(), checkfirst=True)
    conversation_source_enum.drop(op.get_bind(), checkfirst=True)
    plan_snapshot_type_enum.drop(op.get_bind(), checkfirst=True)
    reminder_status_enum.drop(op.get_bind(), checkfirst=True)
    reminder_kind_enum.drop(op.get_bind(), checkfirst=True)
    work_item_person_role_enum.drop(op.get_bind(), checkfirst=True)
    work_item_link_type_enum.drop(op.get_bind(), checkfirst=True)
    work_item_status_enum.drop(op.get_bind(), checkfirst=True)
    work_item_kind_enum.drop(op.get_bind(), checkfirst=True)
