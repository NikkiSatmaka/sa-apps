"""
Model SQLAlchemy untuk tabel ActivityLogs.
Menyimpan catatan aktivitas harian SA per proyek.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ActivityLog(Base):
    """Model untuk tabel activity_logs - catatan aktivitas SA."""

    __tablename__ = "activity_logs"

    # Kolom utama
    id_log: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        comment="ID log aktivitas (format custom)",
    )
    id_project: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("projects.id_project"),
        nullable=True,
        comment="FK ke proyek terkait (wajib untuk work_type=Project, NULL untuk Non-Project)",
    )
    sa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        comment="FK ke user yang melakukan aktivitas (SA atau Lead_SA)",
    )
    work_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Project",
        comment="Jenis aktivitas: Project atau Non-Project",
    )
    project_phase: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
        comment="Fase proyek (Pre-Implementation/Implementation/Post-Implementation); NULL untuk Non-Project",
    )
    subtask_category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Sub-kategori aktivitas (tergantung work_type)",
    )
    id_subtask: Mapped[Optional[str]] = mapped_column(
        String(50),
        ForeignKey("subtasks.id_subtask", ondelete="SET NULL"),
        nullable=True,
        comment="FK opsional ke subtask terkait (informasional)",
    )
    gcal_event_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="ID event Google Calendar (opsional)",
    )
    duration_hours: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        comment="Durasi aktivitas dalam jam (0.25 - 24.00)",
    )
    raw_notes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Catatan mentah dari SA",
    )
    ai_polished_notes: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Catatan yang sudah di-polish oleh AI (JSON terstruktur)",
    )

    # Timestamp (timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Waktu pembuatan record",
    )

    # Constraints dan Indexes
    __table_args__ = (
        # Union seluruh sub-kategori valid (Project + Non-Project).
        # Kecocokan subtask dengan work_type divalidasi di layer schema/service.
        CheckConstraint(
            "subtask_category IN ("
            "'Assessment', 'Internal Meeting', 'Customer Meeting', "
            "'Principal Meeting', 'Commercial Document', 'Technical Document', "
            "'Document Review', 'Training', 'Self-Lab', 'Self-Learning', "
            "'Exam', 'Internal Presentation', 'External Presentation')",
            name="chk_activity_logs_subtask_category",
        ),
        CheckConstraint(
            "work_type IN ('Project', 'Non-Project')",
            name="chk_activity_logs_work_type",
        ),
        CheckConstraint(
            "project_phase IS NULL OR project_phase IN "
            "('Pre-Implementation', 'Implementation', 'Post-Implementation')",
            name="chk_activity_logs_project_phase",
        ),
        # Konsistensi: Project wajib punya id_project + project_phase;
        # Non-Project tidak boleh punya keduanya.
        CheckConstraint(
            "(work_type = 'Project' AND id_project IS NOT NULL AND project_phase IS NOT NULL) "
            "OR (work_type = 'Non-Project' AND id_project IS NULL AND project_phase IS NULL)",
            name="chk_activity_logs_worktype_consistency",
        ),
        CheckConstraint(
            "duration_hours BETWEEN 0.25 AND 24.00",
            name="chk_activity_logs_duration_hours",
        ),
        # Partial unique index: gcal_event_id harus unik jika tidak NULL
        Index(
            "idx_unique_gcal_mapping",
            "gcal_event_id",
            unique=True,
            postgresql_where=text("gcal_event_id IS NOT NULL"),
        ),
        {"comment": "Tabel catatan aktivitas harian SA"},
    )

    def __repr__(self) -> str:
        return f"<ActivityLog(id={self.id_log}, category={self.subtask_category})>"
