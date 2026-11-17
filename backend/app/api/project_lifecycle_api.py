"""Project detail, update, and lifecycle API endpoints."""

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import status as status_konst
from app.core.database import get_db
from app.core.dependencies import (
    TingkatAkses,
    adalah_privileged,
    ensure_project_access,
    get_current_user,
)
from app.models.project import Project
from app.models.project_collaborator import ProjectCollaborator
from app.models.sla_tracking import SLATracking
from app.models.source_document import SourceDocument
from app.models.user import User
from app.schemas.dq_number import DQNumberInput
from app.schemas.project import ProjectDetailResponse
from app.schemas.response import ErrorResponse, SuccessResponse, error_response, success_response
from app.schemas.qualification import validate_answers
from app.services import bant_rubric
from app.services.dq_akses import hentikan_timer_bila_pertama, terapkan_dq
from app.services.integration_operations import list_project_operations
from app.services.qualification_view import build_qualification_view
from app.services.scoring_engine import scoring_engine
from app.services import requirement_generator
from app.api.project_api_helpers import _ringkas_orang

logger = logging.getLogger(__name__)
router = APIRouter()


async def _muat_user(db: AsyncSession, ids) -> dict[uuid.UUID, User]:
    """Muat beberapa user sekaligus (satu query), kunci = id."""
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    hasil = await db.execute(select(User).where(User.id.in_(ids)))
    return {u.id: u for u in hasil.scalars().all()}


