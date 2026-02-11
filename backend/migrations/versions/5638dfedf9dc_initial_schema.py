"""initial_schema

Revision ID: 5638dfedf9dc
Revises: 
Create Date: 2026-02-06 00:10:13.683048

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '5638dfedf9dc'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enums ---
    # Let SQLAlchemy create enum types when referenced by tables.
    task_status_enum = postgresql.ENUM('open', 'blocked', 'done', 'archived', name='task_status')
    goal_status_enum = postgresql.ENUM('active', 'paused', 'done', 'archived', name='goal_status')
    problem_status_enum = postgresql.ENUM('active', 'monitoring', 'resolved', 'archived', name='problem_status')
    link_type_enum = postgresql.ENUM('depends_on', 'blocks', 'supports_goal', 'related', 'addresses_problem', name='link_type')
    entity_type_enum = postgresql.ENUM('task', 'goal', 'problem', name='entity_type')

    # --- Tables ---

    # sessions
    op.create_table(
        'sessions',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('chat_id', sa.String(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('user_id', 'chat_id', 'started_at', name='uq_sessions_user_chat_started')
    )
    op.create_index('idx_sessions_user_chat_activity', 'sessions', ['user_id', 'chat_id', sa.text('last_activity_at DESC')])

    # inbox_items
    op.create_table(
        'inbox_items',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('chat_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), sa.ForeignKey('sessions.id'), nullable=True),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('client_msg_id', sa.String(), nullable=True),
        sa.Column('message_raw', sa.Text(), nullable=False),
        sa.Column('message_norm', sa.Text(), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('source', 'client_msg_id', name='uq_source_client_msg_id')
    )
    op.create_index('idx_inbox_items_user_received', 'inbox_items', ['user_id', sa.text('received_at DESC')])

    # goals
    op.create_table(
        'goals',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('title_norm', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', goal_status_enum, nullable=False, server_default='active'),
        sa.Column('horizon', sa.Text(), nullable=True),
        sa.Column('target_date', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index('idx_goals_user_status', 'goals', ['user_id', 'status'])
    op.create_index('idx_goals_user_title_norm', 'goals', ['user_id', 'title_norm'])

    # problems
    op.create_table(
        'problems',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('title_norm', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', problem_status_enum, nullable=False, server_default='active'),
        sa.Column('severity', sa.SmallInteger(), nullable=True),
        sa.Column('horizon', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('severity BETWEEN 1 AND 5', name='check_problems_severity')
    )
    op.create_index('idx_problems_user_status', 'problems', ['user_id', 'status'])
    op.create_index('idx_problems_user_title_norm', 'problems', ['user_id', 'title_norm'])

    # tasks
    op.create_table(
        'tasks',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('title_norm', sa.Text(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', task_status_enum, nullable=False, server_default='open'),
        sa.Column('priority', sa.SmallInteger(), nullable=True),
        sa.Column('impact_score', sa.SmallInteger(), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('source_inbox_item_id', sa.String(), sa.ForeignKey('inbox_items.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('priority BETWEEN 1 AND 4', name='check_tasks_priority'),
        sa.CheckConstraint('impact_score BETWEEN 1 AND 5', name='check_tasks_impact_score')
    )
    op.create_index('idx_tasks_user_status_due', 'tasks', ['user_id', 'status', 'due_date'])
    op.create_index('idx_tasks_user_title_norm', 'tasks', ['user_id', 'title_norm'])
    op.create_index('idx_tasks_user_updated', 'tasks', ['user_id', sa.text('updated_at DESC')])

    # entity_links
    op.create_table(
        'entity_links',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('from_entity_type', entity_type_enum, nullable=False),
        sa.Column('from_entity_id', sa.String(), nullable=False),
        sa.Column('to_entity_type', entity_type_enum, nullable=False),
        sa.Column('to_entity_id', sa.String(), nullable=False),
        sa.Column('link_type', link_type_enum, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'from_entity_type', 'from_entity_id', 'to_entity_type', 'to_entity_id', 'link_type', name='uq_entity_links')
    )
    op.create_index('idx_entity_links_to', 'entity_links', ['user_id', 'to_entity_type', 'to_entity_id'])

    # memory_summaries
    op.create_table(
        'memory_summaries',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('chat_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), sa.ForeignKey('sessions.id'), nullable=True),
        sa.Column('summary_type', sa.String(), nullable=False),
        sa.Column('summary_text', sa.Text(), nullable=False),
        sa.Column('facts_json', sa.dialects.postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('source_event_ids', sa.dialects.postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("summary_type IN ('session', 'daily', 'weekly')", name='check_summary_type')
    )
    op.create_index('idx_memory_summaries_user_chat_created', 'memory_summaries', ['user_id', 'chat_id', sa.text('created_at DESC')])

    # recent_context_items
    op.create_table(
        'recent_context_items',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('chat_id', sa.String(), nullable=False),
        sa.Column('entity_type', entity_type_enum, nullable=False),
        sa.Column('entity_id', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('surfaced_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('idx_recent_context_user_chat_surfaced', 'recent_context_items', ['user_id', 'chat_id', sa.text('surfaced_at DESC')])
    op.create_index('idx_recent_context_expires', 'recent_context_items', ['expires_at'])

    # prompt_runs
    op.create_table(
        'prompt_runs',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('request_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('operation', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('prompt_version', sa.String(), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('error_code', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('idx_prompt_runs_user_op_created', 'prompt_runs', ['user_id', 'operation', sa.text('created_at DESC')])

    # event_log
    op.create_table(
        'event_log',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('request_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=True),
        sa.Column('entity_id', sa.String(), nullable=True),
        sa.Column('payload_json', sa.dialects.postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False)
    )
    op.create_index('idx_event_log_request', 'event_log', ['request_id'])
    op.create_index('idx_event_log_user_created', 'event_log', ['user_id', sa.text('created_at DESC')])

    # idempotency_keys
    op.create_table(
        'idempotency_keys',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('idempotency_key', sa.String(), nullable=False),
        sa.Column('request_hash', sa.String(), nullable=False),
        sa.Column('response_status', sa.Integer(), nullable=False),
        sa.Column('response_body', sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_idempotency_user_key')
    )
    op.create_index('idx_idempotency_keys_expires', 'idempotency_keys', ['expires_at'])


def downgrade() -> None:
    op.drop_table('idempotency_keys')
    op.drop_table('event_log')
    op.drop_table('prompt_runs')
    op.drop_table('recent_context_items')
    op.drop_table('memory_summaries')
    op.drop_table('entity_links')
    op.drop_table('tasks')
    op.drop_table('problems')
    op.drop_table('goals')
    op.drop_table('inbox_items')
    op.drop_table('sessions')

    op.execute("DROP TYPE entity_type")
    op.execute("DROP TYPE link_type")
    op.execute("DROP TYPE problem_status")
    op.execute("DROP TYPE goal_status")
    op.execute("DROP TYPE task_status")
