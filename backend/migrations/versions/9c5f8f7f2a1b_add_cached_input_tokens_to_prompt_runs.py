"""add_cached_input_tokens_to_prompt_runs

Revision ID: 9c5f8f7f2a1b
Revises: 5d07b602df71
Create Date: 2026-02-10 03:13:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c5f8f7f2a1b"
down_revision: Union[str, Sequence[str], None] = "5d07b602df71"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("prompt_runs", sa.Column("cached_input_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("prompt_runs", "cached_input_tokens")

