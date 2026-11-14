"""
API endpoints untuk manajemen Subtask (work item assignable per proyek).

Subtask adalah konsep work item yang bisa ditugaskan ke SA dalam suatu proyek,
berbeda dengan ActivityCategory (activity_logs.subtask_category).

Endpoints:
- POST   /projects/{project_id}/subtasks        — buat subtask (Lead_SA/Admin)
- GET    /projects/{project_id}/subtasks        — daftar subtask proyek (read-set)
- PATCH  /subtasks/{id_subtask}                 — ubah description/due_date/estimate_hours
                                                  (owner SA / privileged)
- PATCH  /subtasks/{id_subtask}/status          — ubah status (owner SA / privileged)
- PATCH  /subtasks/{id_subtask}/assign          — assign/reassign (Lead_SA/Admin)
- DELETE /subtasks/{id_subtask}                 — hapus subtask (Lead_SA/Admin)
- GET    /subtasks/saya                         — "Tugas saya": subtask milik user lintas project
"""

import logging
import random
import string
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    PERAN_DAPAT_DITUGASKAN,
    PeranUser,
    adalah_privileged,
    adalah_sa_ditugaskan,
    TingkatAkses,
    ensure_project_access,
    get_current_user,
)
from app.core import status as status_konst
from app.models.project import Project
from app.models.subtask import Subtask
from app.models.user import User
from app.schemas.response import success_response
from app.services.status_proyek import majukan_ke_in_progress, pastikan_proyek_bisa_ditulis
from app.schemas.subtask import (
    SubtaskAssignRequest,
    SubtaskCreateRequest,
    SubtaskListResponse,
    SubtaskResponse,
    SubtaskUpdateRequest,
    SubtaskUpdateStatusRequest,
    TugasSayaListResponse,
    TugasSayaResponse,
)
from app.services.subtask import subtask_terlambat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Subtasks"])

# Router terpisah untuk sumber daya milik user lintas project. Prefix `/subtasks` tidak
# berpapasan dengan `/projects/{project_id}`, jadi tidak ada risiko route tertangkap parameter.
router_saya = APIRouter(prefix="/subtasks", tags=["Subtasks"])

# Status project yang disembunyikan dari "Tugas saya" secara default (pekerjaan sudah berakhir).
STATUS_PROJECT_DISEMBUNYIKAN = (status_konst.CLOSED, status_konst.LOST)

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


async def _pastikan_boleh_mengubah(
    subtask: Subtask, project: Project, current_user: User, db: AsyncSession
) -> None:
    """
    Hak ubah subtask: Lead_SA/Admin, atau SA pemilik yang masih berhak TULIS ke proyeknya
    (403 bila tidak); lalu proyek tidak boleh read-only (409). Dipakai ubah status dan field.
    """
    is_privileged = adalah_privileged(current_user)
    is_owner = subtask.assigned_sa == current_user.id
    if not (is_privileged or is_owner):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki akses untuk mengubah subtask ini.",
        )
    # Pemilik non-privileged juga harus masih berhak TULIS ke proyek subtask ini (SA yang sudah
    # dilepas dari proyek atau menjadi viewer ditolak). Lead_SA/Admin selalu lolos di sini.
    if not is_privileged:
        await ensure_project_access(db, project, current_user, TingkatAkses.TULIS)
    pastikan_proyek_bisa_ditulis(project)


async def _nama_assignee(subtask: Subtask, db: AsyncSession) -> str | None:
    """Nama user assignee subtask, atau None bila belum ditugaskan."""
    if subtask.assigned_sa is None:
        return None
    sa_user = (
        await db.execute(select(User).where(User.id == subtask.assigned_sa))
    ).scalar_one_or_none()
    return sa_user.name if sa_user else None


