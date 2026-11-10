"""
Pydantic schemas untuk Notification.
Validasi input dan format response sesuai requirement 14.x.
"""

from datetime import datetime
from typing import Optional

from pydantic import AliasChoices, BaseModel, Field


class NotificationResponse(BaseModel):
    """Schema response untuk satu notifikasi."""

    id: str = Field(..., description="ID notifikasi")
    event_type: str = Field(..., description="Tipe event notifikasi")
    channel: str = Field(..., description="Channel: in-app atau email")
    status: str = Field(..., description="Status: pending, sent, failed, read")
    reference_id: Optional[str] = Field(None, description="ID referensi entitas terkait")
    # Atribut ORM bernama `notification_metadata` (kolom "metadata"); `metadata` pada kelas ORM
    # adalah MetaData SQLAlchemy sehingga tidak boleh dibaca dari atribut itu.
    metadata: Optional[dict] = Field(
        None,
        validation_alias=AliasChoices("notification_metadata", "metadata"),
        description="Metadata tambahan notifikasi",
    )
    created_at: datetime = Field(..., description="Waktu pembuatan notifikasi")
    read_at: Optional[datetime] = Field(None, description="Waktu notifikasi dibaca")

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """Schema response untuk daftar notifikasi (paginated)."""

    items: list[NotificationResponse] = Field(
        default_factory=list,
        description="Daftar notifikasi",
    )
    total: int = Field(..., description="Total jumlah notifikasi")
    page: int = Field(..., description="Halaman saat ini (1-based)")
    per_page: int = Field(default=20, description="Jumlah item per halaman")


class UnreadCountResponse(BaseModel):
    """Schema response untuk jumlah notifikasi yang belum dibaca."""

    unread_count: int = Field(..., description="Jumlah notifikasi belum dibaca")