@router.get(
    "/{project_id}",
    summary="Detail proyek",
    description="Mengambil detail satu proyek berdasarkan ID, termasuk info PIC Sales dan SA.",
    response_model=SuccessResponse[ProjectDetailResponse],
    responses={
        401: {"model": ErrorResponse[dict[str, Any]]},
        404: {"model": ErrorResponse[None]},
        422: {"model": ErrorResponse[list[dict[str, str]]]},
    },
)
async def get_project_detail(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ambil detail proyek berdasarkan project_id, enriched dengan nama PIC."""
    result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    # Titik keputusan bersama (BACA): Admin/Lead_SA, Sales PIC, SA ditugaskan, kolaborator.
    await ensure_project_access(db, project, current_user, TingkatAkses.BACA)

    # Nama created_by, Product PIC, dan Sales PIC (opsional)
    orang = await _muat_user(
        db, (project.created_by, project.product_pic, project.sales_pic, project.lead_sa)
    )

    # Fetch nama SA assigned
    sa_name = None
    sa_email = None
    if project.assigned_sa:
        sa_result = await db.execute(select(User).where(User.id == project.assigned_sa))
        sa_user = sa_result.scalar_one_or_none()
        if sa_user:
            sa_name = sa_user.name
            sa_email = sa_user.email

    # Fetch collaborators
    collabs_result = await db.execute(
        select(ProjectCollaborator)
        .where(ProjectCollaborator.id_project == project_id)
        .order_by(ProjectCollaborator.created_at.desc())
    )
    collaborators = collabs_result.scalars().all()

    collab_list = []
    for c in collaborators:
        c_user_result = await db.execute(select(User).where(User.id == c.user_id))
        c_user = c_user_result.scalar_one_or_none()
        c_adder_result = await db.execute(select(User).where(User.id == c.added_by))
        c_adder = c_adder_result.scalar_one_or_none()
        collab_list.append(
            {
                "id": str(c.id),
                "user_id": str(c.user_id),
                "user_name": c_user.name if c_user else "Unknown",
                "user_email": c_user.email if c_user else "unknown",
                "user_role": c_user.role if c_user else "Unknown",
                "role": c.role,
                "added_by_name": c_adder.name if c_adder else "Unknown",
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
        )

    # Daftar Source document (tanpa teks penuh; hanya panjang teks)
    source_docs_result = await db.execute(
        select(SourceDocument)
        .where(SourceDocument.id_project == project_id)
        .order_by(SourceDocument.created_at.asc())
    )
    source_documents = [
        {
            "id": str(d.id),
            "filename": d.filename,
            "doc_type": d.doc_type,
            "size_bytes": d.size_bytes,
            "extraction_status": d.extraction_status,
            "truncated": bool(d.truncated),
            "text_length": len(d.extracted_text) if d.extracted_text else 0,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }
        for d in source_docs_result.scalars().all()
    ]

    scoring_berjalan = (
        project.status == status_konst.INTAKE
        and project.qualification_state == status_konst.QS_SCORING
    )
    integration_operations = await list_project_operations(db, project_id)
    data = {
        "id_project": project.id_project,
        "project_name": project.project_name,
        "customer_name": project.customer_name,
        "status": project.status,
        "qualification_state": project.qualification_state,
        "previous_status": project.previous_status,
        "lost_reason": project.lost_reason,
        "dq_number": project.dq_number,
        # Selama qualification_state Scoring skor sementara tidak ditampilkan sebagai hasil final
        "bant_score": None if scoring_berjalan else project.bant_score,
        "bant_detail": (
            {
                k: v
                for k, v in (project.bant_detail or {}).items()
                if k not in bant_rubric.SUB_SCORE_KEYS
            }
            if scoring_berjalan
            else project.bant_detail
        ),
        "qualification": build_qualification_view(project),
        "use_case_tags": project.use_case_tags or [],
        "estimasi_nilai": str(project.estimasi_nilai)
        if project.estimasi_nilai is not None
        else None,
        "target_submit": project.target_submit.isoformat() if project.target_submit else None,
        "created_by": _ringkas_orang(orang.get(project.created_by), project.created_by),
        "product_pic": _ringkas_orang(orang.get(project.product_pic), project.product_pic),
        "sales_pic": _ringkas_orang(orang.get(project.sales_pic), project.sales_pic),
        "lead_sa": _ringkas_orang(orang.get(project.lead_sa), project.lead_sa),
        "assigned_sa": {
            "id": str(project.assigned_sa) if project.assigned_sa else None,
            "name": sa_name,
            "email": sa_email,
        }
        if project.assigned_sa
        else None,
        "collaborators": collab_list,
        "gdrive_folder_id": project.gdrive_folder_id,
        "gdrive_solutions_folder_id": project.gdrive_solutions_folder_id,
        "source_documents": source_documents,
        "folder_provisioning_status": project.folder_provisioning_status,
        "folder_provisioning_operation": project.folder_provisioning_operation,
        "integration_operations": integration_operations,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }

    return success_response(
        data=data,
        message="Detail proyek berhasil diambil.",
    )


@router.delete(
    "/{project_id}",
    summary="Hapus proyek",
    description=(
        "Hapus proyek (soft delete) berdasarkan ID. Hanya Lead_SA dan Admin yang dapat "
        "menghapus. Data terkait (dokumen, activity log, SLA) tetap tersimpan."
    ),
)
async def delete_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Soft delete proyek: set deleted_at/deleted_by, proyek lalu tersaring dari
    semua query ORM. Hard delete tidak dipakai karena dokumen, activity log
    (data utilisasi SA), dan SLA mengacu ke proyek via FK tanpa cascade.
    """
    # Cek role
    if not adalah_privileged(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Lead SA dan Admin yang dapat menghapus proyek.",
        )

    result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    now = datetime.now(timezone.utc)
    project.deleted_at = now
    project.deleted_by = current_user.id

    # Hentikan SLA timer yang masih aktif agar scheduler tidak lagi memproses
    # (reminder/eskalasi) proyek yang sudah dihapus.
    await db.execute(
        update(SLATracking)
        .where(SLATracking.project_id == project_id, SLATracking.stopped_at.is_(None))
        .values(stopped_at=now)
    )
    await db.commit()

    logger.info(
        f"Proyek {project_id} dihapus oleh {current_user.email} (role: {current_user.role})"
    )

    return success_response(
        data={"id_project": project_id},
        message=f"Proyek '{project_id}' berhasil dihapus.",
    )


@router.put(
    "/{project_id}/qualification-answers",
    summary="Edit jawaban Kuesioner kualifikasi",
    description=(
        "Sales PIC mengubah jawaban hanya saat Intake dengan qualification_state Need Clarification "
        "(re-score + gate 60). Lead_SA/Admin diperlakukan sama saat Need Clarification; setelah lolos gate mereka "
        "dapat mengoreksi tanpa re-score. Proyek legacy (tanpa jawaban) ditolak."
    ),
)
async def update_qualification_answers(
    project_id: str,
    background_tasks: BackgroundTasks,
    body: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit jawaban kuesioner; skor dihitung backend (ADR 0010), bukan dari klien."""
    result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Proyek tidak ditemukan.")

    # Titik keputusan bersama (EDIT_KUESIONER): Lead_SA/Admin atau Sales PIC proyek ini.
    await ensure_project_access(
        db,
        project,
        current_user,
        TingkatAkses.EDIT_KUESIONER,
        pesan="Anda tidak memiliki akses untuk mengubah jawaban kuesioner proyek ini.",
    )
    is_privileged = adalah_privileged(current_user)

    if project.qualification_answers is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Proyek ini dibuat sebelum kuesioner kualifikasi (legacy) dan tidak punya "
                "jawaban kuesioner. Gunakan bagian data legacy untuk mengubah datanya."
            ),
        )

    needs_clarification = (
        project.status == status_konst.INTAKE
        and project.qualification_state == status_konst.QS_NEED_CLARIFICATION
    )
    if not needs_clarification:
        if not is_privileged:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Jawaban kuesioner hanya dapat diubah Sales saat qualification_state "
                    "Need Clarification."
                ),
            )
        if project.status == status_konst.INTAKE:
            # Intake dengan state Scoring atau Manual Review: gate belum selesai.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Jawaban kuesioner belum dapat diedit pada qualification_state "
                    f"'{project.qualification_state}'."
                ),
            )

    answers, errors = validate_answers(body)
    if errors:
        return JSONResponse(
            status_code=422,
            content=error_response(
                message="Validasi gagal. Periksa data yang dikirim.", data=errors
            ),
        )

    if needs_clarification:
        bant_result = await scoring_engine.rescore_from_answers(db, project, answers)
        if project.requirement_generation_status == "pending":
            background_tasks.add_task(
                requirement_generator.generate_pending_requirement, project.id_project
            )
        return success_response(
            data=bant_result.model_dump(),
            message=f"Jawaban disimpan dan skor dihitung ulang. Total skor: {bant_result.total_score}.",
        )

    # Koreksi Lead_SA/Admin setelah lolos gate: skor dan status tidak berubah.
    project.qualification_answers = answers
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    # Jawaban berubah → Requirement yang belum di-override diperbarui bila hash berbeda.
    background_tasks.add_task(
        requirement_generator.resummarize_if_source_changed, project.id_project
    )
    return success_response(
        data={
            "total_score": project.bant_score,
            "status": project.status,
            "rescored": False,
        },
        message="Jawaban dikoreksi tanpa menghitung ulang skor.",
    )


@router.patch(
    "/{project_id}",
    summary="Update proyek",
    description=(
        "Update informasi proyek (nama, customer, DQ, estimasi nilai, BANT detail, target submit)."
    ),
)
async def update_project(
    project_id: str,
    body: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update field-field proyek yang diizinkan."""
    result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Proyek tidak ditemukan.")

    # Validasi akses ubah proyek sebelum mutasi field apapun: Lead_SA/Admin, Sales PIC,
    # SA ditugaskan, atau collaborator contributor (viewer ditolak).
    await ensure_project_access(db, project, current_user, TingkatAkses.UBAH_PROYEK)

    # Perubahan NILAI dq_number mengikuti aturan DAN efek samping yang sama dengan
    # PATCH /projects/{id}/dq-number (terapkan_dq): diputuskan sebelum mutasi field lain agar 403/400
    # tidak meninggalkan perubahan lain. Nilai yang sama dengan tersimpan diabaikan (form edit
    # mengirim semua field, jadi peran lain yang tak mengubah DQ tidak boleh mendapat 403).
    perubahan_dq = None
    if "dq_number" in body:
        dq_baru = body["dq_number"] or None  # "" dan None sama-sama berarti tidak terisi
        if dq_baru != project.dq_number:
            if dq_baru is not None:
                # Format divalidasi dengan schema yang sama dengan /dq-number (satu sumber);
                # tanpa ini nilai tidak valid menabrak CHECK chk_dq_number_format (500).
                try:
                    DQNumberInput(dq_number=dq_baru)
                except ValidationError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=exc.errors()[0]["msg"].removeprefix("Value error, "),
                    ) from exc
            perubahan_dq = await terapkan_dq(db, project, current_user, dq_baru)

    # Update fields yang dikirim
    if "project_name" in body and body["project_name"]:
        project.project_name = body["project_name"]
    if "customer_name" in body and body["customer_name"]:
        project.customer_name = body["customer_name"]
    if "target_submit" in body and body["target_submit"]:
        from datetime import date as date_cls

        try:
            project.target_submit = date_cls.fromisoformat(body["target_submit"])
        except (ValueError, TypeError):
            pass
    if "estimasi_nilai" in body and body["estimasi_nilai"] is not None:
        # Validasi range sama dengan create_project (0.01 - 999,999,999,999.00)
        try:
            estimasi_decimal = Decimal(str(body["estimasi_nilai"]))
        except (InvalidOperation, ValueError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Format estimasi nilai tidak valid. Gunakan angka desimal.",
            )
        if estimasi_decimal < Decimal("0.01"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Estimasi nilai minimum adalah 0.01.",
            )
        if estimasi_decimal > Decimal("999999999999.00"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Estimasi nilai maksimum adalah 999,999,999,999.00.",
            )
        # Kolom skalar Numeric — reassign langsung aman (bukan mutasi in-place)
        project.estimasi_nilai = estimasi_decimal
    if "bant_detail" in body and body["bant_detail"]:
        # Merge dengan existing bant_detail.
        # Kolom di-map dengan MutableDict sehingga mutasi in-place terdeteksi
        # oleh SQLAlchemy dan ikut ter-commit.
        # Kunci sub-skor numerik dimiliki backend (rubrik/AI/override): tidak boleh ditimpa
        # lewat endpoint ini, hanya metadata deskriptif legacy yang boleh di-merge.
        incoming = body["bant_detail"]
        if not isinstance(incoming, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="bant_detail harus berupa objek.",
            )
        protected = [k for k in bant_rubric.SUB_SCORE_KEYS if k in incoming]
        if protected:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content=error_response(
                    message="Sub-skor BANT tidak dapat diubah lewat endpoint ini.",
                    data=[
                        {
                            "field": f"bant_detail.{k}",
                            "reason": "Sub-skor dihitung backend dan tidak boleh diubah di sini.",
                        }
                        for k in protected
                    ],
                ),
            )
        existing = project.bant_detail or {}
        existing.update(incoming)
        project.bant_detail = existing

    project.updated_at = datetime.now(timezone.utc)
    await db.commit()

    if perubahan_dq is not None:
        await hentikan_timer_bila_pertama(db, project_id, perubahan_dq)

    return success_response(
        data={"id_project": project.id_project, "status": project.status},
        message="Proyek berhasil diupdate.",
    )

