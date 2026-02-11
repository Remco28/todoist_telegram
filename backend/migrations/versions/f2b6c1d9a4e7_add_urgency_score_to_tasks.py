"""add_urgency_score_to_tasks

Revision ID: f2b6c1d9a4e7
Revises: e8f1a7c9d2b4
Create Date: 2026-02-11 19:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2b6c1d9a4e7"
down_revision: Union[str, Sequence[str], None] = "e8f1a7c9d2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("urgency_score", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "check_tasks_urgency_score",
        "tasks",
        "urgency_score BETWEEN 1 AND 5",
    )


def downgrade() -> None:
    op.drop_constraint("check_tasks_urgency_score", "tasks", type_="check")
    op.drop_column("tasks", "urgency_score")

