"""
API tampilan workload Lead_SA (issue #127, spec §2.5). Hanya Lead_SA atau `is_admin`.

- GET /workload/beban — beban tiap SA (subtask aktif, project aktif, jam terlog minggu ini)
- GET /workload/jatuh-tempo — subtask dan project yang lewat atau mendekati due date
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import adalah_privileged, get_current_user
from app.models.user import User
from app.schemas.response import success_response
from app.schemas.workload import BebanResponse
from app.services import workload

router = APIRouter(prefix="/workload", tags=["Workload"])


def _wajib_lead_sa(user: User) -> None:
    if not adalah_privileged(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Lead_SA atau Admin yang dapat melihat workload.",
        )


@router.get("/beban", summary="Beban tiap SA")
async def get_beban(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _wajib_lead_sa(current_user)
    sekarang = datetime.now(UTC)
    items = await workload.hitung_beban(db, sekarang)
    data = BebanResponse(minggu_mulai=workload.awal_minggu(sekarang).date().isoformat(), items=items)
    return success_response(data=data.model_dump(mode="json"), message="Beban SA berhasil diambil.")


@router.get("/jatuh-tempo", summary="Subtask dan project lewat atau mendekati due date")
async def get_jatuh_tempo(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _wajib_lead_sa(current_user)
    data = await workload.hitung_jatuh_tempo(db, datetime.now(UTC).date())
    return success_response(data=data.model_dump(mode="json"), message="Jatuh tempo berhasil diambil.")
