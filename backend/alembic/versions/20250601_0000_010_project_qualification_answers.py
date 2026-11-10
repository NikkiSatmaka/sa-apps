"""Tambah kolom jawaban Kuesioner kualifikasi ke tabel projects

Revision ID: 010
Revises: 009
Create Date: 2025-06-01 00:00:00.000000

Menambahkan qualification_answers (JSONB) dan qualification_schema_version
(Integer) untuk menyimpan jawaban Kuesioner kualifikasi bersama versi skemanya.
Skor BANT dihitung backend dari jawaban ini (ADR 0010).

Kedua kolom nullable tanpa backfill — proyek lama tetap NULL dan ditampilkan
sebagai data BANT legacy.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifikasi revisi
revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Tambah qualification_answers dan qualification_schema_version."""
    op.add_column(
        "projects",
        sa.Column(
            "qualification_answers",
            postgresql.JSONB(),
            nullable=True,
            comment="Jawaban Kuesioner kualifikasi (NULL = proyek lama / legacy)",
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "qualification_schema_version",
            sa.Integer(),
            nullable=True,
            comment="Versi skema kuesioner pada saat jawaban disimpan",
        ),
    )


def downgrade() -> None:
    """Hapus kolom jawaban kuesioner."""
    op.drop_column("projects", "qualification_schema_version")
    op.drop_column("projects", "qualification_answers")
