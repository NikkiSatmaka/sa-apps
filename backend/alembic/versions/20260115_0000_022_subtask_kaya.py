"""subtasks: description, due_date, estimate_hours

Revision ID: 022
Revises: 021
Create Date: 2026-01-15 00:00:00.000000

Issue #124, spec §2.5 dan A4. Subtask menjadi work item yang lebih kaya:
- `description` (Text, NULL): uraian pekerjaan.
- `due_date` (Date, NULL): batas waktu; dasar penanda "terlambat" di daftar subtask.
- `estimate_hours` (Numeric(7,2), NULL): estimasi jam, dengan CHECK tidak negatif
  (`chk_subtasks_estimate_hours`; NULL lolos CHECK karena berarti "belum diestimasi").

Ketiganya nullable tanpa default, jadi baris lama dan seeding subtask template tetap valid.
Downgrade membuang ketiga kolom beserta constraint (lossy: isi kolom hilang).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subtasks",
        sa.Column("description", sa.Text(), nullable=True, comment="Uraian pekerjaan (opsional)"),
    )
    op.add_column(
        "subtasks",
        sa.Column("due_date", sa.Date(), nullable=True, comment="Batas waktu subtask (opsional)"),
    )
    op.add_column(
        "subtasks",
        sa.Column(
            "estimate_hours",
            sa.Numeric(7, 2),
            nullable=True,
            comment="Estimasi jam pengerjaan, >= 0 (opsional)",
        ),
    )
    op.create_check_constraint(
        "chk_subtasks_estimate_hours",
        "subtasks",
        "estimate_hours IS NULL OR estimate_hours >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("chk_subtasks_estimate_hours", "subtasks", type_="check")
    op.drop_column("subtasks", "estimate_hours")
    op.drop_column("subtasks", "due_date")
    op.drop_column("subtasks", "description")
