"""
Model SQLAlchemy untuk tabel ProjectAssignments (SA tambahan per proyek, ADR 0014).

SA utama tetap `Project.assigned_sa` dan tidak diulang di tabel ini.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProjectAssignment(Base):
    """Model untuk tabel project_assignments — SA tambahan dengan hak setara SA utama."""

    __tablename__ = "project_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="Primary key UUID"
    )
    id_project: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("projects.id_project", ondelete="CASCADE", name="fk_project_assignments_id_project"),
        nullable=False,
        comment="FK ke proyek",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_project_assignments_user_id"),
        nullable=False,
        comment="FK ke user SA tambahan",
    )
    added_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_project_assignments_added_by"),
        nullable=False,
        comment="FK ke Lead_SA/Admin penambah",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Waktu penambahan",
    )

    __table_args__ = (
        UniqueConstraint("id_project", "user_id", name="uq_project_assignment"),
        {"comment": "SA tambahan per proyek (hak setara SA utama; ADR 0014)"},
    )

    def __repr__(self) -> str:
        return f"<ProjectAssignment(project={self.id_project}, user={self.user_id})>"
