"""
API endpoints untuk manajemen Collaborator pada proyek.
SA maupun Sales bisa menambahkan peer atau atasan sebagai kolaborator
untuk melihat proyek (viewer) atau menambah activity log (contributor).
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    PERAN_PRIVILEGED,
    PeranKolaborator,
    PeranUser,
    TingkatAkses,
    ensure_project_access,
    get_current_user,
)
from app.models.project import Project
from app.models.project_collaborator import ProjectCollaborator
from app.models.user import User
from app.schemas.collaborator import (
    CollaboratorAddRequest,
    CollaboratorListResponse,
    CollaboratorResponse,
)
from app.schemas.response import error_response, success_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Collaborators"])


async def _verify_project_exists(project_id: str, db: AsyncSession) -> Project:
    """Validasi proyek ada, return Project instance."""
    result = await db.execute(
        select(Project).where(Project.id_project == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )
    return project


@router.get(
    "/{project_id}/collaborators",
    summary="Daftar kolaborator proyek",
    description="Mengambil daftar kolaborator yang ditag ke suatu proyek.",
)
async def list_collaborators(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ambil daftar kolaborator proyek.

    Akses:
    - Lead_SA / Admin: selalu bisa
    - SA yang di-assign, Sales PIC, atau kolaborator existing: bisa
    """
    project = await _verify_project_exists(project_id, db)

    # Titik keputusan bersama (BACA): Lead_SA/Admin, Sales PIC, SA ditugaskan, collaborator.
    await ensure_project_access(db, project, current_user, TingkatAkses.BACA)

    # Query kolaborator + join user info
    result = await db.execute(
        select(ProjectCollaborator)
        .where(ProjectCollaborator.id_project == project_id)
        .order_by(ProjectCollaborator.created_at.desc())
    )
    collaborators = result.scalars().all()

    # Enrich dengan data user
    items: list[dict] = []
    for collab in collaborators:
        user_result = await db.execute(
            select(User).where(User.id == collab.user_id)
        )
        collab_user = user_result.scalar_one_or_none()

        adder_result = await db.execute(
            select(User).where(User.id == collab.added_by)
        )
        adder_user = adder_result.scalar_one_or_none()

        items.append(
            CollaboratorResponse(
                id=collab.id,
                user_id=collab.user_id,
                user_name=collab_user.name if collab_user else "Unknown",
                user_email=collab_user.email if collab_user else "unknown",
                user_role=collab_user.role if collab_user else "Unknown",
                role=collab.role,
                added_by_name=adder_user.name if adder_user else "Unknown",
                created_at=collab.created_at,
            ).model_dump(mode="json")
        )

    data = CollaboratorListResponse(items=items, total=len(items))
    return success_response(
        data=data.model_dump(mode="json"),
        message=f"Ditemukan {len(items)} kolaborator.",
    )


