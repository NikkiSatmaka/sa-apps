"""
API endpoints untuk PMO Handover automation.

Endpoints:
- POST /api/v1/projects/{id}/handover — Trigger proses handover
- GET /api/v1/projects/{id}/handover-status — Cek kesiapan handover
- POST /api/v1/projects/{id}/handover-config — Set email PMO/Delivery Lead

Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    PERAN_REQUESTER,
    TingkatAkses,
    adalah_privileged,
    ensure_project_access,
    get_current_user,
)
from app.models.project import Project
from app.models.user import User
from app.schemas.handover import HandoverConfigInput, HandoverReadiness, HandoverResponse
from app.schemas.response import error_response, success_response
from app.services.handover_service import HandoverError, handover_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Handover"])


@router.get(
    "/projects/{project_id}/handover-status",
    summary="Cek kesiapan handover proyek",
    description=(
        "Mengembalikan status kesiapan handover: apakah semua prasyarat "
        "terpenuhi (status Closed-Win, HLD Final, PMO/Delivery dikonfigurasi)."
    ),
)
async def get_handover_status(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cek apakah proyek siap untuk di-handover.
    Endpoint ini bisa diakses oleh SA, Lead_SA, dan Admin.
    """
    # Validasi proyek ada
    result = await db.execute(
        select(Project).where(Project.id_project == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    # Validasi akses (titik keputusan bersama, TingkatAkses.HANDOVER) — SA yang ditugaskan,
    # Lead_SA, atau Admin. Sales (termasuk PIC) dan collaborator ditolak.
    await ensure_project_access(
        db,
        project,
        current_user,
        TingkatAkses.HANDOVER,
        pesan=(
            "Role Sales/Product tidak memiliki akses ke fitur handover."
            if current_user.role in PERAN_REQUESTER
            else "Anda hanya dapat melihat status handover proyek yang ditugaskan kepada Anda."
        ),
    )

    # Cek kesiapan
    readiness = await handover_service.check_handover_readiness(project_id, db)

    return success_response(
        data=readiness,
        message="Status kesiapan handover berhasil diambil.",
    )


@router.post(
    "/projects/{project_id}/handover-config",
    summary="Konfigurasi email PMO Lead dan Delivery Lead",
    description=(
        "Set email PMO Lead dan Delivery Lead pada proyek. "
        "Wajib dikonfigurasi sebelum handover bisa diproses. "
        "Hanya Lead_SA dan Admin yang bisa mengakses endpoint ini."
    ),
)
async def configure_handover(
    project_id: str,
    body: HandoverConfigInput,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Konfigurasi email PMO Lead dan Delivery Lead untuk proyek.
    Hanya bisa diakses oleh Lead_SA atau Admin (requirement 17.6).
    """
    # Validasi role — hanya Lead_SA dan Admin
    if not adalah_privileged(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Lead_SA atau Admin yang dapat mengkonfigurasi handover.",
        )

    # Cari proyek
    result = await db.execute(
        select(Project).where(Project.id_project == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    # Update email PMO dan Delivery
    project.pmo_lead_email = body.pmo_email
    project.delivery_lead_email = body.delivery_email
    project.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(project)

    logger.info(
        f"Handover config diperbarui untuk proyek {project_id}: "
        f"PMO={body.pmo_email}, Delivery={body.delivery_email} "
        f"oleh {current_user.email}"
    )

    return success_response(
        data={
            "id_project": project.id_project,
            "project_name": project.project_name,
            "pmo_lead_email": project.pmo_lead_email,
            "delivery_lead_email": project.delivery_lead_email,
        },
        message=(
            f"Email PMO Lead ({body.pmo_email}) dan Delivery Lead ({body.delivery_email}) "
            f"berhasil dikonfigurasi untuk proyek '{project.project_name}'."
        ),
    )


@router.post(
    "/projects/{project_id}/handover",
    summary="Trigger proses handover proyek",
    description=(
        "Memulai proses handover proyek ke PMO dan Delivery. "
        "Prasyarat: status Closed-Win, HLD Final, email PMO/Delivery sudah dikonfigurasi. "
        "Proses: buat folder Final_Deliverables, set permission, kirim notifikasi, update status."
    ),
)
async def trigger_handover(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger proses handover proyek.

    Bisa diakses oleh SA yang ditugaskan, Lead_SA, atau Admin.
    Flow:
    1. Validasi prasyarat
    2. Provisioning folder + permission GDrive
    3. Kirim notifikasi ke PMO + Delivery
    4. Update status → "Handover Complete"
    5. Catat audit log

    Requirements: 17.2, 17.3, 17.4, 17.5, 17.7
    """
    # Validasi proyek ada
    result = await db.execute(
        select(Project).where(Project.id_project == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    # Validasi akses (titik keputusan bersama, TingkatAkses.HANDOVER) — SA yang ditugaskan,
    # Lead_SA, atau Admin. Sebelum eksekusi handover (notifikasi, ubah status).
    await ensure_project_access(
        db,
        project,
        current_user,
        TingkatAkses.HANDOVER,
        pesan=(
            "Role Sales/Product tidak memiliki akses untuk memicu handover."
            if current_user.role in PERAN_REQUESTER
            else "Anda hanya dapat memicu handover proyek yang ditugaskan kepada Anda."
        ),
    )

    # Eksekusi handover
    try:
        handover_result = await handover_service.trigger_handover(
            project_id=project_id,
            performed_by=current_user.id,
            db=db,
        )
    except HandoverError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return success_response(
        data=handover_result,
        message=(
            f"Handover proyek '{handover_result['project_name']}' berhasil. "
            f"Status diubah ke 'Handover Complete'. "
            f"Notifikasi terkirim ke PMO ({handover_result['pmo_email']}) "
            f"dan Delivery ({handover_result['delivery_email']})."
        ),
    )
