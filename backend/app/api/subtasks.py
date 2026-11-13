"""
API endpoints untuk manajemen Subtask (work item assignable per proyek).

Subtask adalah konsep work item yang bisa ditugaskan ke SA dalam suatu proyek,
berbeda dengan ActivityCategory (activity_logs.subtask_category).

Endpoints:
- POST   /projects/{project_id}/subtasks        — buat subtask (Lead_SA/Admin)
- GET    /projects/{project_id}/subtasks        — daftar subtask proyek (read-set)
- PATCH  /subtasks/{id_subtask}/status          — ubah status (owner SA / privileged)
- PATCH  /subtasks/{id_subtask}/assign          — assign/reassign (Lead_SA/Admin)
- DELETE /subtasks/{id_subtask}                 — hapus subtask (Lead_SA/Admin)
"""

import logging
import random
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    adalah_privileged,
    TingkatAkses,
    ensure_project_access,
    get_current_user,
)
from app.models.project import Project
from app.models.subtask import Subtask
from app.models.user import User
from app.schemas.response import success_response
from app.schemas.subtask import (
    SubtaskAssignRequest,
    SubtaskCreateRequest,
    SubtaskListResponse,
    SubtaskResponse,
    SubtaskUpdateStatusRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Subtasks"])

# Status subtask yang valid (selaras dengan CheckConstraint di model)
VALID_SUBTASK_STATUSES = ("open", "in_progress", "done")


def _generate_subtask_id() -> str:
    """
    Generate ID subtask unik dengan format SUB-{YYYYMMDD}-{random 6 chars}.
    Mengikuti pola _generate_project_id.
    """
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"SUB-{date_part}-{random_part}"


def _require_lead_sa(current_user: User) -> None:
    """Validasi bahwa user saat ini memiliki role Lead_SA atau Admin."""
    if not adalah_privileged(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Lead_SA atau Admin yang dapat melakukan operasi ini.",
        )


async def _verify_project_exists(project_id: str, db: AsyncSession) -> Project:
    """Validasi proyek ada, return Project instance (404 bila tidak ada)."""
    result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )
    return project


async def _load_subtask(id_subtask: str, db: AsyncSession) -> Subtask:
    """Load subtask by primary key (404 bila tidak ada)."""
    result = await db.execute(select(Subtask).where(Subtask.id_subtask == id_subtask))
    subtask = result.scalar_one_or_none()
    if subtask is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Subtask dengan ID '{id_subtask}' tidak ditemukan.",
        )
    return subtask


def _subtask_response(subtask: Subtask, assigned_sa_name: str | None = None) -> dict:
    """Bangun dict response dari instance Subtask."""
    return SubtaskResponse(
        id_subtask=subtask.id_subtask,
        id_project=subtask.id_project,
        title=subtask.title,
        status=subtask.status,
        assigned_sa=subtask.assigned_sa,
        assigned_sa_name=assigned_sa_name,
        created_at=subtask.created_at,
        updated_at=subtask.updated_at,
    ).model_dump(mode="json")


