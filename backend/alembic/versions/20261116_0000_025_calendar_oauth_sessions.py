"""Store short-lived Google Calendar access tokens in encrypted user sessions.

Revision ID: 025
Revises: 024
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calendar_oauth_sessions",
        sa.Column("session_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_calendar_oauth_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "length(session_hash) = 64", name="chk_calendar_oauth_sessions_hash"
        ),
    )
    op.create_index(
        "ix_calendar_oauth_sessions_user_id", "calendar_oauth_sessions", ["user_id"]
    )
    op.create_index(
        "ix_calendar_oauth_sessions_expires_at", "calendar_oauth_sessions", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_calendar_oauth_sessions_expires_at", table_name="calendar_oauth_sessions"
    )
    op.drop_index("ix_calendar_oauth_sessions_user_id", table_name="calendar_oauth_sessions")
    op.drop_table("calendar_oauth_sessions")
