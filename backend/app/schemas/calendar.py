"""
Pydantic schemas untuk Google Calendar sync dan event mapping.
Digunakan oleh endpoint /api/v1/calendar/sync dan /api/v1/calendar/map.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.schemas.activity_log import (
    VALID_PROJECT_PHASES,
    VALID_WORK_TYPES,
    subtask_categories_for,
)

from app.schemas.integration_operation import IntegrationOperationResponse
# === Request Schemas ===



class CalendarMapRequest(BaseModel):
    """Request body untuk memetakan event Google Calendar ke proyek."""

    gcal_event_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="ID event dari Google Calendar",
    )
    work_type: str = Field(
        default="Project",
        description="Jenis aktivitas: Project atau Non-Project",
    )
    project_id: Optional[str] = Field(
        default=None,
        max_length=50,
        description="ID proyek tujuan (wajib untuk Project, kosong untuk Non-Project)",
    )
    project_phase: Optional[str] = Field(
        default=None,
        description="Fase proyek (wajib untuk Project, kosong untuk Non-Project)",
    )
    subtask_category: str = Field(
        ...,
        description="Sub-kategori aktivitas (tergantung work_type)",
    )
    duration_hours: Optional[Decimal] = Field(
        default=None,
        ge=Decimal("0.25"),
        le=Decimal("24.00"),
        description="Override durasi (jam). Jika kosong, dihitung otomatis dari event.",
    )
    raw_notes: Optional[str] = Field(
        default=None,
        description="Catatan mentah. Jika kosong, auto-generate dari event title + description.",
    )
    event_title: str = Field(
        ...,
        description="Judul event untuk auto-generate notes jika raw_notes kosong",
    )
    event_description: Optional[str] = Field(
        default=None,
        description="Deskripsi event untuk auto-generate notes",
    )
    is_all_day: bool = Field(
        default=False,
        description="Apakah event all-day (durasi default 8 jam)",
    )
    event_start: Optional[datetime] = Field(
        default=None,
        description="Waktu mulai event (untuk kalkulasi durasi)",
    )
    event_end: Optional[datetime] = Field(
        default=None,
        description="Waktu selesai event (untuk kalkulasi durasi)",
    )

    @model_validator(mode="after")
    def validate_work_type_consistency(self) -> "CalendarMapRequest":
        """
        Validasi konsistensi berdasarkan work_type (selaras ActivityLogCreate):
        - Project: project_id & project_phase wajib; subtask dari set Project.
        - Non-Project: project_id & project_phase harus kosong; subtask dari set Non-Project.
        """
        if self.work_type not in VALID_WORK_TYPES:
            raise ValueError(
                f"work_type tidak valid. Pilihan: {', '.join(VALID_WORK_TYPES)}"
            )

        if self.work_type == "Project":
            if not self.project_id:
                raise ValueError("project_id wajib diisi untuk aktivitas Project.")
            if not self.project_phase:
                raise ValueError("project_phase wajib diisi untuk aktivitas Project.")
            if self.project_phase not in VALID_PROJECT_PHASES:
                raise ValueError(
                    f"project_phase tidak valid. Pilihan: {', '.join(VALID_PROJECT_PHASES)}"
                )
        else:  # Non-Project
            if self.project_id:
                raise ValueError("Aktivitas Non-Project tidak boleh terkait proyek.")
            if self.project_phase:
                raise ValueError("Aktivitas Non-Project tidak boleh punya project_phase.")

        allowed = subtask_categories_for(self.work_type)
        if self.subtask_category not in allowed:
            raise ValueError(
                f"Subtask category '{self.subtask_category}' tidak valid untuk "
                f"work_type '{self.work_type}'. Pilihan: {', '.join(allowed)}"
            )

        return self


# === Response Schemas ===


class CalendarAuthUrlResponse(BaseModel):
    auth_url: str


class CalendarSyncErrorData(BaseModel):
    integration_operation: Optional[IntegrationOperationResponse] = None



class CalendarEventResponse(BaseModel):
    """Representasi satu event Google Calendar setelah sync."""

    gcal_event_id: str
    title: str
    start: Optional[str] = None
    end: Optional[str] = None
    duration_hours: Decimal
    is_all_day: bool
    description: Optional[str] = None


class CalendarSyncResponse(BaseModel):
    """Response dari endpoint sync — daftar events."""

    events: list[CalendarEventResponse]
    total_events: int
    integration_operation: Optional[IntegrationOperationResponse] = None


class CalendarMapResponse(BaseModel):
    """Response dari endpoint map — detail activity log yang dibuat."""

    id_log: str
    work_type: str
    id_project: Optional[str] = None
    project_phase: Optional[str] = None
    gcal_event_id: str
    subtask_category: str
    duration_hours: Decimal
    raw_notes: str
    created_at: datetime