@router.post(
    "/{project_id}/subtasks",
    status_code=status.HTTP_201_CREATED,
    summary="Buat subtask baru",
    description="Membuat work item subtask pada proyek. Hanya Lead_SA atau Admin.",
)
async def create_subtask(
    project_id: str,
    body: SubtaskCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Buat subtask baru untuk proyek tertentu (Lead_SA/Admin)."""
    _require_lead_sa(current_user)
    await _verify_project_exists(project_id, db)

    subtask = Subtask(
        id_subtask=_generate_subtask_id(),
        id_project=project_id,
        title=body.title,
        status="open",
    )
    db.add(subtask)
    await db.commit()
    await db.refresh(subtask)

    logger.info(
        f"Subtask {subtask.id_subtask} dibuat untuk proyek {project_id} "
        f"oleh {current_user.email}"
    )

    return success_response(
        data=_subtask_response(subtask),
        message=f"Subtask '{subtask.title}' berhasil dibuat.",
    )


@router.get(
    "/{project_id}/subtasks",
    summary="Daftar subtask proyek",
    description="Mengambil daftar subtask suatu proyek. Akses sesuai read-set proyek.",
)
async def list_subtasks(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Daftar subtask proyek (read-set termasuk collaborator)."""
    project = await _verify_project_exists(project_id, db)
    await ensure_project_access(db, project, current_user)

    result = await db.execute(
        select(Subtask)
        .where(Subtask.id_project == project_id)
        .order_by(Subtask.created_at)
    )
    subtasks = result.scalars().all()

    items: list[dict] = []
    for subtask in subtasks:
        assigned_sa_name = None
        if subtask.assigned_sa is not None:
            user_result = await db.execute(
                select(User).where(User.id == subtask.assigned_sa)
            )
            sa_user = user_result.scalar_one_or_none()
            assigned_sa_name = sa_user.name if sa_user else None
        items.append(_subtask_response(subtask, assigned_sa_name))

    data = SubtaskListResponse(items=items, total=len(items))
    return success_response(
        data=data.model_dump(mode="json"),
        message=f"Ditemukan {len(items)} subtask.",
    )


@router.patch(
    "/subtasks/{id_subtask}/status",
    summary="Ubah status subtask",
    description=(
        "Mengubah status subtask (open/in_progress/done). "
        "Hanya SA pemilik subtask yang masih berhak tulis ke proyeknya, atau Lead_SA/Admin."
    ),
)
async def update_subtask_status(
    id_subtask: str,
    body: SubtaskUpdateStatusRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ubah status subtask (owner SA atau privileged)."""
    subtask = await _load_subtask(id_subtask, db)
    # Pastikan proyek induk ada (konsistensi FK / validasi keberadaan).
    project = await _verify_project_exists(subtask.id_project, db)

    is_privileged = adalah_privileged(current_user)
    is_owner = subtask.assigned_sa == current_user.id
    if not (is_privileged or is_owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki akses untuk mengubah status subtask ini.",
        )
    # Pemilik non-privileged juga harus masih berhak TULIS ke proyek subtask ini (SA yang sudah
    # dilepas dari proyek atau menjadi viewer ditolak). Lead_SA/Admin selalu lolos di sini.
    if not is_privileged:
        await ensure_project_access(db, project, current_user, TingkatAkses.TULIS)

    if body.status not in VALID_SUBTASK_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Status '{body.status}' tidak valid. "
                f"Pilihan: {', '.join(VALID_SUBTASK_STATUSES)}."
            ),
        )

    subtask.status = body.status
    subtask.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(subtask)

    return success_response(
        data=_subtask_response(subtask),
        message=f"Status subtask diubah menjadi '{subtask.status}'.",
    )


@router.patch(
    "/subtasks/{id_subtask}/assign",
    summary="Assign/reassign subtask ke SA",
    description=(
        "Menugaskan subtask ke SA, atau melepas penugasan bila assigned_sa null. "
        "Hanya Lead_SA atau Admin. Reassign memakai jalur yang sama."
    ),
)
async def assign_subtask(
    id_subtask: str,
    body: SubtaskAssignRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign/reassign subtask ke SA (Lead_SA/Admin)."""
    _require_lead_sa(current_user)
    subtask = await _load_subtask(id_subtask, db)

    assigned_sa_name = None
    if body.assigned_sa is not None:
        user_result = await db.execute(
            select(User).where(User.id == body.assigned_sa)
        )
        sa_user = user_result.scalar_one_or_none()
        if sa_user is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User dengan ID '{body.assigned_sa}' tidak ditemukan.",
            )
        if sa_user.role != "SA":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"User '{sa_user.name}' memiliki role '{sa_user.role}', bukan 'SA'. "
                    f"Hanya user dengan role SA yang bisa ditugaskan ke subtask."
                ),
            )
        assigned_sa_name = sa_user.name

    subtask.assigned_sa = body.assigned_sa
    subtask.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(subtask)

    return success_response(
        data=_subtask_response(subtask, assigned_sa_name),
        message="Penugasan subtask berhasil diperbarui.",
    )


@router.delete(
    "/subtasks/{id_subtask}",
    summary="Hapus subtask",
    description="Menghapus subtask. Hanya Lead_SA atau Admin.",
)
async def delete_subtask(
    id_subtask: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hapus subtask (Lead_SA/Admin)."""
    _require_lead_sa(current_user)
    subtask = await _load_subtask(id_subtask, db)

    await db.delete(subtask)
    await db.commit()

    logger.info(f"Subtask {id_subtask} dihapus oleh {current_user.email}")

    return success_response(
        data=None,
        message="Subtask berhasil dihapus.",
    )
