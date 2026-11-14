"""
API generate ulang manual Requirement (Fase 5B, #34).

POST /projects/{id}/requirement/regenerate menandai proyek `pending` lalu menjalankan
generate di background (jalur yang sama dengan trigger otomatis). Dipakai juga sebagai
"coba lagi" saat status `failed`.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.documents import _to_response
from app.core.database import get_db
from app.core.dependencies import TingkatAkses, ensure_project_access, get_current_user
from app.models.document import Document
from app.models.project import Project
from app.models.user import User
from app.schemas.response import success_response
from app.services.status_proyek import pastikan_proyek_bisa_ditulis
from app.services.requirement_generator import (
    collect_sources,
    generate_pending_requirement,
    is_protected_requirement,
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

    await ensure_project_access(
        db,
        project,
        current_user,
        TingkatAkses.KELOLA_REQUIREMENT,
        pesan="Hanya SA yang ditugaskan, Lead SA, atau Admin yang dapat generate ulang Requirement.",
    )
    pastikan_proyek_bisa_ditulis(project)  # Closed/Lost read-only (409)

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

    # Atomik: hanya satu request yang berhasil memindahkan ready/failed -> pending. Cek di atas
    # hanya untuk pesan galat spesifik; pemenang ditentukan UPDATE bersyarat ini sehingga dua
    # request bersamaan tidak menjalankan dua generate.
    claimed = await db.execute(
        update(Project)
        .where(
            Project.id_project == project_id,
            Project.requirement_generation_status.in_(("ready", "failed")),
        )
        .values(requirement_generation_status="pending")
    )
    await db.commit()
    if claimed.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Requirement sedang dibuat. Tunggu hingga selesai.",
        )
    background_tasks.add_task(generate_pending_requirement, project_id, True)

    return success_response(
        data={"requirement_generation_status": "pending"},
        message="Generate ulang Requirement dimulai.",
    )


@router.post(
    "/projects/{project_id}/requirement/keep-version",
    summary="Pertahankan versi Requirement saya (SA ditugaskan, Lead_SA, Admin)",
    description=(
        "Memperbarui hash sumber tersimpan ke hash saat ini tanpa mengubah konten, sehingga "
        "banner 'sumber berubah' hilang. Hanya untuk Requirement yang di-override atau Final."
    ),
)
async def keep_requirement_version(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = (
        await db.execute(select(Project).where(Project.id_project == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )
    await ensure_project_access(
        db,
        project,
        current_user,
        TingkatAkses.KELOLA_REQUIREMENT,
        pesan=(
            "Hanya SA yang ditugaskan, Lead SA, atau Admin yang dapat mempertahankan versi "
            "Requirement."
        ),
    )
    pastikan_proyek_bisa_ditulis(project)  # Closed/Lost read-only (409)

    document = (
        await db.execute(
            select(Document)
            .where(Document.id_project == project_id, Document.doc_type == "Requirement")
            .with_for_update()
        )
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requirement untuk proyek ini belum tersedia.",
        )
    # Requirement biasa diperbarui otomatis; memajukan hash-nya akan membuat perubahan sumber
    # terlewat tanpa re-summarize.
    if not is_protected_requirement(document):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Requirement belum di-override dan belum Final; tidak ada versi yang dipertahankan.",
        )

    _, current_hash = await collect_sources(db, project)
    document.source_hash = current_hash
    document.updated_by = current_user.id
    await db.commit()

    return success_response(
        data=_to_response(document, source_changed=False),
        message="Versi Requirement Anda dipertahankan.",
    )
