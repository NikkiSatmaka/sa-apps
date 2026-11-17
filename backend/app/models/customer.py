"""Persistent identity for a customer organization."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(450), nullable=False, unique=True)
    gdrive_folder_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    projects = relationship("Project", back_populates="customer")

    __table_args__ = (
        UniqueConstraint("gdrive_folder_id", name="uq_customers_gdrive_folder_id"),
    )
