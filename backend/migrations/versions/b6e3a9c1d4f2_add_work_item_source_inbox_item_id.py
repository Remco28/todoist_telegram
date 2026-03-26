"""add work item source inbox item id

Revision ID: b6e3a9c1d4f2
Revises: 8c2d1e4f5a6b
Create Date: 2026-03-25 20:35:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6e3a9c1d4f2"
down_revision: Union[str, Sequence[str], None] = "8c2d1e4f5a6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_items",
        sa.Column("source_inbox_item_id", sa.String(), sa.ForeignKey("inbox_items.id"), nullable=True),
    )
    op.create_index(
        "idx_work_items_user_source_inbox",
        "work_items",
        ["user_id", "source_inbox_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_work_items_user_source_inbox", table_name="work_items")
    op.drop_column("work_items", "source_inbox_item_id")
