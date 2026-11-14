"""sla_tracking: kolom jeda untuk status On Hold

Revision ID: 021
Revises: 020
Create Date: 2026-01-01 00:00:00.000000

Issue #122, ADR 0013. Timer SLA DQ berhenti selama proyek `On Hold` dan lanjut sesudahnya:
- `paused_at` (NULL): waktu jeda yang sedang berjalan; NULL berarti tidak sedang dijeda.
- `paused_total_seconds` (0): akumulasi detik jeda yang sudah selesai (dikurangkan dari waktu
  berjalan), dengan CHECK tidak negatif.

Baris lama tetap valid (tidak sedang dijeda, akumulasi 0). Downgrade membuang kedua kolom
(lossy: riwayat jeda hilang; tracker yang sedang dijeda kembali menghitung waktu jeda).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sla_tracking",
        sa.Column(
            "paused_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Waktu jeda On Hold yang sedang berjalan (NULL = tidak dijeda)",
        ),
    )
    op.add_column(
        "sla_tracking",
        sa.Column(
            "paused_total_seconds",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Akumulasi detik jeda On Hold yang sudah selesai",
        ),
    )
    op.create_check_constraint(
        "chk_sla_tracking_paused_total_seconds",
        "sla_tracking",
        "paused_total_seconds >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("chk_sla_tracking_paused_total_seconds", "sla_tracking", type_="check")
    op.drop_column("sla_tracking", "paused_total_seconds")
    op.drop_column("sla_tracking", "paused_at")
