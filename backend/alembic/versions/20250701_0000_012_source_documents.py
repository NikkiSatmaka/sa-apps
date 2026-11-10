"""Tambah tabel source_documents (Source document MoM/RFP)

Revision ID: 012
Revises: 011
Create Date: 2025-07-01 00:00:00.000000

Menyimpan teks hasil ekstraksi LLM untuk file MoM/RFP yang di-upload Sales saat intake.
File asli tidak disimpan. Revision 011 dipakai tiket #28 (paralel); down_revision "011"
sengaja menunggu merge integration branch.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifikasi revisi
revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Buat tabel source_documents."""
    op.create_table(
        "source_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "id_project",
            sa.String(50),
            sa.ForeignKey("projects.id_project", ondelete="CASCADE"),
            nullable=False,
            comment="FK ke proyek pemilik",
        ),
        sa.Column("filename", sa.String(255), nullable=False, comment="Nama file asli"),
        sa.Column("doc_type", sa.String(10), nullable=False, comment="MoM atau RFP"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, comment="Ukuran file asli"),
        sa.Column(
            "extraction_status",
            sa.String(10),
            nullable=False,
            server_default="pending",
            comment="pending/extracted/empty/failed",
        ),
        sa.Column("extracted_text", sa.Text(), nullable=True, comment="Teks hasil ekstraksi LLM"),
        sa.Column(
            "truncated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Respons LLM berhenti karena batas token",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("doc_type IN ('MoM', 'RFP')", name="chk_source_documents_doc_type"),
        sa.CheckConstraint(
            "extraction_status IN ('pending', 'extracted', 'empty', 'failed')",
            name="chk_source_documents_status",
        ),
        comment="Source document (MoM/RFP) — teks hasil ekstraksi per proyek",
    )
    op.create_index("idx_source_documents_project", "source_documents", ["id_project"])


def downgrade() -> None:
    """Hapus tabel source_documents."""
    op.drop_index("idx_source_documents_project", table_name="source_documents")
    op.drop_table("source_documents")
