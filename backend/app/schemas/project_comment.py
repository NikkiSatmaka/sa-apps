"""Schema Pydantic untuk komentar project (issue #125, spec A5)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

BODY_MAKS = 4000


class KomentarCreateRequest(BaseModel):
    """Body POST komentar. Spasi tepi dibuang; isi kosong ditolak (422)."""

    body: str = Field(..., max_length=BODY_MAKS + 100, description="Isi komentar")

    @field_validator("body")
    @classmethod
    def _rapikan(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Isi komentar tidak boleh kosong.")
        if len(v) > BODY_MAKS:
            raise ValueError(f"Isi komentar maksimal {BODY_MAKS} karakter.")
        return v


class KomentarResponse(BaseModel):
    id_comment: str
    id_project: str
    author_id: uuid.UUID
    author_name: str | None = None
    author_role: str | None = None
    body: str
    created_at: datetime


class KomentarListResponse(BaseModel):
    items: list[KomentarResponse]
    total: int
