"""status dua field: enum status baru, qualification_state, previous_status, lost_reason

Revision ID: 020
Revises: 019
Create Date: 2025-12-01 00:00:00.000000

Issue #121, ADR 0013 (menggantikan ADR 0001).
- `projects.status` memakai enum siklus kerja baru: Intake, Awaiting Assignment, Assigned,
  In Progress, Submitted, Won, Handed Over, Closed, ditambah status samping Lost dan On Hold.
- `projects.qualification_state` (NOT NULL, default `Scoring`): Scoring, Need Clarification,
  Manual Review, Qualified. Hanya bermakna saat `status = Intake`; selanjutnya `Qualified`.
- `projects.previous_status` (NULL): status sebelum On Hold atau Lost.
- `projects.lost_reason` (NULL): wajib saat `status = Lost` (CHECK).

Pemetaan data (satu langkah; tidak ada data produksi):
  New / Scoring Pending        → Intake + Scoring
  Need Clarification           → Intake + Need Clarification
  Manual Review Required       → Intake + Manual Review
  Pending Assignment           → Awaiting Assignment + Qualified
  Assigned                     → Assigned + Qualified
  Ready                        → Submitted + Qualified
  Closed-Win                   → Won + Qualified
  Handover Complete            → Handed Over + Qualified
  Lost                         → Lost + Qualified, `lost_reason` diisi teks pengganti karena
                                 alasan asli tidak pernah tercatat (syarat CHECK); tahap asal
                                 tidak diketahui sehingga `previous_status` dibiarkan NULL.

Downgrade (lossy): kolom baru dibuang. Pemetaan balik: Intake+Scoring → Scoring Pending,
Intake+Need Clarification → Need Clarification, Intake+Manual Review → Manual Review Required,
Awaiting Assignment → Pending Assignment, In Progress → Assigned, Submitted → Ready,
Won → Closed-Win, Handed Over dan Closed → Handover Complete, On Hold → pemetaan dari
`previous_status` (tanpa riwayat: Pending Assignment). `Lost` tetap `Lost`; alasan hilang.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# Identifikasi revisi
revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Daftar nilai ditulis literal (bukan impor dari app) agar migration tidak berubah bila
# konstanta aplikasi berubah di kemudian hari.
STATUS_BARU = (
    "Intake",
    "Awaiting Assignment",
    "Assigned",
    "In Progress",
    "Submitted",
    "Won",
    "Handed Over",
    "Closed",
    "Lost",
    "On Hold",
)
STATUS_LAMA = (
    "New",
    "Pending Assignment",
    "Assigned",
    "Ready",
    "Closed-Win",
    "Handover Complete",
    "Lost",
    "Need Clarification",
    "Scoring Pending",
    "Manual Review Required",
)
SIKLUS_UTAMA = STATUS_BARU[:8]
QUALIFICATION_STATE = ("Scoring", "Need Clarification", "Manual Review", "Qualified")

ALASAN_LOST_MIGRASI = "Dimigrasi dari status Lost lama; alasan asli tidak tercatat."


def _daftar(nilai: tuple[str, ...]) -> str:
    return ", ".join(f"'{n}'" for n in nilai)


def upgrade() -> None:
    op.drop_constraint("chk_projects_status", "projects", type_="check")

    op.add_column(
        "projects",
        sa.Column(
            "qualification_state",
            sa.String(30),
            nullable=False,
            server_default="Scoring",
            comment="Gate kualifikasi; bermakna saat status Intake, selanjutnya Qualified",
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "previous_status",
            sa.String(30),
            nullable=True,
            comment="Status sebelum On Hold atau Lost; dipakai saat lanjut atau dibuka kembali",
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "lost_reason",
            sa.Text(),
            nullable=True,
            comment="Alasan proyek Lost (wajib saat status Lost)",
        ),
    )

    # Satu UPDATE: semua ekspresi SET membaca nilai `status` LAMA.
    op.execute(
        sa.text(
            """
            UPDATE projects SET
              qualification_state = CASE status
                WHEN 'New' THEN 'Scoring'
                WHEN 'Scoring Pending' THEN 'Scoring'
                WHEN 'Need Clarification' THEN 'Need Clarification'
                WHEN 'Manual Review Required' THEN 'Manual Review'
                ELSE 'Qualified'
              END,
              lost_reason = CASE WHEN status = 'Lost' THEN :alasan ELSE NULL END,
              status = CASE status
                WHEN 'New' THEN 'Intake'
                WHEN 'Scoring Pending' THEN 'Intake'
                WHEN 'Need Clarification' THEN 'Intake'
                WHEN 'Manual Review Required' THEN 'Intake'
                WHEN 'Pending Assignment' THEN 'Awaiting Assignment'
                WHEN 'Ready' THEN 'Submitted'
                WHEN 'Closed-Win' THEN 'Won'
                WHEN 'Handover Complete' THEN 'Handed Over'
                ELSE status
              END
            """
        ).bindparams(alasan=ALASAN_LOST_MIGRASI)
    )

    op.alter_column("projects", "status", server_default="Intake")

    op.create_check_constraint(
        "chk_projects_status", "projects", f"status IN ({_daftar(STATUS_BARU)})"
    )
    op.create_check_constraint(
        "chk_projects_qualification_state",
        "projects",
        f"qualification_state IN ({_daftar(QUALIFICATION_STATE)})",
    )
    op.create_check_constraint(
        "chk_projects_previous_status",
        "projects",
        f"previous_status IS NULL OR previous_status IN ({_daftar(SIKLUS_UTAMA)})",
    )
    op.create_check_constraint(
        "chk_projects_lost_reason",
        "projects",
        "status <> 'Lost' OR (lost_reason IS NOT NULL AND btrim(lost_reason) <> '')",
    )


def downgrade() -> None:
    for nama in (
        "chk_projects_lost_reason",
        "chk_projects_previous_status",
        "chk_projects_qualification_state",
        "chk_projects_status",
    ):
        op.drop_constraint(nama, "projects", type_="check")

    op.execute(
        """
        UPDATE projects SET status = CASE status
          WHEN 'Intake' THEN CASE qualification_state
            WHEN 'Scoring' THEN 'Scoring Pending'
            WHEN 'Need Clarification' THEN 'Need Clarification'
            WHEN 'Manual Review' THEN 'Manual Review Required'
            ELSE 'Pending Assignment'
          END
          WHEN 'Awaiting Assignment' THEN 'Pending Assignment'
          WHEN 'In Progress' THEN 'Assigned'
          WHEN 'Submitted' THEN 'Ready'
          WHEN 'Won' THEN 'Closed-Win'
          WHEN 'Handed Over' THEN 'Handover Complete'
          WHEN 'Closed' THEN 'Handover Complete'
          WHEN 'On Hold' THEN CASE previous_status
            WHEN 'Assigned' THEN 'Assigned'
            WHEN 'In Progress' THEN 'Assigned'
            WHEN 'Submitted' THEN 'Ready'
            WHEN 'Won' THEN 'Closed-Win'
            WHEN 'Handed Over' THEN 'Handover Complete'
            WHEN 'Closed' THEN 'Handover Complete'
            ELSE 'Pending Assignment'
          END
          ELSE status
        END
        """
    )

    op.drop_column("projects", "lost_reason")
    op.drop_column("projects", "previous_status")
    op.drop_column("projects", "qualification_state")
    op.alter_column("projects", "status", server_default="New")

    op.create_check_constraint(
        "chk_projects_status", "projects", f"status IN ({_daftar(STATUS_LAMA)})"
    )
