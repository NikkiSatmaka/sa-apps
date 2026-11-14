"""
Schema Pydantic untuk endpoint workflow status proyek.
Digunakan untuk validasi request/response pada fitur transisi status proyek.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class StatusUpdateRequest(BaseModel):
    """Request body untuk mengubah status proyek."""

    new_status: str = Field(
        ...,
        description="Status baru yang ingin diterapkan ke proyek",
        examples=["Assigned", "In Progress", "Submitted", "Won", "Closed", "Lost", "On Hold"],
    )
    reason: Optional[str] = Field(
        None,
        description="Alasan perubahan status (opsional, wajib untuk status 'Lost')",
        max_length=500,
    )


class AuditLogEntry(BaseModel):
    """Data audit log yang dibuat setelah perubahan status."""

    id: str = Field(..., description="ID audit log")
    entity_type: str = Field(..., description="Tipe entitas (project)")
    entity_id: str = Field(..., description="ID proyek yang berubah")
    action: str = Field(..., description="Aksi yang dilakukan (status_change)")
    performed_by: str = Field(..., description="ID user yang melakukan perubahan")
    old_value: dict = Field(..., description="Nilai sebelum perubahan")
    new_value: dict = Field(..., description="Nilai setelah perubahan")
    created_at: datetime = Field(..., description="Waktu perubahan")


class StatusTransitionResponse(BaseModel):
    """Response setelah transisi status berhasil."""

    id_project: str = Field(..., description="ID proyek")
    project_name: str = Field(..., description="Nama proyek")
    old_status: str = Field(..., description="Status sebelumnya")
    new_status: str = Field(..., description="Status baru")
    audit_log: AuditLogEntry = Field(..., description="Entry audit log yang dibuat")
