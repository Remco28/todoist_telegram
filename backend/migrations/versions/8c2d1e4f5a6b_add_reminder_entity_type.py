"""add_reminder_entity_type

Revision ID: 8c2d1e4f5a6b
Revises: 7a1c9e4d2f3b
Create Date: 2026-03-25 15:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "8c2d1e4f5a6b"
down_revision: Union[str, Sequence[str], None] = "7a1c9e4d2f3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE entity_type ADD VALUE IF NOT EXISTS 'reminder'")


def downgrade() -> None:
    # PostgreSQL enum value removal is intentionally left as a no-op.
    pass
