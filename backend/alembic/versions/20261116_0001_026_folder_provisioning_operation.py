"""Persist Drive folder provisioning attempts and outcomes.

Revision ID: 026
Revises: 025
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("folder_provisioning_operation", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "folder_provisioning_operation")
