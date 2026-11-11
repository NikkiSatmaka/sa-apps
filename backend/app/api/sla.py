"""
API endpoints untuk SLA Timer — status check dan manual trigger processing.

Menyediakan:
- GET /api/v1/projects/{id}/sla-status — Cek status SLA proyek
- POST /api/v1/sla/process — Manual trigger untuk SLA processing (admin/cron)

Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import ensure_project_access, get_current_user
from app.models.project import Project
from app.models.user import User
from app.schemas.response import success_response
from app.services.sla_timer import sla_timer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SLA Timer"])


@router.get(
    "/projects/{project_id}/sla-status",
    summary="Cek status SLA untuk sebuah proyek",
    description=(
        "Mengembalikan status SLA saat ini: badge (green/yellow/red), "
        "days_elapsed, is_locked, dan apakah timer masih aktif."
    ),
)
async def get_sla_status(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ambil status SLA untuk proyek tertentu.

    Returns:
        - status: green/yellow/red
        - days_elapsed: jumlah hari sejak assignment
        - is_locked: apakah folder Solutions di-lock
        - is_active: apakah timer masih berjalan
    """
    # Urutan: proyek ada (404) -> akses BACA (403) -> baru tracker. check_sla_status
    # menulis (hitung ulang + commit), jadi harus setelah cek akses.
    project = (
        await db.execute(select(Project).where(Project.id_project == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )
    await ensure_project_access(db, project, current_user)

    sla_status = await sla_timer.check_sla_status(
        project_id=project_id, db=db
    )

    if sla_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"SLA tracker untuk proyek '{project_id}' tidak ditemukan. "
                f"Timer dimulai saat proyek di-assign ke SA."
            ),
        )

    return success_response(
        data=sla_status,
        message=f"Status SLA proyek: {sla_status['status']} (H+{sla_status['days_elapsed']})",
    )


@router.post(
    "/sla/process",
    summary="Trigger SLA processing untuk semua proyek aktif",
    description=(
        "Manual trigger untuk memproses SLA semua proyek yang timer-nya masih aktif. "
        "Biasanya dipanggil oleh cron job harian atau admin. "
        "Hanya Admin atau Lead_SA yang boleh memicu endpoint ini."
    ),
)
async def process_sla(
    current_user: User = Depends(get_current_user),
):
    """
    Proses SLA untuk semua proyek aktif.

    Aksi yang di-trigger:
    - H+3: Kirim reminder ke Sales
    - H+5: Kirim eskalasi ke Sales Manager + auto-lock folder Solutions

    Hanya bisa diakses oleh Admin atau Lead_SA.
    """
    # Hanya Admin atau Lead_SA yang boleh trigger manual
    if current_user.role not in ("Admin", "Lead_SA"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Admin atau Lead_SA yang dapat memicu SLA processing.",
        )

    logger.info(
        f"SLA processing dipicu oleh {current_user.email} "
        f"(role: {current_user.role})"
    )

    stats = await sla_timer.process_sla_actions()

    return success_response(
        data=stats,
        message=(
            f"SLA processing selesai. "
            f"{stats['total_checked']} proyek dicek, "
            f"{stats['reminders_sent']} reminder dikirim, "
            f"{stats['escalations_sent']} eskalasi dikirim."
        ),
    )
