"""Tambah kolom soft delete ke tabel projects

Revision ID: 009
Revises: 008
Create Date: 2025-05-01 00:00:00.000000

Menambahkan deleted_at (waktu hapus) dan deleted_by (FK users.id) untuk soft
delete proyek. Hard delete sebelumnya selalu gagal karena documents,
activity_logs, dan sla_tracking mengacu ke projects tanpa ON DELETE CASCADE,
dan data tersebut (khususnya utilisasi SA) memang harus dipertahankan.

Kedua kolom nullable tanpa backfill — proyek lama tetap aktif (NULL).
Index parsial mempercepat query proyek aktif (filter deleted_at IS NULL).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifikasi revisi
revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Tambah deleted_at, deleted_by (+FK) dan index parsial proyek aktif."""
    op.add_column(
        "projects",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("deleted_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_projects_deleted_by",
        "projects",
        "users",
        ["deleted_by"],
        ["id"],
    )
    op.create_index(
        "idx_projects_active",
        "projects",
        ["updated_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    """
    Hapus index, FK, dan kolom soft delete.

    Peringatan: proyek yang sudah di-soft delete akan muncul kembali sebagai
    proyek aktif setelah downgrade.
    """
    op.drop_index("idx_projects_active", table_name="projects")
    op.drop_constraint("fk_projects_deleted_by", "projects", type_="foreignkey")
    op.drop_column("projects", "deleted_by")
    op.drop_column("projects", "deleted_at")
