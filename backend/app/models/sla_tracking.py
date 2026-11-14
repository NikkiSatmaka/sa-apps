"""
Model SQLAlchemy untuk tabel SLATracking.
Menyimpan data tracking SLA countdown DQ Number per proyek.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Boolean, ForeignKey, CheckConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SLATracking(Base):
    """Model untuk tabel sla_tracking - tracking SLA countdown proyek."""

    __tablename__ = "sla_tracking"

    # Kolom utama
    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
        comment="ID SLA tracking (format custom)",
    )
    project_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("projects.id_project"),
        unique=True,
        nullable=False,
        comment="FK ke proyek (satu proyek hanya punya satu SLA tracker)",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Waktu mulai tracking SLA",
    )
    stopped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Waktu SLA dihentikan (DQ Number sudah diinput)",
    )
    days_elapsed: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Jumlah hari yang sudah berlalu sejak SLA dimulai",
    )
    current_status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="green",
        comment="Status SLA saat ini: green, yellow, red",
    )
    is_locked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Apakah folder Solutions sudah di-lock",
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Waktu folder Solutions di-lock",
    )
    unlocked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Waktu folder Solutions di-unlock",
    )

    escalated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Waktu eskalasi H+5 dikirim (sekali per tracker)",
    )

    paused_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Waktu jeda On Hold yang sedang berjalan (NULL = tidak dijeda)",
    )
    paused_total_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Akumulasi detik jeda On Hold yang sudah selesai",
    )

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "current_status IN ('green', 'yellow', 'red')",
            name="chk_sla_tracking_current_status",
        ),
        CheckConstraint(
            "paused_total_seconds >= 0",
            name="chk_sla_tracking_paused_total_seconds",
        ),
        {"comment": "Tabel tracking SLA countdown DQ Number"},
    )

    def __repr__(self) -> str:
        return f"<SLATracking(id={self.id}, project={self.project_id}, status={self.current_status})>"
