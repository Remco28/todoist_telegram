"""add_todoist_task_map

Revision ID: 5d07b602df71
Revises: 5638dfedf9dc
Create Date: 2026-02-09 18:15:09.845226

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d07b602df71'
down_revision: Union[str, Sequence[str], None] = '5638dfedf9dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'todoist_task_map',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('local_task_id', sa.String(), nullable=False),
        sa.Column('todoist_task_id', sa.String(), nullable=True),
        sa.Column('sync_state', sa.String(), nullable=False, server_default='pending'),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['local_task_id'], ['tasks.id'], ),
        sa.UniqueConstraint('user_id', 'local_task_id', name='uq_todoist_map_local')
    )
    op.create_index('idx_todoist_map_remote_lookup', 'todoist_task_map', ['user_id', 'todoist_task_id'], unique=True)


def downgrade() -> None:
    op.drop_index('idx_todoist_map_remote_lookup', table_name='todoist_task_map')
    op.drop_table('todoist_task_map')
