"""Sesi refresh berotasi dan handoff OAuth sekali pakai.

Revision ID: 024
Revises: 023
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("jti_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("jti_hash", name="uq_auth_refresh_tokens_jti"),
        sa.CheckConstraint(
            "status IN ('active', 'consumed', 'revoked')",
            name="chk_auth_refresh_tokens_status",
        ),
    )
    op.create_index("ix_auth_refresh_tokens_family_id", "auth_refresh_tokens", ["family_id"])
    op.create_index(
        "ix_auth_refresh_tokens_family_status",
        "auth_refresh_tokens",
        ["family_id", "status"],
    )
    op.create_table(
        "auth_handoffs",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("encrypted_value", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("purpose IN ('login', 'calendar')", name="chk_auth_handoffs_purpose"),
    )
    op.create_index("ix_auth_handoffs_expires_at", "auth_handoffs", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_handoffs_expires_at", table_name="auth_handoffs")
    op.drop_table("auth_handoffs")
    op.drop_index("ix_auth_refresh_tokens_family_status", table_name="auth_refresh_tokens")
    op.drop_index("ix_auth_refresh_tokens_family_id", table_name="auth_refresh_tokens")
    op.drop_table("auth_refresh_tokens")
