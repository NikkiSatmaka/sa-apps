"""
Schema Pydantic untuk endpoint assignment SA ke proyek.
Digunakan untuk validasi request/response pada fitur penugasan oleh Lead_SA.
"""

import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class AssignRequest(BaseModel):
    """Request body untuk assign SA ke proyek."""

    sa_id: uuid.UUID = Field(
        ...,
        description="UUID dari SA yang akan ditugaskan ke proyek",
    )
    lead_sa_id: Optional[uuid.UUID] = Field(
        default=None,
        description=(
            "UUID Lead_SA proyek (opsional). Bila kosong, yang meng-assign menjadi `lead_sa`."
        ),
    )


class SAAvailability(BaseModel):
    """Data ketersediaan SA beserta jumlah proyek aktif."""

    id: uuid.UUID = Field(..., description="UUID SA")
    name: str = Field(..., description="Nama lengkap SA")
    email: str = Field(..., description="Email SA")
    active_project_count: int = Field(
        ...,
        description="Jumlah proyek aktif yang sedang ditangani SA",
    )


class ProjectBrief(BaseModel):
    """Ringkasan data proyek untuk response assignment."""

    id_project: str
    project_name: str
    customer_name: str
    status: str
    bant_score: Optional[int] = None
    use_case_tags: Optional[list] = None
    assigned_sa: Optional[uuid.UUID] = None
    assigned_at: Optional[datetime] = None
    target_submit: date
    gdrive_folder_id: Optional[str] = None
    folder_provisioning_status: Optional[str] = None


class AssignmentResponse(BaseModel):
    """Response setelah assignment berhasil."""

    project: ProjectBrief = Field(..., description="Data proyek setelah di-assign")
    assigned_sa_name: str = Field(..., description="Nama SA yang ditugaskan")
    notification_sent: bool = Field(
        ...,
        description="Apakah notifikasi berhasil dikirim ke SA",
    )
    folder_provisioning_triggered: bool = Field(
        ...,
        description="Apakah folder provisioning sudah di-trigger",
    )
