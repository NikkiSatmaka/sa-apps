"""Tambah kolom ai_scoring_result ke tabel projects

Revision ID: 011
Revises: 010
Create Date: 2025-07-01 00:00:00.000000

Menyimpan hasil analisis AI terakhir atas file (sub-skor + use_case_tags) terpisah dari
skor rubrik. Skor akhir per kriteria adalah max(rubrik, AI) dan disimpan di bant_detail
(ADR 0010). Kolom nullable tanpa backfill — proyek tanpa analisis AI tetap NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifikasi revisi
revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Tambah projects.ai_scoring_result."""
    op.add_column(
        "projects",
        sa.Column(
            "ai_scoring_result",
            postgresql.JSONB(),
            nullable=True,
            comment="Hasil analisis AI terakhir atas file (sub_scores, use_case_tags), terpisah dari rubrik",
        ),
    )


def downgrade() -> None:
    """Hapus kolom ai_scoring_result."""
    op.drop_column("projects", "ai_scoring_result")
