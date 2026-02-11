"""add_action_drafts

Revision ID: e8f1a7c9d2b4
Revises: c3a2b7d9f1e0
Create Date: 2026-02-11 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e8f1a7c9d2b4"
down_revision: Union[str, Sequence[str], None] = "c3a2b7d9f1e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "action_drafts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("source_inbox_item_id", sa.String(), sa.ForeignKey("inbox_items.id"), nullable=True),
        sa.Column("source_message", sa.Text(), nullable=False),
        sa.Column(
            "proposal_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft','confirmed','discarded','expired')", name="ck_action_drafts_status"),
    )
    op.create_index("idx_action_drafts_user_chat_status", "action_drafts", ["user_id", "chat_id", "status"], unique=False)
    op.create_index("idx_action_drafts_expires", "action_drafts", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_action_drafts_expires", table_name="action_drafts")
    op.drop_index("idx_action_drafts_user_chat_status", table_name="action_drafts")
    op.drop_table("action_drafts")
