"""
API endpoints untuk DQ Number input dan document gating.
Menangani input DQ Number oleh Sales, proteksi edit oleh Lead_SA,
dan gating akses dokumen Solutions berdasarkan DQ + status dokumen.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import TingkatAkses, ensure_project_access, get_current_user
from app.models.document import Document
from app.models.project import Project
from app.models.user import User
from app.schemas.dq_number import DQNumberInput, DQNumberResponse, SolutionsDocumentResponse
from app.schemas.response import error_response, success_response
from app.services.sla_timer import sla_timer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["DQ Number"])

# Status proyek yang diizinkan untuk input DQ Number ("Assigned" atau lebih tinggi)
ALLOWED_STATUSES_FOR_DQ = (
    "Assigned",
    "Ready",
    "Closed-Win",
    "Handover Complete",
)


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

    # Hanya Sales PIC proyek ini, Lead_SA, dan Admin; sebelum validasi lain, penulisan,
    # dan penghentian timer SLA (403 generik, tanpa efek samping).
    await ensure_project_access(db, project, current_user, TingkatAkses.ISI_DQ)

    # === 2. Validasi status proyek cukup tinggi ===
    if project.status not in ALLOWED_STATUSES_FOR_DQ:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"DQ Number hanya bisa diinput pada proyek berstatus "
                f"'Assigned' atau lebih tinggi. Status saat ini: '{project.status}'."
            ),
        )

    # === 3. Proteksi: Sales tidak bisa edit DQ yang sudah tersimpan ===
    if project.dq_number is not None and current_user.role == "Sales":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "DQ Number sudah tersimpan dan tidak bisa diubah oleh Sales. "
                "Hubungi Lead SA untuk perubahan."
            ),
        )

    # === 4. Hanya Sales atau Lead_SA yang boleh input DQ ===
    if current_user.role not in ("Sales", "Lead_SA", "Admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Sales atau Lead_SA yang dapat menginput DQ Number.",
        )

    # === 5. Update DQ Number dan status ===
    now = datetime.now(timezone.utc)
    is_first_dq = project.dq_number is None

    project.dq_number = body.dq_number
    project.updated_at = now

    # Update status ke "Ready" hanya saat DQ pertama kali diinput
    # dan status saat ini masih "Assigned"
    if is_first_dq and project.status == "Assigned":
        project.status = "Ready"

    await db.commit()
    await db.refresh(project)

    # Stop SLA timer saat DQ Number pertama kali diinput
    # Ini juga akan auto-unlock folder Solutions jika sudah di-lock
    if is_first_dq:
        try:
            await sla_timer.stop_timer(project_id=project_id, db=db)
        except Exception as e:
            logger.warning(
                f"Gagal menghentikan SLA timer untuk proyek {project_id}: {e}"
            )

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
    if current_user.role == "Sales" and project.sales_pic != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki akses ke proyek ini.",
        )

    # === 2. Gating untuk Sales: DQ Number harus ada ===
    if current_user.role == "Sales" and project.dq_number is None:
        # Sembunyikan link Solutions — return list kosong
        return success_response(
            data={"documents": [], "total": 0, "dq_required": True},
            message="DQ Number belum diinput. Dokumen Solutions belum tersedia.",
        )

    # === 3. Query dokumen Solutions ===
    query = select(Document).where(
        Document.id_project == project_id,
        Document.folder_type == "Solutions",
    )

    # Sales hanya bisa lihat dokumen dengan status "Reviewed" atau "Final"
    if current_user.role == "Sales":
        query = query.where(Document.status.in_(["Reviewed", "Final"]))

    doc_result = await db.execute(query.order_by(Document.created_at.desc()))
    documents = doc_result.scalars().all()

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
