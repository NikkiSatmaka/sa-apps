"""
Model SQLAlchemy untuk tabel Subtasks.
Menyimpan work item yang bisa ditugaskan (assignable) ke SA dalam suatu proyek.
Catatan: Subtask adalah konsep work item, berbeda dengan ActivityCategory
(activity_logs.subtask_category) yang merupakan sub-kategori aktivitas.
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
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Subtask(Base):
    """Model untuk tabel subtasks — work item assignable per proyek."""

    __tablename__ = "subtasks"

    # Kolom utama
    id_subtask: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        comment="ID subtask (format custom)",
    )
    id_project: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("projects.id_project", ondelete="CASCADE"),
        nullable=False,
        comment="FK ke proyek terkait",
    )
    assigned_sa: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        comment="FK ke user SA yang ditugaskan ke subtask (opsional)",
    )
    title: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        comment="Deskripsi work item subtask",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="open",
        comment="Status subtask: open, in_progress, atau done",
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Uraian pekerjaan (opsional)",
    )
    due_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        comment="Batas waktu subtask (opsional)",
    )
    estimate_hours: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(7, 2),
        nullable=True,
        comment="Estimasi jam pengerjaan, >= 0 (opsional)",
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
            "status IN ('open', 'in_progress', 'done')",
            name="chk_subtasks_status",
        ),
        CheckConstraint(
            "estimate_hours IS NULL OR estimate_hours >= 0",
            name="chk_subtasks_estimate_hours",
        ),
        UniqueConstraint(
            "id_project", "title",
            name="uq_subtask_project_title",
        ),
        {"comment": "Tabel subtask — work item assignable per proyek"},
    )

    def __repr__(self) -> str:
        return f"<Subtask(id={self.id_subtask}, project={self.id_project}, status={self.status})>"
