"""Project-list API endpoints and their query filters."""

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.project import Project
from app.models.project_assignment import ProjectAssignment
from app.models.project_collaborator import ProjectCollaborator
from app.models.user import User
from app.schemas.project import ProjectListPageResponse
from app.schemas.response import ErrorResponse, SuccessResponse, success_response
from app.services.project_listing import build_project_list_page

router = APIRouter()


def _sa_ditugaskan_ke(user_id: uuid.UUID):
    """Kriteria "SA ditugaskan": SA utama atau SA tambahan (`ProjectAssignments`; ADR 0014)."""
    return or_(
        Project.assigned_sa == user_id,
        Project.id_project.in_(
            select(ProjectAssignment.id_project).where(ProjectAssignment.user_id == user_id)
        ),
    )


def _terlibat(user_id: uuid.UUID):
    """Kriteria `involved=me` (ADR 0014): user adalah `created_by`, `sales_pic`, `product_pic`,
    `lead_sa`, SA utama/tambahan, atau collaborator. Memakai subquery `IN` (bukan join), jadi
    project dengan banyak hubungan tidak menghasilkan baris ganda."""
    return or_(
        Project.created_by == user_id,
        Project.sales_pic == user_id,
        Project.product_pic == user_id,
        Project.lead_sa == user_id,
        _sa_ditugaskan_ke(user_id),
        Project.id_project.in_(
            select(ProjectCollaborator.id_project).where(ProjectCollaborator.user_id == user_id)
        ),
    )


_PARAM_ALIAS_PENSIUN = ("sales_pic", "assigned_to")


def _tolak_param_lama(request: Request) -> None:
    """Alias `sales_pic=me` / `assigned_to=me` dipensiunkan (#155), diganti `involved=me`.
    Tanpa penolakan, FastAPI mengabaikan param tak dikenal dan klien lama diam-diam menerima
    SEMUA proyek sebagai "proyek saya"; jadi dijawab 422 yang menyebut penggantinya."""
    dipakai = [k for k in _PARAM_ALIAS_PENSIUN if k in request.query_params]
    if dipakai:
        raise HTTPException(
            status_code=422,
            detail=f"Parameter {', '.join(dipakai)} sudah dihapus; gunakan involved=me.",
        )


@router.get(
    "",
    summary="Daftar proyek",
    description="Daftar proyek terfilter, terurut secara deterministik, dan dipaginasi.",
    response_model=SuccessResponse[ProjectListPageResponse],
    responses={
        401: {"model": ErrorResponse[dict[str, Any]]},
        422: {"model": ErrorResponse[list[dict[str, str]]]},
    },
)
async def list_projects(
    involved: Optional[str] = Query(
        None, description="Filter: 'me' untuk proyek yang melibatkan user login (semua peran)"
    ),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter berdasarkan status proyek"
    ),
    search: Optional[str] = Query(
        None, description="Cari nama proyek, customer, atau ID proyek"
    ),
    sort: Optional[str] = Query(
        "-updated_at", description="Sort: field name, prefix '-' untuk desc"
    ),
    page: int = Query(1, ge=1, description="Nomor halaman (1-based)"),
    page_size: int = Query(
        25,
        ge=1,
        le=100,
        description="Jumlah proyek per halaman (maksimal 100)",
    ),
    current_user: User = Depends(get_current_user),
    _: None = Depends(_tolak_param_lama),
    db: AsyncSession = Depends(get_db),
):
    """Ambil halaman daftar proyek dengan filter berdasarkan keterlibatan, status, dan pencarian.

    Sort tetap memakai nama field dan prefix `-` untuk descending. `id_project` menjadi
    pemecah seri ascending agar setiap halaman memiliki urutan stabil.
    """
    filters = []

    # Semua proyek dapat dilihat semua pengguna terautentikasi (ADR 0011); involved=me hanya
    # mempersempit daftar, tidak memperluas akses.
    if involved == "me":
        filters.append(_terlibat(current_user.id))

    if status_filter:
        filters.append(Project.status == status_filter)

    search_term = (search or "").strip()
    if search_term:
        pattern = f"%{search_term}%"
        filters.append(
            or_(
                Project.project_name.ilike(pattern),
                Project.customer_name.ilike(pattern),
                Project.id_project.ilike(pattern),
            )
        )

    data = await build_project_list_page(db, filters, sort, page, page_size)
    return success_response(
        data=data,
        message=f"Ditemukan {data['total']} proyek.",
    )


@router.get(
    "/status-summary",
    summary="Ringkasan jumlah proyek per status",
    description="Mengembalikan count proyek per status untuk overview dashboard.",
)
async def get_status_summary(
    involved: Optional[str] = Query(
        None, description="Filter: 'me' untuk proyek yang melibatkan user login (semua peran)"
    ),
    current_user: User = Depends(get_current_user),
    _: None = Depends(_tolak_param_lama),
    db: AsyncSession = Depends(get_db),
):
    """Hitung jumlah proyek per status, dengan filter berbasis role."""
    query = select(Project.status, func.count(Project.id_project))

    # Semua proyek dapat dilihat semua pengguna terautentikasi (sama seperti list_projects).
    # Penyempit opsional dari query param
    if involved == "me":
        query = query.where(_terlibat(current_user.id))

    result = await db.execute(
        query.group_by(Project.status).order_by(func.count(Project.id_project).desc())
    )
    rows = result.all()

    summary = [{"status": row[0], "count": row[1]} for row in rows]

    return success_response(
        data=summary,
        message=f"Ringkasan {len(summary)} status.",
    )