@router.post(
    "/{project_id}/collaborators",
    summary="Tambah kolaborator ke proyek",
    description=(
        "Menambahkan user sebagai kolaborator proyek. "
        "Hanya Lead_SA, Admin, SA ditugaskan, atau Sales PIC proyek itu yang bisa menambahkan "
        "kolaborator. "
        "Role: 'viewer' (lihat saja) atau 'contributor' (bisa tambah activity log)."
    ),
)
async def add_collaborator(
    project_id: str,
    body: CollaboratorAddRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Tambahkan kolaborator ke proyek.

    Flow:
    1. Validasi proyek ada
    2. Validasi akses penambah (Lead_SA/Admin/SA ditugaskan/Sales PIC)
    3. Validasi user yang akan ditag ada
    4. Validasi role kolaborator (viewer / contributor)
    5. Cek duplikasi
    6. Simpan ke database
    """
    project = await _verify_project_exists(project_id, db)

    # Gerbang peran kasar: hanya SA, Sales, Lead_SA, Admin yang bisa add collaborator
    allowed_roles = ("SA", "Sales", "Lead_SA", "Admin")
    if current_user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki izin menambahkan kolaborator.",
        )

    # Relasi ke proyek: hanya Lead_SA/Admin, SA ditugaskan, atau Sales PIC proyek ini.
    # Dicek sebelum mencari user target agar pihak luar tidak bisa menyelidiki user lain.
    await ensure_project_access(db, project, current_user, TingkatAkses.TAMBAH_KOLABORATOR)

    # Validasi user yang akan ditag ada
    user_result = await db.execute(
        select(User).where(User.id == body.user_id)
    )
    target_user = user_result.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User dengan ID '{body.user_id}' tidak ditemukan.",
        )

    # === Aturan role penambah terhadap role target ===
    # - Sales hanya bisa menambahkan sesama Sales
    # - SA hanya bisa menambahkan sesama SA
    # - Lead_SA / Admin bisa menambahkan role apa pun
    if current_user.role == "Sales" and target_user.role != "Sales":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sales hanya dapat menambahkan sesama Sales sebagai kolaborator.",
        )
    if current_user.role == "SA" and target_user.role != "SA":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SA hanya dapat menambahkan sesama SA sebagai kolaborator.",
        )

    # Validasi role kolaborator
    if body.role not in tuple(PeranKolaborator):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Role kolaborator harus 'viewer' atau 'contributor'.",
        )

    # Contributor harus SA (karena hanya SA yang bisa buat activity log)
    if body.role == PeranKolaborator.CONTRIBUTOR and target_user.role not in (
        PeranUser.SA,
        *PERAN_PRIVILEGED,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hanya SA yang bisa menjadi contributor (menambah activity log).",
        )

    # Cek duplikasi
    existing = await db.execute(
        select(ProjectCollaborator).where(
            ProjectCollaborator.id_project == project_id,
            ProjectCollaborator.user_id == body.user_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User '{target_user.name}' sudah menjadi kolaborator proyek ini.",
        )

    # Jangan bisa tag diri sendiri
    if body.user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tidak bisa menambahkan diri sendiri sebagai kolaborator.",
        )

    # Simpan
    collaborator = ProjectCollaborator(
        id_project=project_id,
        user_id=body.user_id,
        role=body.role,
        added_by=current_user.id,
    )
    db.add(collaborator)
    await db.commit()
    await db.refresh(collaborator)

    logger.info(
        f"Kolaborator ditambahkan: proyek={project_id}, user={target_user.email}, "
        f"role={body.role}, oleh={current_user.email}"
    )

    return success_response(
        data={
            "id": str(collaborator.id),
            "user_id": str(collaborator.user_id),
            "user_name": target_user.name,
            "user_email": target_user.email,
            "role": body.role,
        },
        message=f"'{target_user.name}' berhasil ditambahkan sebagai kolaborator ({body.role}).",
    )


@router.delete(
    "/{project_id}/collaborators/{user_id}",
    summary="Hapus kolaborator dari proyek",
    description="Menghapus kolaborator dari proyek. Hanya Lead_SA, Admin, atau yang menambahkan yang bisa hapus.",
)
async def remove_collaborator(
    project_id: str,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Hapus kolaborator dari proyek.

    Akses:
    - Lead_SA / Admin: selalu bisa
    - User yang menambahkan kolaborator (added_by): bisa
    - Sales PIC / assigned SA: bisa
    """
    project = await _verify_project_exists(project_id, db)

    # Titik keputusan bersama (HAPUS_KOLABORATOR): Lead_SA/Admin, Sales PIC, SA ditugaskan.
    await ensure_project_access(
        db,
        project,
        current_user,
        TingkatAkses.HAPUS_KOLABORATOR,
        pesan="Anda tidak memiliki izin menghapus kolaborator.",
    )

    # Cari kolaborator
    collab_result = await db.execute(
        select(ProjectCollaborator).where(
            ProjectCollaborator.id_project == project_id,
            ProjectCollaborator.user_id == user_id,
        )
    )
    collaborator = collab_result.scalar_one_or_none()

    if collaborator is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kolaborator tidak ditemukan.",
        )

    # Hapus
    target_user_result = await db.execute(
        select(User).where(User.id == user_id)
    )
    target_user = target_user_result.scalar_one_or_none()
    target_name = target_user.name if target_user else str(user_id)

    await db.delete(collaborator)
    await db.commit()

    logger.info(
        f"Kolaborator dihapus: proyek={project_id}, user={user_id}, "
        f"oleh={current_user.email}"
    )

    return success_response(
        data=None,
        message=f"'{target_name}' berhasil dihapus dari kolaborator proyek.",
    )


@router.get(
    "/users/search",
    summary="Cari user untuk autocomplete kolaborator",
    description="Cari user berdasarkan nama atau email. Digunakan untuk autocomplete saat menambah kolaborator.",
)
async def search_users(
    q: str = Query(..., min_length=2, description="Kata kunci pencarian (nama atau email)"),
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Cari user berdasarkan nama atau email (case-insensitive).
    Mengembalikan max `limit` hasil.
    """
    search_pattern = f"%{q}%"

    result = await db.execute(
        select(User)
        .where(
            (User.name.ilike(search_pattern)) | (User.email.ilike(search_pattern))
        )
        .where(User.id != current_user.id)  # Exclude diri sendiri
        .order_by(User.name)
        .limit(limit)
    )
    users = result.scalars().all()

    data = [
        {
            "id": str(u.id),
            "name": u.name,
            "email": u.email,
            "role": u.role,
        }
        for u in users
    ]

    return success_response(
        data=data,
        message=f"Ditemukan {len(data)} user.",
    )
