"""
Model SQLAlchemy untuk tabel AuditLogs.
Menyimpan jejak audit perubahan data pada entitas sistem.
"""

import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import String, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """Model untuk tabel audit_logs - jejak audit perubahan data."""

    __tablename__ = "audit_logs"

    # Kolom utama
    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        comment="ID audit log (format custom)",
    )
    entity_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="Tipe entitas yang diubah (project, document, dll)",
    )
    entity_id: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="ID entitas yang diubah",
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Aksi yang dilakukan (create, update, delete, dll)",
    )
    performed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        comment="FK ke user yang melakukan aksi",
    )
    old_value: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Nilai sebelum perubahan (NULL untuk create)",
    )
    new_value: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Nilai setelah perubahan",
    )

    # Timestamp (timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Waktu aksi dilakukan",
    )

    # Table args
    __table_args__ = (
        {"comment": "Tabel jejak audit perubahan data sistem"},
    )

    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, entity={self.entity_type}:{self.entity_id}, action={self.action})>"
