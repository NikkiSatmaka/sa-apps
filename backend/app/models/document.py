"""
Model SQLAlchemy untuk tabel Documents.
Menyimpan metadata dokumen proyek yang tersimpan di Google Drive.
"""

import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Document(Base):
    """Model untuk tabel documents - metadata dokumen proyek."""

    __tablename__ = "documents"

    # Kolom utama
    id_doc: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        comment="ID dokumen (format custom)",
    )
    id_project: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("projects.id_project"),
        nullable=False,
        comment="FK ke proyek pemilik dokumen",
    )
    doc_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Tipe dokumen: Requirement, PropTek, BOQ, Mandays, MoM, RFP, HLD",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Draft",
        comment="Status dokumen: Draft, Reviewed, Final",
    )
    gdrive_link: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Link Google Drive dokumen",
    )
    folder_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Tipe folder penyimpanan: Inventory, Diagram, Solutions",
    )
    notes: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Catatan tambahan untuk dokumen",
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        comment="FK ke user yang membuat dokumen",
    )
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        comment="FK ke user yang terakhir update dokumen",
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
            "doc_type IN ('Requirement', 'PropTek', 'BOQ', 'Mandays', 'MoM', 'RFP', 'HLD')",
            name="chk_documents_doc_type",
        ),
        CheckConstraint(
            "status IN ('Draft', 'Reviewed', 'Final')",
            name="chk_documents_status",
        ),
        CheckConstraint(
            "folder_type IN ('Inventory', 'Diagram', 'Solutions')",
            name="chk_documents_folder_type",
        ),
        {"comment": "Tabel metadata dokumen proyek"},
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id_doc}, type={self.doc_type}, status={self.status})>"
