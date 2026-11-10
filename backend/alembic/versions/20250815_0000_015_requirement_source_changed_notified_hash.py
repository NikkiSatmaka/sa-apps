"""Tambah documents.source_changed_notified_hash (notifikasi sumber berubah sekali per hash)

Revision ID: 015
Revises: 014
Create Date: 2025-08-15 00:00:00.000000

Fase 5B (#37). Menyimpan hash sumber basi terakhir yang sudah diberitahukan ke SA agar
notifikasi "sumber Requirement berubah" tidak terkirim ganda untuk hash yang sama.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Identifikasi revisi
revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "source_changed_notified_hash",
            sa.String(length=64),
            nullable=True,
            comment="Hash sumber basi terakhir yang sudah diberitahukan (notifikasi sekali per hash)",
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "source_changed_notified_hash")
