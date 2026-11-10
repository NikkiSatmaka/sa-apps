"""
Pydantic schemas untuk Activity Log.
Validasi input dan format response sesuai requirement 8.x.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

# Work type aktivitas
VALID_WORK_TYPES = ["Project", "Non-Project"]

# Fase proyek (hanya untuk work_type=Project)
VALID_PROJECT_PHASES = [
    "Pre-Implementation",
    "Implementation",
    "Post-Implementation",
]

# Sub-kategori per work_type
PROJECT_SUBTASK_CATEGORIES = [
    "Assessment",
    "Internal Meeting",
    "Customer Meeting",
    "Principal Meeting",
    "Commercial Document",
    "Technical Document",
    "Document Review",
]

NON_PROJECT_SUBTASK_CATEGORIES = [
    "Training",
    "Self-Lab",
    "Self-Learning",
    "Exam",
    "Internal Meeting",
    "Internal Presentation",
    "External Presentation",
    "Principal Meeting",
]

# Union seluruh sub-kategori valid (dipakai sebagai fallback/validasi longgar)
VALID_SUBTASK_CATEGORIES = sorted(
    set(PROJECT_SUBTASK_CATEGORIES) | set(NON_PROJECT_SUBTASK_CATEGORIES)
)


def subtask_categories_for(work_type: str) -> list[str]:
    """Daftar sub-kategori yang valid untuk sebuah work_type."""
    if work_type == "Non-Project":
        return NON_PROJECT_SUBTASK_CATEGORIES
    return PROJECT_SUBTASK_CATEGORIES


def default_phase_for_status(project_status: str) -> str:
    """
    Default project_phase berdasarkan status proyek saat log dibuat.
    - Handover Complete → Implementation (masa serah terima)
    - Selainnya → Pre-Implementation (mayoritas kerja SA pre-sales)
    - Post-Implementation tidak pernah jadi default (tag manual saja).
    """
    if project_status == "Handover Complete":
        return "Implementation"
    return "Pre-Implementation"


class ActionItem(BaseModel):
    """Item aksi hasil AI polishing."""

    description: str
    pic: Optional[str] = None


class AiPolishedNotes(BaseModel):
    """Format output AI polishing (requirement 8.3)."""

    discussion_points: list[str] = Field(
        default_factory=list,
        description="Daftar poin diskusi yang sudah di-polish",
    )
    action_items: list[ActionItem] = Field(
        default_factory=list,
        description="Daftar item aksi dengan deskripsi dan PIC",
    )


class ActivityLogCreate(BaseModel):
    """
    Schema validasi untuk pembuatan activity log baru (requirement 8.1, 8.2).

    Validasi:
    - id_project: wajib, string (FK ke projects)
    - subtask_category: wajib, harus dari daftar yang valid
    - duration_hours: 0.25–24.00, kelipatan 0.25
    - raw_notes: wajib, maksimal 5000 karakter
    - gcal_event_id: opsional, untuk mapping dari Google Calendar
    """

    work_type: str = Field(
        default="Project",
        description="Jenis aktivitas: Project atau Non-Project",
    )
    id_project: Optional[str] = Field(
        default=None,
        description="ID proyek (wajib untuk Project, kosong untuk Non-Project)",
    )
    project_phase: Optional[str] = Field(
        default=None,
        description="Fase proyek (wajib untuk Project, kosong untuk Non-Project)",
    )
    subtask_category: str = Field(
        ...,
        description="Sub-kategori aktivitas (tergantung work_type)",
    )
    id_subtask: Optional[str] = Field(
        default=None,
        description="ID subtask terkait (opsional, tautan informasional)",
    )
    duration_hours: Decimal = Field(
        ...,
        ge=Decimal("0.25"),
        le=Decimal("24.00"),
        description="Durasi aktivitas dalam jam (0.25–24.00, kelipatan 0.25)",
    )
    raw_notes: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Catatan mentah aktivitas (maks 5000 karakter)",
    )
    gcal_event_id: Optional[str] = Field(
        None,
        max_length=255,
        description="ID event Google Calendar (opsional)",
    )

    @model_validator(mode="after")
    def validate_work_type_consistency(self) -> "ActivityLogCreate":
        """
        Validasi konsistensi antar-field berdasarkan work_type:
        - work_type harus valid.
        - Project: id_project & project_phase wajib; subtask dari set Project.
        - Non-Project: id_project & project_phase harus kosong; subtask dari set Non-Project.
        """
        if self.work_type not in VALID_WORK_TYPES:
            raise ValueError(f"work_type tidak valid. Pilihan: {', '.join(VALID_WORK_TYPES)}")

        if self.work_type == "Project":
            if not self.id_project:
                raise ValueError("id_project wajib diisi untuk aktivitas Project.")
            if not self.project_phase:
                raise ValueError("project_phase wajib diisi untuk aktivitas Project.")
            if self.project_phase not in VALID_PROJECT_PHASES:
                raise ValueError(
                    f"project_phase tidak valid. Pilihan: {', '.join(VALID_PROJECT_PHASES)}"
                )
        else:  # Non-Project
            if self.id_project:
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

    @field_validator("duration_hours")
    @classmethod
    def validate_duration_multiple(cls, v: Decimal) -> Decimal:
        """Validasi durasi harus kelipatan 0.25."""
        remainder = v % Decimal("0.25")
        if remainder != 0:
            raise ValueError("Durasi harus kelipatan 0.25 jam.")
        return v

    @field_validator("raw_notes")
    @classmethod
    def strip_notes(cls, v: str) -> str:
        """Trim whitespace di awal/akhir; catatan yang hanya berisi spasi dianggap kosong."""
        v = v.strip()
        if not v:
            raise ValueError("raw_notes wajib diisi (tidak boleh hanya spasi).")
        return v


class ActivityLogResponse(BaseModel):
    """Schema response untuk satu activity log entry."""

    id_log: str
    work_type: str
    id_project: Optional[str] = None
    project_phase: Optional[str] = None
    sa_id: UUID
    subtask_category: str
    id_subtask: Optional[str] = None
    duration_hours: Decimal
    raw_notes: str
    ai_polished_notes: Optional[dict] = None
    gcal_event_id: Optional[str] = None
    created_at: datetime
    needs_repolish: bool = Field(
        default=False,
        description="True jika AI polishing gagal dan perlu di-trigger ulang",
    )

    class Config:
        from_attributes = True


class ProjectStoryResponse(BaseModel):
    """Schema response untuk project story (paginated)."""

    items: list[ActivityLogResponse]
    total: int = Field(..., description="Total jumlah entry")
    page: int = Field(..., description="Halaman saat ini (1-based)")
    page_size: int = Field(default=20, description="Jumlah entry per halaman")
    total_pages: int = Field(..., description="Total halaman")
