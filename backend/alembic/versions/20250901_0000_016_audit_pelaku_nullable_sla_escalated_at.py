"""audit_logs.performed_by nullable + sla_tracking.escalated_at

Revision ID: 016
Revises: 015
Create Date: 2025-09-01 00:00:00.000000

Issue #77.
- `audit_logs.performed_by` boleh NULL: aksi otomatis (lock/unlock SLA oleh cron) tidak punya
  user pelaku. Sebelumnya dipakai UUID nol yang tidak ada di `users`, sehingga FK menolak insert
  dan audit lock/unlock tidak pernah tertulis. Tidak ada user sistem palsu: ia akan ikut jadi
  penerima eskalasi Admin.
- `sla_tracking.escalated_at`: kapan eskalasi H+5 dikirim, agar tidak dikirim ulang tiap siklus
  cron saat lock Drive terus gagal.

Downgrade: baris audit tanpa pelaku (aksi otomatis) dibuang karena kolom kembali NOT NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identifikasi revisi
revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "audit_logs",
        "performed_by",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
        existing_comment="FK ke user yang melakukan aksi",
        comment="FK ke user yang melakukan aksi (NULL untuk aksi otomatis sistem)",
    )
    op.add_column(
        "sla_tracking",
        sa.Column(
            "escalated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Waktu eskalasi H+5 dikirim (sekali per tracker)",
        ),
    )


def downgrade() -> None:
    op.drop_column("sla_tracking", "escalated_at")
    op.execute("DELETE FROM audit_logs WHERE performed_by IS NULL")
    op.alter_column(
        "audit_logs",
        "performed_by",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
        existing_comment="FK ke user yang melakukan aksi (NULL untuk aksi otomatis sistem)",
        comment="FK ke user yang melakukan aksi",
    )
