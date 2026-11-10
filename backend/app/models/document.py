"""
Model SQLAlchemy untuk tabel Documents.
Menyimpan metadata dokumen proyek yang tersimpan di Google Drive.
"""

import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    gdrive_link: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Link Google Drive dokumen (boleh kosong hanya untuk Requirement)",
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
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        comment="FK ke user yang membuat dokumen (NULL hanya untuk Requirement hasil generate sistem)",
    )
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        comment="FK ke user yang terakhir update dokumen",
    )

    # Kolom khusus Requirement (konten turunan AI; NULL/default untuk dokumen jenis lain)
    content: Mapped[Optional[list]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Daftar butir Requirement [{id, kategori, butir}] (hanya Requirement)",
    )
    is_overridden: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="True bila konten sudah diedit manual (tidak lagi murni hasil AI)",
    )
    source_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="SHA-256 sumber (jawaban kuesioner + teks Source document extracted) saat generate",
    )
    generated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Waktu generate AI terakhir",
    )
    source_truncated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="True bila teks sumber terpotong saat generate",
    )

    source_changed_notified_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="Hash sumber basi terakhir yang sudah diberitahukan (notifikasi sekali per hash)",
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
        CheckConstraint(
            "gdrive_link IS NOT NULL OR doc_type = 'Requirement'",
            name="chk_documents_gdrive_link_required",
        ),
        CheckConstraint(
            "created_by IS NOT NULL OR doc_type = 'Requirement'",
            name="chk_documents_created_by_required",
        ),
        # Satu Requirement per proyek (mencegah duplikat/balapan generate)
        Index(
            "uq_documents_requirement_per_project",
            "id_project",
            unique=True,
            postgresql_where=text("doc_type = 'Requirement'"),
        ),
        {"comment": "Tabel metadata dokumen proyek"},
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id_doc}, type={self.doc_type}, status={self.status})>"
