"""add session state fields

Revision ID: c4f2d9e1a7b3
Revises: b6e3a9c1d4f2
Create Date: 2026-03-25 23:35:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "c4f2d9e1a7b3"
down_revision = "b6e3a9c1d4f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("current_mode", sa.String(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column(
            "active_entity_refs_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column("sessions", sa.Column("pending_draft_id", sa.String(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column(
            "pending_clarification_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "summary_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "summary_metadata_json")
    op.drop_column("sessions", "pending_clarification_json")
    op.drop_column("sessions", "pending_draft_id")
    op.drop_column("sessions", "active_entity_refs_json")
    op.drop_column("sessions", "current_mode")
