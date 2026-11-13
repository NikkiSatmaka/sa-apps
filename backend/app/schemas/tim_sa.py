"""
Schema Pydantic untuk endpoint Tim SA per proyek (SA utama + SA tambahan; ADR 0014).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AnggotaSA(BaseModel):
    """Satu SA di tim project."""

    id: uuid.UUID
    name: str
    email: str


class AnggotaSATambahan(AnggotaSA):
    """SA tambahan: ditambah siapa penambahnya dan kapan."""

    added_by: uuid.UUID
    created_at: datetime


class TimSAResponse(BaseModel):
    """Tim SA project: SA utama (penanggung jawab) dan SA tambahan (hak setara)."""

    sa_utama: AnggotaSA | None
    sa_tambahan: list[AnggotaSATambahan]


class TambahSATambahanRequest(BaseModel):
    """Request body menambah SA tambahan."""

    user_id: uuid.UUID = Field(..., description="UUID user berrole SA atau Lead_SA")


class GantiSAUtamaRequest(BaseModel):
    """Request body mengganti SA utama."""

    user_id: uuid.UUID = Field(..., description="UUID SA utama baru (role SA atau Lead_SA)")
    pertahankan_sebagai_tambahan: bool = Field(
        default=False,
        description="True: SA utama lama tetap di tim sebagai SA tambahan; default: dilepas",
    )
