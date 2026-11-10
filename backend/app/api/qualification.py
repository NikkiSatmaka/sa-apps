"""
Endpoint skema Kuesioner kualifikasi (ADR 0010 / tiket 5A-7).

- GET /api/v1/qualification/schema — definisi kuesioner (schema_version + pertanyaan + kelompok).
  Frontend merender form dan tampilan baca-saja dari sini; backend satu-satunya sumber definisi.
"""

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.qualification_definition import schema_payload
from app.schemas.response import success_response

router = APIRouter(tags=["Qualification"])


@router.get(
    "/qualification/schema",
    summary="Skema Kuesioner kualifikasi",
    description="Mengembalikan schema_version dan seluruh definisi pertanyaan kuesioner (terautentikasi).",
)
async def get_qualification_schema(current_user: User = Depends(get_current_user)):
    return success_response(schema_payload())
