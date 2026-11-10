"""
API generate ulang manual Requirement (Fase 5B, #34).

POST /projects/{id}/requirement/regenerate menandai proyek `pending` lalu menjalankan
generate di background (jalur yang sama dengan trigger otomatis). Dipakai juga sebagai
"coba lagi" saat status `failed`.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.project import Project
from app.models.user import User
from app.schemas.response import success_response
from app.services.requirement_generator import (
    can_regenerate_requirement,
    generate_pending_requirement,
)

router = APIRouter(tags=["Requirement"])


@router.post(
    "/projects/{project_id}/requirement/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate ulang Requirement (SA ditugaskan, Lead_SA, Admin)",
    description=(
        "Menjalankan ulang generate Requirement di background. Menimpa konten dan "
        "menghapus penanda override. Juga berfungsi sebagai coba lagi setelah gagal."
    ),
)
async def regenerate_requirement(
    project_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    if not can_regenerate_requirement(project, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya SA yang ditugaskan, Lead SA, atau Admin yang dapat generate ulang Requirement.",
        )

    if project.requirement_generation_status is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Requirement belum tersedia: proyek belum lolos gate kualifikasi.",
        )
    if project.requirement_generation_status == "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Requirement sedang dibuat. Tunggu hingga selesai.",
        )

    project.requirement_generation_status = "pending"
    await db.commit()
    background_tasks.add_task(generate_pending_requirement, project_id, True)

    return success_response(
        data={"requirement_generation_status": "pending"},
        message="Generate ulang Requirement dimulai.",
    )
