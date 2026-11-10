"""
Model SQLAlchemy untuk tabel source_documents.
Source document = file MoM/RFP yang di-upload Sales saat intake. Hanya teks hasil ekstraksi
yang disimpan; file asli TIDAK disimpan di server dan tidak membuat baris Document.
"""

import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

DOC_TYPES = ("MoM", "RFP")
EXTRACTION_STATUSES = ("pending", "extracted", "empty", "failed")


class SourceDocument(Base):
    """Teks hasil ekstraksi satu file MoM/RFP milik sebuah proyek."""

    __tablename__ = "source_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    id_project: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("projects.id_project", ondelete="CASCADE"),
        nullable=False,
        comment="FK ke proyek pemilik",
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False, comment="Nama file asli")
    doc_type: Mapped[str] = mapped_column(String(10), nullable=False, comment="MoM atau RFP")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Ukuran file asli")
    extraction_status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="pending", comment="pending/extracted/empty/failed"
    )
    extracted_text: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Teks hasil ekstraksi LLM"
    )
    truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="Respons LLM berhenti karena batas token"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        CheckConstraint("doc_type IN ('MoM', 'RFP')", name="chk_source_documents_doc_type"),
        CheckConstraint(
            "extraction_status IN ('pending', 'extracted', 'empty', 'failed')",
            name="chk_source_documents_status",
        ),
        Index("idx_source_documents_project", "id_project"),
        {"comment": "Source document (MoM/RFP) — teks hasil ekstraksi per proyek"},
    )
