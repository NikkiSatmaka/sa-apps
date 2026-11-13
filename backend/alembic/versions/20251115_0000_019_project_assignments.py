"""project_assignments: SA tambahan per project (multi-SA)

Revision ID: 019
Revises: 018
Create Date: 2025-11-15 00:00:00.000000

Issue #119, ADR 0014. Tabel `project_assignments` menyimpan SA tambahan; SA utama tetap
`projects.assigned_sa` dan tidak diulang di sini. Unik pada (`id_project`, `user_id`).
Kewajiban role `SA`/`Lead_SA` ditegakkan di API (CHECK tidak bisa merujuk `users.role`).

Downgrade membuang tabel (lossy: daftar SA tambahan hilang).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Identifikasi revisi
revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_assignments",
        sa.Column("id", sa.UUID(), nullable=False, comment="Primary key UUID"),
        sa.Column("id_project", sa.String(length=50), nullable=False, comment="FK ke proyek"),
        sa.Column("user_id", sa.UUID(), nullable=False, comment="FK ke user SA tambahan"),
        sa.Column("added_by", sa.UUID(), nullable=False, comment="FK ke Lead_SA/Admin penambah"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="Waktu penambahan",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["id_project"],
            ["projects.id_project"],
            name="fk_project_assignments_id_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_project_assignments_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["added_by"], ["users.id"], name="fk_project_assignments_added_by"
        ),
        sa.UniqueConstraint("id_project", "user_id", name="uq_project_assignment"),
        comment="SA tambahan per proyek (hak setara SA utama; ADR 0014)",
    )


def downgrade() -> None:
    op.drop_table("project_assignments")
