"""
Model SQLAlchemy untuk tabel Projects.
Menyimpan data proyek yang dikelola oleh Sales dan SA.
Catatan: kolom sales_pic menyimpan requester (bisa Sales, SA, atau Lead_SA).
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import (
    Mapped,
    ORMExecuteState,
    Session,
    mapped_column,
    relationship,
    with_loader_criteria,
)

from app.core.database import Base


class Project(Base):
    """Model untuk tabel projects - data proyek presales."""

    __tablename__ = "projects"

    # Kolom utama
    id_project: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        comment="ID proyek (format custom)",
    )
    project_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        comment="Nama proyek",
    )
    customer_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        comment="Nama customer/perusahaan",
    )
    dq_number: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Nomor DQ (Deal Qualification)",
    )
    sales_pic: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        comment="FK ke user requester yang membuat request (Sales/SA/Lead_SA)",
    )
    assigned_sa: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        comment="FK ke user SA yang ditugaskan",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="New",
        comment="Status proyek saat ini",
    )
    target_submit: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="Target tanggal submit proposal",
    )
    bant_score: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Skor BANT (0-100)",
    )
    bant_detail: Mapped[Optional[dict]] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=True,
        comment="Detail breakdown skor BANT per kriteria",
    )
    qualification_answers: Mapped[Optional[dict]] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=True,
        comment="Jawaban Kuesioner kualifikasi (NULL = proyek lama / legacy)",
    )
    qualification_schema_version: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Versi skema kuesioner pada saat jawaban disimpan",
    )
    ai_scoring_result: Mapped[Optional[dict]] = mapped_column(
        MutableDict.as_mutable(JSONB),
        nullable=True,
        comment="Hasil analisis AI terakhir atas file (sub_scores, use_case_tags), terpisah dari rubrik",
    )
    estimasi_nilai: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2),
        nullable=True,
        comment="Estimasi nilai proyek dalam IDR (0.01 - 999,999,999,999.00)",
    )
    use_case_tags: Mapped[Optional[list]] = mapped_column(
        JSONB,
        nullable=True,
        default=list,
        comment="Tags use case proyek (array JSON)",
    )
    gdrive_folder_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="ID folder Google Drive proyek",
    )
    gdrive_solutions_folder_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="ID subfolder Solutions di Google Drive (ADR 0005)",
    )
    folder_provisioning_status: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Status provisioning folder: pending/provisioned/failed",
    )
    # Konfigurasi handover PMO/Delivery (per-proyek, requirement 17.6)
    pmo_lead_email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Email PMO Lead untuk handover proyek",
    )
    delivery_lead_email: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Email Delivery Lead untuk handover proyek",
    )

    assigned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Waktu SA ditugaskan ke proyek",
    )

    # Soft delete — proyek terhapus tetap di DB agar dokumen, activity log
    # (data utilisasi SA), dan SLA tidak hilang. Disaring otomatis dari semua
    # query ORM oleh listener `_filter_soft_deleted` di bawah.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Waktu proyek dihapus (soft delete); NULL = aktif",
    )
    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        comment="FK ke user yang menghapus proyek",
    )

    # Timestamp (timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Waktu pembuatan record",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        comment="Waktu update terakhir",
    )

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "status IN ('New', 'Pending Assignment', 'Assigned', 'Ready', "
            "'Closed-Win', 'Handover Complete', 'Lost', 'Need Clarification', "
            "'Scoring Pending', 'Manual Review Required')",
            name="chk_projects_status",
        ),
        CheckConstraint(
            "bant_score IS NULL OR (bant_score BETWEEN 0 AND 100)",
            name="chk_projects_bant_score",
        ),
        CheckConstraint(
            "dq_number IS NULL OR dq_number ~ '^[A-Za-z0-9\\-]{5,20}$'",
            name="chk_dq_number_format",
        ),
        CheckConstraint(
            "folder_provisioning_status IS NULL OR "
            "folder_provisioning_status IN ('pending','provisioned','failed')",
            name="chk_projects_folder_provisioning_status",
        ),
        Index(
            "idx_projects_active",
            "updated_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"comment": "Tabel proyek presales Portal SA"},
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id_project}, name={self.project_name}, status={self.status})>"


# Opsi eksekusi untuk menonaktifkan filter soft delete, mis.:
#   select(Project).execution_options(**{INCLUDE_DELETED: True})
INCLUDE_DELETED = "include_deleted"


@event.listens_for(Session, "do_orm_execute")
def _filter_soft_deleted(execute_state: ORMExecuteState) -> None:
    """
    Sembunyikan proyek yang sudah di-soft delete dari semua SELECT ORM.

    Berlaku global (semua Session, termasuk AsyncSession) sehingga ~45 query
    `select(Project)` yang tersebar tidak perlu menambah filter manual.
    Pola resmi SQLAlchemy: with_loader_criteria di event do_orm_execute.
    """
    if (
        execute_state.is_select
        and not execute_state.is_column_load
        and not execute_state.is_relationship_load
        and not execute_state.execution_options.get(INCLUDE_DELETED, False)
    ):
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                Project,
                Project.deleted_at.is_(None),
                include_aliases=True,
            )
        )
