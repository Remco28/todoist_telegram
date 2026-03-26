"""add_work_item_attributes_json

Revision ID: 7a1c9e4d2f3b
Revises: 4d7a9c2e1b4f
Create Date: 2026-03-25 17:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7a1c9e4d2f3b"
down_revision: Union[str, Sequence[str], None] = "4d7a9c2e1b4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_items",
        sa.Column("attributes_json", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("work_items", "attributes_json")
