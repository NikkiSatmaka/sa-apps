"""project_comments dan event notifikasi komentar

Revision ID: 023
Revises: 022
Create Date: 2026-02-01 00:00:00.000000

Issue #125, spec §2.5 dan A5.
- Tabel `project_comments` (thread komentar per proyek): PK `id_comment`, FK `id_project`
  (ON DELETE CASCADE), FK `author_id` ke users, `body` Text dengan CHECK tidak kosong
  (`chk_project_comments_body`), `created_at`. Indeks (`id_project`, `created_at`) untuk thread.
- CHECK `chk_notification_logs_event_type` diperluas dengan nilai `komentar`.

Downgrade membuang tabel (lossy: semua komentar hilang), menghapus baris notifikasi
`event_type = 'komentar'` (agar CHECK lama bisa dipasang kembali), lalu memulihkan CHECK lama.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EVENT_LAMA = "'assignment', 'status_change', 'sla_reminder', 'sla_escalation', 'handover', 'doc_ready'"
_EVENT_BARU = _EVENT_LAMA + ", 'komentar'"


def _ganti_check_event(daftar: str) -> None:
    op.drop_constraint("chk_notification_logs_event_type", "notification_logs", type_="check")
    op.create_check_constraint(
        "chk_notification_logs_event_type", "notification_logs", f"event_type IN ({daftar})"
    )


def upgrade() -> None:
    op.create_table(
        "project_comments",
        sa.Column("id_comment", sa.String(50), primary_key=True, comment="ID komentar (format CMT-YYYYMMDD-XXXXXX)"),
        sa.Column("id_project", sa.String(50), nullable=False, comment="FK ke proyek"),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False, comment="FK ke user penulis"),
        sa.Column("body", sa.Text(), nullable=False, comment="Isi komentar"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, comment="Waktu komentar ditulis"),
        sa.ForeignKeyConstraint(
            ["id_project"], ["projects.id_project"], name="fk_project_comments_project", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], name="fk_project_comments_author"),
        sa.CheckConstraint("body !~ '^\\s*$'", name="chk_project_comments_body"),
        comment="Komentar thread per proyek (append-only; terpisah dari Project Story)",
    )
    op.create_index(
        "idx_project_comments_project_created", "project_comments", ["id_project", "created_at"]
    )
    _ganti_check_event(_EVENT_BARU)


def downgrade() -> None:
    op.execute("DELETE FROM notification_logs WHERE event_type = 'komentar'")
    _ganti_check_event(_EVENT_LAMA)
    op.drop_index("idx_project_comments_project_created", table_name="project_comments")
    op.drop_table("project_comments")
