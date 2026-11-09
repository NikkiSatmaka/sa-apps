"""
Model SQLAlchemy untuk tabel ProjectCollaborators.
Menyimpan data kolaborator yang ditag ke suatu proyek.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProjectCollaborator(Base):
    """Model untuk tabel project_collaborators — peer/atasan yang di-tag ke proyek."""

    __tablename__ = "project_collaborators"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Primary key UUID",
    )
    id_project: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("projects.id_project", ondelete="CASCADE"),
        nullable=False,
        comment="FK ke proyek terkait",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK ke user yang di-tag sebagai kolaborator",
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="viewer",
        comment="Peran kolaborator: viewer atau contributor",
    )
    added_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        comment="FK ke user yang menambahkan kolaborator",
    )

    # Timestamp (timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Waktu penambahan kolaborator",
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint(
            "id_project", "user_id",
            name="uq_project_collaborator",
            comment="Satu user hanya bisa menjadi kolaborator sekali per proyek",
        ),
        {"comment": "Tabel kolaborator proyek — peer/atasan yang di-tag untuk melihat atau berkontribusi"},
    )

    def __repr__(self) -> str:
        return f"<ProjectCollaborator(project={self.id_project}, user={self.user_id}, role={self.role})>"
