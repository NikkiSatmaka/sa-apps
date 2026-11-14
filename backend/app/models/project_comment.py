"""
Model SQLAlchemy untuk tabel ProjectComments (spec §2.5 dan A5, issue #125).

Thread komentar per proyek, terpisah dari Project Story (`activity_logs`). Komentar bersifat
append-only: tidak ada edit atau hapus (spec tidak menyebutnya).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProjectComment(Base):
    """Model untuk tabel project_comments — satu komentar pada thread proyek."""

    __tablename__ = "project_comments"

    id_comment: Mapped[str] = mapped_column(
        String(50), primary_key=True, comment="ID komentar (format CMT-YYYYMMDD-XXXXXX)"
    )
    id_project: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("projects.id_project", ondelete="CASCADE", name="fk_project_comments_project"),
        nullable=False,
        comment="FK ke proyek",
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_project_comments_author"),
        nullable=False,
        comment="FK ke user penulis",
    )
    body: Mapped[str] = mapped_column(Text, nullable=False, comment="Isi komentar")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Waktu komentar ditulis",
    )

    __table_args__ = (
        CheckConstraint("body !~ '^\\s*$'", name="chk_project_comments_body"),
        Index("idx_project_comments_project_created", "id_project", "created_at"),
        {"comment": "Komentar thread per proyek (append-only; terpisah dari Project Story)"},
    )

    def __repr__(self) -> str:
        return f"<ProjectComment(id={self.id_comment}, project={self.id_project})>"
