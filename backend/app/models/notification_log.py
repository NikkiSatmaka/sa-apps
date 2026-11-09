"""
Model SQLAlchemy untuk tabel NotificationLogs.
Menyimpan riwayat notifikasi yang dikirim ke pengguna.
"""

import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import String, ForeignKey, CheckConstraint, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class NotificationLog(Base):
    """Model untuk tabel notification_logs - riwayat notifikasi."""

    __tablename__ = "notification_logs"

    # Kolom utama
    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        comment="ID notifikasi (format custom)",
    )
    event_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="Tipe event notifikasi",
    )
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        comment="FK ke user penerima notifikasi",
    )
    channel: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="Channel pengiriman: in-app atau email",
    )
    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="pending",
        comment="Status pengiriman notifikasi",
    )
    reference_id: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="ID referensi entitas terkait (proyek/dokumen)",
    )
    notification_metadata: Mapped[Optional[dict]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Metadata tambahan notifikasi (JSON)",
    )

    # Timestamp (timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Waktu pembuatan notifikasi",
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Waktu notifikasi dibaca oleh user",
    )

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('assignment', 'status_change', 'sla_reminder', "
            "'sla_escalation', 'handover', 'doc_ready')",
            name="chk_notification_logs_event_type",
        ),
        CheckConstraint(
            "channel IN ('in-app', 'email')",
            name="chk_notification_logs_channel",
        ),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'read')",
            name="chk_notification_logs_status",
        ),
        {"comment": "Tabel riwayat notifikasi pengguna"},
    )

    def __repr__(self) -> str:
        return f"<NotificationLog(id={self.id}, type={self.event_type}, status={self.status})>"
