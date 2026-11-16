"""Short-lived, user-bound sessions for encrypted Google Calendar access tokens."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CalendarOAuthSession(Base):
    __tablename__ = "calendar_oauth_sessions"
    __table_args__ = (
        CheckConstraint("length(session_hash) = 64", name="chk_calendar_oauth_sessions_hash"),
        Index("ix_calendar_oauth_sessions_user_id", "user_id"),
        Index("ix_calendar_oauth_sessions_expires_at", "expires_at"),
    )

    session_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
            name="fk_calendar_oauth_sessions_user_id_users",
        ),
        nullable=False,
    )
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
