"""Perluas documents untuk Requirement turunan AI + status generate di projects

Revision ID: 014
Revises: 013
Create Date: 2025-08-01 00:00:00.000000

Fase 5B (#33). Requirement adalah konten turunan AI, bukan file Drive:
- documents: kolom content (JSONB), is_overridden, source_hash, generated_at,
  source_truncated.
- documents.gdrive_link dan documents.created_by menjadi nullable, dibatasi CHECK agar
  hanya doc_type 'Requirement' yang boleh kosong.
- Unique partial index: satu Requirement per proyek.
- projects.requirement_generation_status (pending/ready/failed, nullable).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifikasi revisi
revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Tambah kolom Requirement, longgarkan gdrive_link/created_by, tambah index unik."""
    op.add_column(
        "documents",
        sa.Column(
            "content",
            postgresql.JSONB(),
            nullable=True,
            comment="Daftar butir Requirement [{id, kategori, butir}] (hanya Requirement)",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "is_overridden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="True bila konten sudah diedit manual (tidak lagi murni hasil AI)",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "source_hash",
            sa.String(length=64),
            nullable=True,
            comment="SHA-256 sumber (jawaban kuesioner + teks Source document extracted) saat generate",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Waktu generate AI terakhir",
        ),
    )
    op.add_column(
        "documents",
        sa.Column(
            "source_truncated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="True bila teks sumber terpotong saat generate",
        ),
    )

    op.alter_column("documents", "gdrive_link", existing_type=sa.Text(), nullable=True)
    op.alter_column(
        "documents", "created_by", existing_type=postgresql.UUID(as_uuid=True), nullable=True
    )
    op.create_check_constraint(
        "chk_documents_gdrive_link_required",
        "documents",
        "gdrive_link IS NOT NULL OR doc_type = 'Requirement'",
    )
    op.create_check_constraint(
        "chk_documents_created_by_required",
        "documents",
        "created_by IS NOT NULL OR doc_type = 'Requirement'",
    )
    op.create_index(
        "uq_documents_requirement_per_project",
        "documents",
        ["id_project"],
        unique=True,
        postgresql_where=sa.text("doc_type = 'Requirement'"),
    )

    op.add_column(
        "projects",
        sa.Column(
            "requirement_generation_status",
            sa.String(length=10),
            nullable=True,
            comment="Status generate Requirement otomatis: pending/ready/failed (NULL = belum pernah lolos gate)",
        ),
    )
    op.create_check_constraint(
        "chk_projects_requirement_generation_status",
        "projects",
        "requirement_generation_status IS NULL OR "
        "requirement_generation_status IN ('pending','ready','failed')",
    )


def downgrade() -> None:
    """
    Kembalikan skema ke 013.

    Baris Requirement (konten turunan, tanpa link/pembuat) dihapus lebih dulu karena
    tidak bisa memenuhi NOT NULL gdrive_link/created_by; dokumen jenis lain tidak tersentuh.
    """
    op.drop_constraint("chk_projects_requirement_generation_status", "projects", type_="check")
    op.drop_column("projects", "requirement_generation_status")

    op.drop_index("uq_documents_requirement_per_project", table_name="documents")
    op.drop_constraint("chk_documents_created_by_required", "documents", type_="check")
    op.drop_constraint("chk_documents_gdrive_link_required", "documents", type_="check")

    op.execute(
        "DELETE FROM documents WHERE doc_type = 'Requirement' "
        "AND (gdrive_link IS NULL OR created_by IS NULL)"
    )
    op.alter_column(
        "documents", "created_by", existing_type=postgresql.UUID(as_uuid=True), nullable=False
    )
    op.alter_column("documents", "gdrive_link", existing_type=sa.Text(), nullable=False)

    op.drop_column("documents", "source_truncated")
    op.drop_column("documents", "generated_at")
    op.drop_column("documents", "source_hash")
    op.drop_column("documents", "is_overridden")
    op.drop_column("documents", "content")
