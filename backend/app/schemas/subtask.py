"""
Schema Pydantic untuk entity Subtask (work item assignable per proyek).
Digunakan untuk validasi request/response pada fitur manajemen subtask.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

DESCRIPTION_MAX = 2000


def _description_ringkas(v: Optional[str]) -> Optional[str]:
    """Rapikan spasi tepi; string kosong dianggap tidak ada (NULL)."""
    if v is None:
        return None
    v = v.strip()
    return v or None


def _field_estimate_hours() -> Any:
    return Field(
        default=None,
        ge=Decimal("0"),
        max_digits=7,
        decimal_places=2,
        description="Estimasi jam pengerjaan (>= 0, maks 2 desimal); opsional",
    )


class SubtaskCreateRequest(BaseModel):
    """Request body untuk membuat subtask baru."""

    title: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Deskripsi work item subtask",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=DESCRIPTION_MAX,
        description="Uraian pekerjaan; opsional",
    )
    due_date: Optional[date] = Field(default=None, description="Batas waktu; opsional")
    estimate_hours: Optional[Decimal] = _field_estimate_hours()

    _rapikan_description = field_validator("description")(_description_ringkas)


class SubtaskUpdateRequest(BaseModel):
    """
    Request body untuk mengubah `description`, `due_date`, dan `estimate_hours` (PATCH parsial).

    Field yang tidak dikirim tidak diubah; nilai `null` eksplisit mengosongkan field.
    Minimal satu field harus dikirim.
    """

    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    due_date: Optional[date] = None
    estimate_hours: Optional[Decimal] = _field_estimate_hours()

    _rapikan_description = field_validator("description")(_description_ringkas)

    @model_validator(mode="after")
    def minimal_satu_field(self) -> "SubtaskUpdateRequest":
        if not self.model_fields_set:
            raise ValueError(
                "Kirim minimal satu field: description, due_date, atau estimate_hours."
            )
        return self


class SubtaskUpdateStatusRequest(BaseModel):
    """Request body untuk mengubah status subtask."""

    status: str = Field(
        ...,
        description="Status subtask; nilai valid: 'open', 'in_progress', 'done'",
    )


class SubtaskAssignRequest(BaseModel):
    """Request body untuk menugaskan (assign) subtask ke seorang SA."""

    assigned_sa: Optional[uuid.UUID] = Field(
        default=None,
        description="UUID SA yang ditugaskan; NULL untuk melepas penugasan",
    )


class SubtaskResponse(BaseModel):
    """Response data satu subtask."""

    id_subtask: str
    id_project: str
    title: str
    status: str
    assigned_sa: Optional[uuid.UUID] = None
    assigned_sa_name: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[date] = None
    estimate_hours: Optional[Decimal] = None
    terlambat: bool = False
    created_at: datetime
    updated_at: datetime


class SubtaskListResponse(BaseModel):
    """Response daftar subtask suatu proyek."""

    items: list[SubtaskResponse]
    total: int
