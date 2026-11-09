"""
Model SQLAlchemy untuk tabel Users.
Menyimpan data user yang login via Google OAuth.
"""

import uuid
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import String, CheckConstraint, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    """Model untuk tabel users - data pengguna sistem."""

    __tablename__ = "users"

    # Kolom utama
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Primary key UUID",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="Email unik pengguna",
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Nama lengkap pengguna",
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="SA",
        comment="Role pengguna: Sales, SA, Lead_SA, Admin",
    )
    google_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="Google OAuth ID unik",
    )
    avatar_url: Mapped[Optional[str]] = mapped_column(
        String,
        nullable=True,
        comment="URL avatar dari Google",
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
            "role IN ('Sales', 'SA', 'Lead_SA', 'Admin')",
            name="chk_users_role",
        ),
        {"comment": "Tabel pengguna sistem Portal SA"},
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"
