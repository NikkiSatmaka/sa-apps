"""
API komentar project (issue #125, spec §2.0, §2.5, A5).

- POST /projects/{project_id}/comments: tulis komentar (yang ditugaskan, Lead_SA, Admin).
- GET  /projects/{project_id}/comments: thread komentar, kronologis naik (semua pengguna).

Komentar append-only (tanpa edit/hapus), terpisah dari Project Story. Proyek soft-deleted atau
tidak ada → 404; proyek `Closed`/`Lost` menolak tulis dengan 409 (helper read-only).
"""

import logging
import random
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import TingkatAkses, ensure_project_access, get_current_user
from app.models.project import Project
from app.models.project_comment import ProjectComment
from app.models.user import User
from app.schemas.project_comment import (
    KomentarCreateRequest,
    KomentarListResponse,
    KomentarResponse,
)
from app.schemas.response import success_response
from app.services.status_proyek import pastikan_proyek_bisa_ditulis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Komentar Project"])


def _generate_comment_id() -> str:
    """ID komentar: CMT-{YYYYMMDD}-{6 karakter acak} (pola `_generate_subtask_id`)."""
    tanggal = datetime.now(timezone.utc).strftime("%Y%m%d")
    acak = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"CMT-{tanggal}-{acak}"


async def _muat_proyek(project_id: str, db: AsyncSession) -> Project:
    """Proyek aktif atau 404 (soft-deleted dianggap tidak ada)."""
    proyek = (
        await db.execute(select(Project).where(Project.id_project == project_id))
    ).scalar_one_or_none()
    if proyek is None or proyek.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )
    return proyek


def _respons(komentar: ProjectComment, penulis: User | None) -> dict:
    return KomentarResponse(
        id_comment=komentar.id_comment,
        id_project=komentar.id_project,
        author_id=komentar.author_id,
        author_name=penulis.name if penulis else None,
        author_role=penulis.role if penulis else None,
        body=komentar.body,
        created_at=komentar.created_at,
    ).model_dump(mode="json")


@router.get(
    "/{project_id}/comments",
    summary="Daftar komentar project",
    description="Thread komentar proyek, kronologis naik. Terbuka untuk semua pengguna login.",
)
async def daftar_komentar(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proyek = await _muat_proyek(project_id, db)
    await ensure_project_access(db, proyek, current_user, TingkatAkses.BACA)

    baris = (
        await db.execute(
            select(ProjectComment, User)
            .join(User, User.id == ProjectComment.author_id, isouter=True)
            .where(ProjectComment.id_project == project_id)
            .order_by(ProjectComment.created_at, ProjectComment.id_comment)
        )
    ).all()
    items = [_respons(k, u) for k, u in baris]
    return success_response(
        data=KomentarListResponse(items=items, total=len(items)).model_dump(mode="json"),
        message=f"Ditemukan {len(items)} komentar.",
    )


@router.post(
    "/{project_id}/comments",
    status_code=status.HTTP_201_CREATED,
    summary="Tulis komentar project",
    description=(
        "Orang yang ditugaskan di proyek (Sales/Product PIC, SA utama/tambahan, collaborator "
        "contributor), Lead_SA, dan Admin. Ditolak 409 pada proyek Closed/Lost."
    ),
)
async def tulis_komentar(
    project_id: str,
    body: KomentarCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proyek = await _muat_proyek(project_id, db)
    await ensure_project_access(db, proyek, current_user, TingkatAkses.KOMENTAR)
    pastikan_proyek_bisa_ditulis(proyek)

    komentar = ProjectComment(
        id_comment=_generate_comment_id(),
        id_project=project_id,
        author_id=current_user.id,
        body=body.body,
        created_at=datetime.now(timezone.utc),
    )
    db.add(komentar)
    await db.commit()
    await db.refresh(komentar)

    logger.info(f"Komentar {komentar.id_comment} ditulis di {project_id} oleh {current_user.email}")
    return success_response(data=_respons(komentar, current_user), message="Komentar ditambahkan.")
