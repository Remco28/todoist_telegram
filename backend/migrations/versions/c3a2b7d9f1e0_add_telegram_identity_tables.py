"""add_telegram_identity_tables

Revision ID: c3a2b7d9f1e0
Revises: 9c5f8f7f2a1b
Create Date: 2026-02-10 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3a2b7d9f1e0"
down_revision: Union[str, Sequence[str], None] = "9c5f8f7f2a1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telegram_user_map",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("chat_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("telegram_username", sa.String(), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("chat_id", name="uq_telegram_user_map_chat"),
    )
    op.create_index("idx_telegram_user_map_user", "telegram_user_map", ["user_id"], unique=False)

    op.create_table(
        "telegram_link_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_telegram_link_tokens_hash"),
    )
    op.create_index("idx_telegram_link_tokens_user", "telegram_link_tokens", ["user_id"], unique=False)
    op.create_index("idx_telegram_link_tokens_expires", "telegram_link_tokens", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_telegram_link_tokens_expires", table_name="telegram_link_tokens")
    op.drop_index("idx_telegram_link_tokens_user", table_name="telegram_link_tokens")
    op.drop_table("telegram_link_tokens")

    op.drop_index("idx_telegram_user_map_user", table_name="telegram_user_map")
    op.drop_table("telegram_user_map")