def _subtask_response(subtask: Subtask, assigned_sa_name: str | None = None) -> dict:
    """Bangun dict response dari instance Subtask."""
    return SubtaskResponse(
        id_subtask=subtask.id_subtask,
        id_project=subtask.id_project,
        title=subtask.title,
        status=subtask.status,
        assigned_sa=subtask.assigned_sa,
        assigned_sa_name=assigned_sa_name,
        description=subtask.description,
        due_date=subtask.due_date,
        estimate_hours=subtask.estimate_hours,
        terlambat=subtask_terlambat(subtask.due_date, subtask.status),
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
    project = await _verify_project_exists(project_id, db)
    pastikan_proyek_bisa_ditulis(project)

    subtask = Subtask(
        id_subtask=_generate_subtask_id(),
        id_project=project_id,
        title=body.title,
        status="open",
        description=body.description,
        due_date=body.due_date,
        estimate_hours=body.estimate_hours,
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
    "/subtasks/{id_subtask}",
    summary="Ubah description, due_date, dan estimate_hours subtask",
    description=(
        "Perubahan parsial: field yang tidak dikirim tidak diubah, null mengosongkan field. "
        "Hanya SA pemilik subtask yang masih berhak tulis ke proyeknya, atau Lead_SA/Admin."
    ),
)
async def update_subtask_fields(
    id_subtask: str,
    body: SubtaskUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ubah field kaya subtask (owner SA atau privileged; hak sama dengan ubah status)."""
    subtask = await _load_subtask(id_subtask, db)
    project = await _verify_project_exists(subtask.id_project, db)
    await _pastikan_boleh_mengubah(subtask, project, current_user, db)

    for nama in body.model_fields_set:
        setattr(subtask, nama, getattr(body, nama))
    subtask.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(subtask)

    return success_response(
        data=_subtask_response(subtask, await _nama_assignee(subtask, db)),
        message="Subtask berhasil diperbarui.",
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

    await _pastikan_boleh_mengubah(subtask, project, current_user, db)

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
    # Subtask `in_progress` pertama memindahkan proyek `Assigned` → `In Progress`.
    if body.status == "in_progress":
        majukan_ke_in_progress(db, project, current_user.id, "subtask")
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
    pastikan_proyek_bisa_ditulis(await _verify_project_exists(subtask.id_project, db))

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
        if sa_user.role not in PERAN_DAPAT_DITUGASKAN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"User '{sa_user.name}' memiliki role '{sa_user.role}', bukan 'SA' atau "
                    f"'Lead_SA'. Hanya SA atau Lead_SA yang bisa ditugaskan ke subtask."
                ),
            )
        # Assignee: SA project (utama/tambahan) atau Lead_SA mana pun (ADR 0014).
        project = await _verify_project_exists(subtask.id_project, db)
        if sa_user.role != PeranUser.LEAD_SA and not await adalah_sa_ditugaskan(
            db, project, sa_user
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"User '{sa_user.name}' bukan anggota tim SA proyek ini. Tambahkan ke tim SA "
                    f"lebih dulu, atau pilih SA utama/tambahan atau Lead_SA."
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
    pastikan_proyek_bisa_ditulis(await _verify_project_exists(subtask.id_project, db))

    await db.delete(subtask)
    await db.commit()

    logger.info(f"Subtask {id_subtask} dihapus oleh {current_user.email}")

    return success_response(
        data=None,
        message="Subtask berhasil dihapus.",
    )


@router_saya.get(
    "/saya",
    summary="Daftar 'Tugas saya' lintas project",
    description=(
        "Semua subtask yang ditugaskan ke user login, lintas project, urut due_date naik "
        "(due_date kosong di akhir). Project soft-deleted tidak pernah ikut; project Closed/Lost "
        "ikut hanya dengan `sertakan_project_selesai=true`. Filter `status` boleh diulang; "
        "default semua status."
    ),
)
async def daftar_tugas_saya(
    status_filter: Annotated[
        list[Literal["open", "in_progress", "done"]] | None,
        Query(alias="status", description="Filter status subtask; boleh diulang"),
    ] = None,
    sertakan_project_selesai: Annotated[
        bool, Query(description="Sertakan subtask dari project Closed/Lost")
    ] = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Subtask milik user login (hanya data sendiri; tidak ada parameter user lain)."""
    # Filter soft delete pada Project sudah otomatis oleh listener `_filter_soft_deleted`;
    # kondisi eksplisit di bawah menjaga perilaku tetap benar bila listener berubah.
    query = (
        select(Subtask, Project)
        .join(Project, Project.id_project == Subtask.id_project)
        .where(Subtask.assigned_sa == current_user.id, Project.deleted_at.is_(None))
    )
    if status_filter:
        query = query.where(Subtask.status.in_(status_filter))
    if not sertakan_project_selesai:
        query = query.where(Project.status.notin_(STATUS_PROJECT_DISEMBUNYIKAN))
    query = query.order_by(
        Subtask.due_date.asc().nulls_last(), Subtask.created_at, Subtask.id_subtask
    )

    baris = (await db.execute(query)).all()
    items = [
        TugasSayaResponse(
            **SubtaskResponse(
                id_subtask=st.id_subtask,
                id_project=st.id_project,
                title=st.title,
                status=st.status,
                assigned_sa=st.assigned_sa,
                assigned_sa_name=current_user.name,
                description=st.description,
                due_date=st.due_date,
                estimate_hours=st.estimate_hours,
                terlambat=subtask_terlambat(st.due_date, st.status),
                created_at=st.created_at,
                updated_at=st.updated_at,
            ).model_dump(),
            project_name=pr.project_name,
            customer_name=pr.customer_name,
            project_status=pr.status,
        )
        for st, pr in baris
    ]
    data = TugasSayaListResponse(items=items, total=len(items))
    return success_response(
        data=data.model_dump(mode="json"),
        message=f"Ditemukan {len(items)} tugas.",
    )
