"""
API endpoints untuk DQ Number input dan document gating.
Menangani input DQ Number oleh Sales, proteksi edit oleh Lead_SA,
dan gating akses dokumen Solutions berdasarkan DQ + status dokumen.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    TingkatAkses,
    adalah_sales_terbatas,
    ensure_project_access,
    get_current_user,
)
from app.models.document import Document
from app.models.project import Project
from app.models.user import User
from app.schemas.dq_number import DQNumberInput, DQNumberResponse, SolutionsDocumentResponse
from app.schemas.response import error_response, success_response
from app.services.dq_akses import (
    FOLDER_SOLUTIONS,
    hentikan_timer_bila_pertama,
    saring_dokumen_terlihat,
    terapkan_dq,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["DQ Number"])


@router.patch(
    "/projects/{project_id}/dq-number",
    summary="Input atau update DQ Number pada proyek",
    description=(
        "Sales PIC proyek itu, Lead_SA, dan Admin menginput DQ Number untuk proyek yang "
        "berstatus 'Assigned' atau lebih. Setelah DQ tersimpan, Sales tidak bisa mengedit. "
        "Status proyek berubah menjadi 'Ready' saat DQ pertama kali diinput."
    ),
)
async def update_dq_number(
    project_id: str,
    body: DQNumberInput,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Input/update DQ Number pada proyek.

    Rules:
    1. Proyek harus ada dan berstatus minimal "Assigned"
    2. Jika DQ sudah ada dan user = Sales → tolak (403)
    3. Jika DQ sudah ada dan user = Lead_SA → izinkan edit
    4. Saat DQ pertama kali diinput → status berubah ke "Ready"
    """
    # === 1. Validasi proyek ada ===
    result = await db.execute(
        select(Project).where(Project.id_project == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    # Aturan + mutasi DQ dipakai bersama dengan PATCH /projects/{id} (app.services.dq_akses):
    # akses (403 generik) dan status (400) diputuskan sebelum penulisan dan penghentian timer SLA.
    perubahan = await terapkan_dq(db, project, current_user, body.dq_number)
    is_first_dq = perubahan.pertama_kali

    await db.commit()
    await db.refresh(project)

    # Stop SLA timer saat DQ pertama kali diinput (auto-unlock folder Solutions bila terkunci)
    await hentikan_timer_bila_pertama(db, project_id, perubahan)

    logger.info(
        f"DQ Number '{body.dq_number}' diinput pada proyek {project_id} "
        f"oleh {current_user.email} (role: {current_user.role})"
    )

    response_data = DQNumberResponse(
        id_project=project.id_project,
        project_name=project.project_name,
        customer_name=project.customer_name,
        dq_number=project.dq_number,
        status=project.status,
    )

    return success_response(
        data=response_data.model_dump(mode="json"),
        message=(
            "DQ Number berhasil disimpan. Status proyek diubah ke 'Ready'."
            if is_first_dq and project.status == "Ready"
            else "DQ Number berhasil diperbarui."
        ),
    )


@router.get(
    "/projects/{project_id}/documents/solutions",
    summary="Ambil dokumen Solutions dengan gating DQ Number",
    description=(
        "Menampilkan dokumen dari folder Solutions. "
        "Sales hanya bisa melihat jika DQ Number sudah ada DAN status dokumen 'Reviewed' atau 'Final'. "
        "SA/Lead_SA bisa melihat semua dokumen Solutions kapanpun."
    ),
)
async def get_solutions_documents(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ambil dokumen Solutions dengan gating logic:
    - Sales: hanya terlihat jika DQ ada + dokumen berstatus "Reviewed"/"Final"
    - SA/Lead_SA: selalu bisa melihat semua dokumen Solutions
    """
    # === 1. Validasi proyek ada ===
    project_result = await db.execute(
        select(Project).where(Project.id_project == project_id)
    )
    project = project_result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    await ensure_project_access(db, project, current_user, TingkatAkses.BACA)
    # Sales hanya boleh melihat link Solutions bila PIC proyek ini (collaborator Sales tidak).
    if adalah_sales_terbatas(current_user) and project.sales_pic != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki akses ke proyek ini.",
        )

    # === 2. Gating untuk Sales: DQ Number harus ada ===
    if adalah_sales_terbatas(current_user) and project.dq_number is None:
        # Sembunyikan link Solutions — return list kosong
        return success_response(
            data={"documents": [], "total": 0, "dq_required": True},
            message="DQ Number belum diinput. Dokumen Solutions belum tersedia.",
        )

    # === 3. Query dokumen Solutions ===
    doc_result = await db.execute(
        select(Document)
        .where(Document.id_project == project_id, Document.folder_type == FOLDER_SOLUTIONS)
        .order_by(Document.created_at.desc())
    )
    # Aturan gating yang sama dengan GET /projects/{id}/documents (Sales: PIC + DQ + Reviewed/Final).
    documents = saring_dokumen_terlihat(current_user, project, doc_result.scalars().all())

    # === 4. Format response ===
    docs_data = [
        SolutionsDocumentResponse(
            id_doc=doc.id_doc,
            doc_type=doc.doc_type,
            status=doc.status,
            gdrive_link=doc.gdrive_link,
            notes=doc.notes,
        ).model_dump(mode="json")
        for doc in documents
    ]

    return success_response(
        data={
            "documents": docs_data,
            "total": len(docs_data),
            "dq_number": project.dq_number,
        },
        message=f"Ditemukan {len(docs_data)} dokumen Solutions.",
    )
