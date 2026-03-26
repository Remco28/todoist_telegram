"""add_reminder_versions

Revision ID: 4d7a9c2e1b4f
Revises: 1f9d7c3a4b6e
Create Date: 2026-03-25 15:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4d7a9c2e1b4f"
down_revision: Union[str, Sequence[str], None] = "1f9d7c3a4b6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reminder_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("reminder_id", sa.String(), sa.ForeignKey("reminders.id"), nullable=False),
        sa.Column("action_batch_id", sa.String(), sa.ForeignKey("action_batches.id"), nullable=True),
        sa.Column("operation", sa.Enum(name="version_operation", create_type=False), nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("after_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_reminder_versions_item_created",
        "reminder_versions",
        ["reminder_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_reminder_versions_user_created",
        "reminder_versions",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_reminder_versions_user_created", table_name="reminder_versions")
    op.drop_index("idx_reminder_versions_item_created", table_name="reminder_versions")
    op.drop_table("reminder_versions")
