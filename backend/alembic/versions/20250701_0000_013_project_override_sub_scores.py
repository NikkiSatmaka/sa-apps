"""Tambah kolom override_sub_scores ke tabel projects

Revision ID: 013
Revises: 012
Create Date: 2025-07-01 00:00:00.000000

Menyimpan sub-skor override Lead SA/Admin terpisah dari rubrik dan hasil AI (#41).
Override menjadi batas bawah: skor akhir per kriteria = max(rubrik, AI, override).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifikasi revisi
revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Tambah projects.override_sub_scores."""
    op.add_column(
        "projects",
        sa.Column(
            "override_sub_scores",
            postgresql.JSONB(),
            nullable=True,
            comment="Sub-skor override Lead SA/Admin (batas bawah skor akhir), terpisah dari rubrik dan AI",
        ),
    )


def downgrade() -> None:
    """Hapus kolom override_sub_scores."""
    op.drop_column("projects", "override_sub_scores")
