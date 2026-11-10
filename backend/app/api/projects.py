"""
API endpoints untuk manajemen proyek pre-sales.
Menangani submission request baru oleh Sales termasuk file upload.
"""

import logging
import random
import uuid
import string
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy import asc, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import ensure_project_access, get_current_user
from app.models.project import Project
from app.models.project_collaborator import ProjectCollaborator
from app.models.sla_tracking import SLATracking
from app.models.source_document import DOC_TYPES, SourceDocument
from app.models.user import User
from app.schemas.project import FileUploadResult, ProjectResponse
from app.schemas.qualification import parse_answers, validate_answers
from app.schemas.response import error_response, success_response
from app.services import bant_rubric
from app.services.scoring_engine import SCORING_MUTABLE_STATUSES, scoring_engine
from app.services.qualification_view import build_qualification_view
from app.services.requirement_generator import (
    generate_pending_requirement,
    resummarize_if_source_changed,
)
from app.services.source_document_extractor import extract_source_documents

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Projects"])

# Konstanta file upload
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20MB
MAX_FILES = 5
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ALLOWED_EXTENSIONS = {".pdf", ".docx"}


def _generate_project_id() -> str:
    """
    Generate ID proyek unik dengan format PRJ-{YYYYMMDD}-{random 6 chars}.
    Contoh: PRJ-20250101-A3X9K2
    """
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"PRJ-{date_part}-{random_part}"


def _validate_file_extension(filename: str) -> bool:
    """Cek apakah ekstensi file termasuk yang diizinkan."""
    if not filename:
        return False
    lower_name = filename.lower()
    return any(lower_name.endswith(ext) for ext in ALLOWED_EXTENSIONS)


async def _process_file_upload(file: UploadFile) -> tuple[FileUploadResult, Optional[bytes]]:
    """
    Proses satu file upload: validasi format dan ukuran.
    Return tuple (hasil validasi, konten file jika valid).
    """
    filename = file.filename or "unknown"

    # Validasi ekstensi file
    if not _validate_file_extension(filename):
        return FileUploadResult(
            filename=filename,
            success=False,
            error=f"Format file tidak valid. Hanya PDF dan DOCX yang diterima.",
        ), None

    # Validasi MIME type
    content_type = file.content_type or ""
    if content_type not in ALLOWED_MIME_TYPES:
        # Fallback: cek ekstensi saja (beberapa client tidak kirim MIME type yang benar)
        if not _validate_file_extension(filename):
            return FileUploadResult(
                filename=filename,
                success=False,
                error=f"MIME type '{content_type}' tidak didukung.",
            ), None

    # Baca konten file dan validasi ukuran
    try:
        content = await file.read()
        size_bytes = len(content)

        if size_bytes > MAX_FILE_SIZE_BYTES:
            size_mb = size_bytes / (1024 * 1024)
            return FileUploadResult(
                filename=filename,
                success=False,
                error=f"Ukuran file {size_mb:.1f}MB melebihi batas 20MB.",
                size_bytes=size_bytes,
            ), None

        if size_bytes == 0:
            return FileUploadResult(
                filename=filename,
                success=False,
                error="File kosong (0 bytes).",
                size_bytes=0,
            ), None

        return FileUploadResult(
            filename=filename,
            success=True,
            size_bytes=size_bytes,
        ), content

    except Exception as e:
        logger.error(f"Gagal membaca file '{filename}': {e}")
        return FileUploadResult(
            filename=filename,
            success=False,
            error=f"Gagal membaca file: {str(e)}",
        ), None


async def _trigger_scoring_engine(
    project_id: str,
    valid_files: list[tuple[str, bytes, str]],
) -> None:
    """
    Background task: trigger Scoring_Engine untuk analisis BANT.
    Dipanggil async setelah record proyek tersimpan (< 5 detik).

    Args:
        project_id: ID proyek yang baru dibuat.
        valid_files: List tuple (filename, content_bytes, mime_type).
    """
    from app.core.database import AsyncSessionLocal
    from app.services.scoring_engine import scoring_engine

    logger.info(
        f"[ScoringEngine] Trigger scoring untuk proyek {project_id} dengan {len(valid_files)} file."
    )
    try:
        # Buat session baru untuk background task (request session sudah ditutup)
        async with AsyncSessionLocal() as db:
            # Konversi format: (filename, content, mime_type) → (content, mime_type, filename)
            files_for_scoring = [
                (content, mime_type, filename) for filename, content, mime_type in valid_files
            ]
            result = await scoring_engine.score_documents(
                project_id=project_id,
                files=files_for_scoring,
                db=db,
            )
            logger.info(
                f"[ScoringEngine] Scoring selesai untuk proyek {project_id}: "
                f"total_score={result.total_score}, status={result.status}"
            )
    except Exception as e:
        logger.error(f"[ScoringEngine] Gagal memproses proyek {project_id}: {e}")
        # Jaring pengaman: jangan biarkan proyek menggantung di Scoring Pending
        try:
            async with AsyncSessionLocal() as db:
                await scoring_engine.fallback_after_failure(db, project_id)
        except Exception as fallback_error:
            logger.error(
                f"[ScoringEngine] Fallback rubrik gagal untuk proyek {project_id}: {fallback_error}"
            )

    # Proyek yang baru lolos gate (jalur AI maupun fallback rubrik) → generate Requirement.
    # No-op bila proyek tidak bertanda `pending`; tidak pernah melempar.
    await generate_pending_requirement(project_id)


@router.get(
    "",
    summary="Daftar proyek",
    description=(
        "Menampilkan daftar proyek berdasarkan role user yang login. "
        "Sales hanya melihat proyeknya sendiri, SA melihat proyek yang ditugaskan, "
        "Lead_SA melihat semua proyek aktif."
    ),
)
async def list_projects(
    sales_pic: Optional[str] = Query(
        None, description="Filter: 'me' untuk proyek milik user login"
    ),
    assigned_to: Optional[str] = Query(
        None, description="Filter: 'me' untuk proyek yang ditugaskan ke user login"
    ),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter berdasarkan status proyek"
    ),
    sort: Optional[str] = Query(
        "-updated_at", description="Sort: field name, prefix '-' untuk desc"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ambil daftar proyek dengan filter berdasarkan role.

    Filter:
    - sales_pic=me → proyek yang dibuat oleh user saat ini
    - assigned_to=me → proyek yang ditugaskan ke user saat ini
    - status=<value> → filter berdasarkan status

    Sort:
    - -updated_at (default): terbaru diupdate
    - updated_at: terlama diupdate
    - -created_at: terbaru dibuat
    """
    query = select(Project)

    # === Scoping akses berbasis role (dipaksa server-side) ===
    # Lead_SA & Admin: akses ke seluruh proyek.
    # Sales & SA: hanya proyek terkait dirinya (sebagai sales_pic / assigned_sa)
    #             ATAU proyek di mana ia terdaftar sebagai collaborator.
    # Catatan: query param sales_pic=me / assigned_to=me hanya penyempit opsional,
    # bukan satu-satunya penjaga akses (sebelumnya rawan bypass bila param tidak dikirim).
    if current_user.role not in ("Lead_SA", "Admin"):
        collab_subquery = select(ProjectCollaborator.id_project).where(
            ProjectCollaborator.user_id == current_user.id
        )
        query = query.where(
            or_(
                Project.sales_pic == current_user.id,
                Project.assigned_sa == current_user.id,
                Project.id_project.in_(collab_subquery),
            )
        )

    # Penyempit opsional dari query param (hanya mempersempit, tidak memperluas akses)
    if sales_pic == "me":
        query = query.where(Project.sales_pic == current_user.id)
    elif assigned_to == "me":
        query = query.where(Project.assigned_sa == current_user.id)

    # Filter status
    if status_filter:
        query = query.where(Project.status == status_filter)

    # Sorting
    if sort:
        if sort.startswith("-"):
            field_name = sort[1:]
            if hasattr(Project, field_name):
                query = query.order_by(desc(getattr(Project, field_name)))
            else:
                query = query.order_by(desc(Project.updated_at))
        else:
            if hasattr(Project, sort):
                query = query.order_by(asc(getattr(Project, sort)))
            else:
                query = query.order_by(desc(Project.updated_at))
    else:
        query = query.order_by(desc(Project.updated_at))

    result = await db.execute(query)
    projects = result.scalars().all()

    # Format response
    projects_data = []
    for p in projects:
        projects_data.append(
            {
                "id_project": p.id_project,
                "project_name": p.project_name,
                "customer_name": p.customer_name,
                "status": p.status,
                "dq_number": p.dq_number,
                "bant_score": p.bant_score,
                "use_case_tags": p.use_case_tags or [],
                "estimasi_nilai": str(p.estimasi_nilai) if p.estimasi_nilai is not None else None,
                "target_submit": p.target_submit.isoformat() if p.target_submit else None,
                "assigned_sa": str(p.assigned_sa) if p.assigned_sa else None,
                "gdrive_folder_id": p.gdrive_folder_id,
                "folder_provisioning_status": p.folder_provisioning_status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            }
        )

    return success_response(
        data=projects_data,
        message=f"Ditemukan {len(projects_data)} proyek.",
    )


@router.get(
    "/status-summary",
    summary="Ringkasan jumlah proyek per status",
    description="Mengembalikan count proyek per status untuk overview dashboard.",
)
async def get_status_summary(
    sales_pic: Optional[str] = Query(
        None, description="Filter: 'me' untuk proyek milik user login"
    ),
    assigned_to: Optional[str] = Query(
        None, description="Filter: 'me' untuk proyek yang ditugaskan ke user login"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hitung jumlah proyek per status, dengan filter berbasis role."""
    query = select(Project.status, func.count(Project.id_project))

    # === Scoping akses berbasis role (sama seperti list_projects) ===
    # Lead_SA & Admin: seluruh proyek. Sales & SA: proyek terkait + collaborator.
    if current_user.role not in ("Lead_SA", "Admin"):
        collab_subquery = select(ProjectCollaborator.id_project).where(
            ProjectCollaborator.user_id == current_user.id
        )
        query = query.where(
            or_(
                Project.sales_pic == current_user.id,
                Project.assigned_sa == current_user.id,
                Project.id_project.in_(collab_subquery),
            )
        )

    # Penyempit opsional dari query param
    if sales_pic == "me":
        query = query.where(Project.sales_pic == current_user.id)
    elif assigned_to == "me":
        query = query.where(Project.assigned_sa == current_user.id)

    result = await db.execute(
        query.group_by(Project.status).order_by(func.count(Project.id_project).desc())
    )
    rows = result.all()

    summary = [{"status": row[0], "count": row[1]} for row in rows]

    return success_response(
        data=summary,
        message=f"Ringkasan {len(summary)} status.",
    )


@router.get(
    "/{project_id}",
    summary="Detail proyek",
    description="Mengambil detail satu proyek berdasarkan ID, termasuk info PIC Sales dan SA.",
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

    # Validasi akses: Admin/Lead_SA selalu bisa, Sales PIC / assigned SA bisa,
    # kolaborator bisa, lainnya 403
    is_privileged = current_user.role in ("Lead_SA", "Admin")
    is_sales_pic = project.sales_pic == current_user.id
    is_assigned_sa = project.assigned_sa == current_user.id

    # Cek kolaborator
    collab_result = await db.execute(
        select(ProjectCollaborator).where(
            ProjectCollaborator.id_project == project_id,
            ProjectCollaborator.user_id == current_user.id,
        )
    )
    is_collaborator = collab_result.scalar_one_or_none() is not None

    if not (is_privileged or is_sales_pic or is_assigned_sa or is_collaborator):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki akses ke proyek ini.",
        )

    # Fetch nama Sales PIC
    sales_name = None
    sales_email = None
    if project.sales_pic:
        sales_result = await db.execute(select(User).where(User.id == project.sales_pic))
        sales_user = sales_result.scalar_one_or_none()
        if sales_user:
            sales_name = sales_user.name
            sales_email = sales_user.email

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

    data = {
        "id_project": project.id_project,
        "project_name": project.project_name,
        "customer_name": project.customer_name,
        "status": project.status,
        "dq_number": project.dq_number,
        # Selama Scoring Pending skor sementara tidak ditampilkan sebagai hasil final
        "bant_score": None if project.status == "Scoring Pending" else project.bant_score,
        "bant_detail": (
            {
                k: v
                for k, v in (project.bant_detail or {}).items()
                if k not in bant_rubric.SUB_SCORE_KEYS
            }
            if project.status == "Scoring Pending"
            else project.bant_detail
        ),
        "qualification": build_qualification_view(project),
        "use_case_tags": project.use_case_tags or [],
        "estimasi_nilai": str(project.estimasi_nilai)
        if project.estimasi_nilai is not None
        else None,
        "target_submit": project.target_submit.isoformat() if project.target_submit else None,
        "sales_pic": {
            "id": str(project.sales_pic) if project.sales_pic else None,
            "name": sales_name,
            "email": sales_email,
        },
        "assigned_sa": {
            "id": str(project.assigned_sa) if project.assigned_sa else None,
            "name": sa_name,
            "email": sa_email,
        }
        if project.assigned_sa
        else None,
        "collaborators": collab_list,
        "source_documents": source_documents,
        "gdrive_folder_id": project.gdrive_folder_id,
        "folder_provisioning_status": project.folder_provisioning_status,
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
    if current_user.role not in ("Lead_SA", "Admin"):
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
        "Sales PIC mengubah jawaban hanya saat status Need Clarification (re-score + gate 60). "
        "Lead_SA/Admin diperlakukan sama saat Need Clarification; setelah lolos gate mereka "
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

    is_privileged = current_user.role in ("Lead_SA", "Admin")
    is_sales_pic = current_user.role == "Sales" and project.sales_pic == current_user.id
    if not (is_privileged or is_sales_pic):
        raise HTTPException(
            status_code=403,
            detail="Anda tidak memiliki akses untuk mengubah jawaban kuesioner proyek ini.",
        )

    if project.qualification_answers is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Proyek ini dibuat sebelum kuesioner kualifikasi (legacy) dan tidak punya "
                "jawaban kuesioner. Gunakan bagian data legacy untuk mengubah datanya."
            ),
        )

    needs_clarification = project.status == "Need Clarification"
    if not needs_clarification:
        if not is_privileged:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Jawaban kuesioner hanya dapat diubah Sales saat status Need Clarification."
                ),
            )
        if project.status in SCORING_MUTABLE_STATUSES or project.status == "Manual Review Required":
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Jawaban kuesioner belum dapat diedit pada status '{project.status}'."
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
            background_tasks.add_task(generate_pending_requirement, project.id_project)
        return success_response(
            data=bant_result.model_dump(),
            message=f"Jawaban disimpan dan skor dihitung ulang. Total skor: {bant_result.total_score}.",
        )

    # Koreksi Lead_SA/Admin setelah lolos gate: skor dan status tidak berubah.
    project.qualification_answers = answers
    project.updated_at = datetime.now(timezone.utc)
    await db.commit()
    # Jawaban berubah → Requirement yang belum di-override diperbarui bila hash berbeda.
    background_tasks.add_task(resummarize_if_source_changed, project.id_project)
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

    # Validasi akses general sebelum mutasi field apapun:
    # privileged (Lead_SA/Admin), Sales PIC, assigned SA, atau collaborator.
    await ensure_project_access(db, project, current_user)

    # Update fields yang dikirim
    if "project_name" in body and body["project_name"]:
        project.project_name = body["project_name"]
    if "customer_name" in body and body["customer_name"]:
        project.customer_name = body["customer_name"]
    if "dq_number" in body:
        project.dq_number = body["dq_number"] if body["dq_number"] else None
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

    return success_response(
        data={"id_project": project.id_project, "status": project.status},
        message="Proyek berhasil diupdate.",
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Submit request SA (request proyek pre-sales baru)",
    description=(
        "Endpoint untuk mengajukan Request SA (proyek pre-sales baru). "
        "Dapat diakses oleh role Sales, SA, dan Lead_SA. "
        "Menerima form data + file attachment (PDF/DOCX, max 20MB/file, max 5 files). "
        "Menerima jawaban Kuesioner kualifikasi (qualification_answers, JSON); skor BANT "
        "dihitung backend. Tanpa file: gate 60 langsung diterapkan. Dengan file: status 'Scoring Pending' "
        "dan scoring engine async."
    ),
)
async def create_project(
    background_tasks: BackgroundTasks,
    project_name: str = Form(
        ...,
        min_length=1,
        max_length=150,
        description="Nama proyek (wajib, max 150 karakter)",
    ),
    customer_name: str = Form(
        ...,
        min_length=1,
        max_length=150,
        description="Nama customer (wajib, max 150 karakter)",
    ),
    target_submit: date = Form(
        ...,
        description="Target tanggal submit (format: YYYY-MM-DD, tidak boleh masa lalu)",
    ),
    estimasi_nilai: str = Form(
        ...,
        description="Estimasi nilai proyek IDR (0.01 - 999,999,999,999.00)",
    ),
    dq_number: Optional[str] = Form(
        default=None,
        description="DQ Number opsional (alfanumerik + hyphen, 5-20 karakter)",
    ),
    qualification_answers: Optional[str] = Form(
        default=None,
        description="Jawaban Kuesioner kualifikasi v1 (string JSON, wajib)",
    ),
    files: list[UploadFile] = File(
        default=[],
        description="File attachment (PDF/DOCX, max 20MB/file, max 5 files)",
    ),
    file_types: list[str] = Form(
        default=[],
        description="Tipe Source document per file (MoM/RFP), paralel dengan `files` (indeks sama)",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit request proyek pre-sales baru.

    Flow:
    1. Validasi input form (project_name, customer_name, target_submit, estimasi_nilai)
    2. Validasi file upload (format, ukuran, jumlah)
    3. Buat record Project dengan status awal sesuai skor rubrik (Scoring Pending bila ada file)
    4. Trigger Scoring_Engine async jika ada file valid
    5. Return 201 dengan data proyek + hasil upload per file
    """
    # === Validasi manual untuk field yang diterima sebagai Form ===

    # Trim whitespace
    project_name = project_name.strip()
    customer_name = customer_name.strip()

    # Validasi field kosong setelah trim
    validation_errors = []

    if not project_name:
        validation_errors.append({"field": "project_name", "reason": "Nama proyek wajib diisi."})

    if not customer_name:
        validation_errors.append({"field": "customer_name", "reason": "Nama customer wajib diisi."})

    # Validasi target_submit tidak boleh masa lalu
    if target_submit < date.today():
        validation_errors.append(
            {
                "field": "target_submit",
                "reason": "Target submit tidak boleh tanggal di masa lalu.",
            }
        )

    # Validasi estimasi_nilai — parse Decimal dari string
    estimasi_decimal: Optional[Decimal] = None
    try:
        estimasi_decimal = Decimal(estimasi_nilai)
        if estimasi_decimal < Decimal("0.01"):
            validation_errors.append(
                {
                    "field": "estimasi_nilai",
                    "reason": "Estimasi nilai minimum adalah 0.01.",
                }
            )
        elif estimasi_decimal > Decimal("999999999999.00"):
            validation_errors.append(
                {
                    "field": "estimasi_nilai",
                    "reason": "Estimasi nilai maksimum adalah 999,999,999,999.00.",
                }
            )
    except (InvalidOperation, ValueError):
        validation_errors.append(
            {
                "field": "estimasi_nilai",
                "reason": "Format estimasi nilai tidak valid. Gunakan angka desimal.",
            }
        )

    # Validasi DQ Number (opsional — jika diisi, harus valid)
    import re

    validated_dq: Optional[str] = None
    if dq_number and dq_number.strip():
        dq_clean = dq_number.strip()
        if not re.match(r"^[A-Za-z0-9\-]{5,20}$", dq_clean):
            validation_errors.append(
                {
                    "field": "dq_number",
                    "reason": "Format DQ Number tidak valid (alfanumerik + hyphen, 5-20 karakter).",
                }
            )
        else:
            validated_dq = dq_clean

    # Validasi Kuesioner kualifikasi (skor dihitung backend dari jawaban ini)
    answers, answer_errors = parse_answers(qualification_answers)
    validation_errors.extend(answer_errors)

    # Validasi jumlah file
    if len(files) > MAX_FILES:
        validation_errors.append(
            {
                "field": "files",
                "reason": f"Maksimal {MAX_FILES} file per request.",
            }
        )

    # Tipe Source document wajib dipilih per file (error per file, indeks sama dengan `files`)
    for idx in range(len(files)):
        tipe = file_types[idx].strip() if idx < len(file_types) else ""
        if tipe not in DOC_TYPES:
            validation_errors.append(
                {
                    "field": f"files[{idx}].type",
                    "reason": "Tipe file wajib dipilih: MoM atau RFP.",
                }
            )

    # Return 422 jika ada error validasi
    if validation_errors:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_response(
                message="Validasi gagal. Periksa data yang dikirim.",
                data=validation_errors,
            ),
        )

    # === Proses file upload (partial failure handling) ===
    file_results: list[FileUploadResult] = []
    valid_files_data: list[tuple[str, bytes, str]] = []  # (filename, content, mime_type)
    valid_file_types: list[str] = []  # tipe Source document, paralel dengan valid_files_data

    for idx, file in enumerate(files):
        result, content = await _process_file_upload(file)
        file_results.append(result)
        if result.success and content is not None:
            mime_type = file.content_type or "application/octet-stream"
            valid_files_data.append((file.filename or "unknown", content, mime_type))
            valid_file_types.append(file_types[idx].strip())

    # === Buat record Project ===
    project_id = _generate_project_id()
    now = datetime.now(timezone.utc)

    # Tanpa file valid: rubrik dihitung sinkron dan gate 60 langsung diterapkan.
    # Dengan file: perilaku scoring file tidak berubah (status New + background task).
    rubric_scores = bant_rubric.compute_rubric_scores(answers, target_submit)
    rubric_total = bant_rubric.total_score(rubric_scores)
    scored_now = not valid_files_data
    # Dengan file: status `Scoring Pending` sampai analisis AI selesai (skor rubrik sudah disimpan).
    initial_status = (
        bant_rubric.decide_status(rubric_total) if scored_now else "Scoring Pending"
    )
    feedback: Optional[str] = None
    if scored_now and rubric_total < bant_rubric.GATE_THRESHOLD:
        feedback = bant_rubric.generate_feedback(rubric_scores)

    new_project = Project(
        id_project=project_id,
        project_name=project_name,
        customer_name=customer_name,
        target_submit=target_submit,
        estimasi_nilai=estimasi_decimal,
        dq_number=validated_dq,
        status=initial_status,
        # Lolos gate tanpa file: Requirement di-generate di background (#33).
        requirement_generation_status=(
            "pending" if scored_now and initial_status == "Pending Assignment" else None
        ),
        sales_pic=current_user.id,
        qualification_answers=answers,
        qualification_schema_version=bant_rubric.QUESTIONNAIRE_SCHEMA_VERSION,
        bant_score=rubric_total,
        bant_detail=rubric_scores.model_dump(),
        created_at=now,
        updated_at=now,
    )

    db.add(new_project)

    # Source document: baris `pending` per file valid (hanya teks hasil ekstraksi yang disimpan)
    extraction_items = []
    for (fname, content, mime_type), tipe in zip(valid_files_data, valid_file_types):
        source_doc = SourceDocument(
            id=uuid.uuid4(),
            id_project=project_id,
            filename=fname,
            doc_type=tipe,
            size_bytes=len(content),
            extraction_status="pending",
            truncated=False,
        )
        db.add(source_doc)
        extraction_items.append((source_doc.id, fname, content, mime_type))

    await db.commit()
    await db.refresh(new_project)

    logger.info(
        f"Proyek baru dibuat: {project_id} oleh {current_user.email} "
        f"({len(valid_files_data)} file valid dari {len(files)} total)"
    )

    # === Notifikasi Lead_SA (proyek langsung lolos gate) / trigger scoring file ===
    scoring_triggered = False

    if valid_files_data:
        # Ada file valid — trigger scoring engine di background
        background_tasks.add_task(
            _trigger_scoring_engine,
            project_id,
            valid_files_data,
        )
        scoring_triggered = True
        # Ekstraksi teks Source document: panggilan Gemini terpisah, tidak menahan respons/scoring
        background_tasks.add_task(extract_source_documents, project_id, extraction_items)
    elif initial_status == "Pending Assignment":
        from app.services.scoring_engine import scoring_engine

        try:
            await scoring_engine.notify_new_opportunity(db, project_id, rubric_total)
        except Exception as e:  # proyek sudah tersimpan; kegagalan notifikasi tidak boleh 500
            logger.error(f"Gagal mengirim notifikasi New Opportunity {project_id}: {e}")
        background_tasks.add_task(generate_pending_requirement, project_id)

    # === Build response ===
    response_data = ProjectResponse(
        id_project=project_id,
        project_name=project_name,
        customer_name=customer_name,
        target_submit=target_submit,
        estimasi_nilai=estimasi_decimal,
        status=initial_status,
        sales_pic=current_user.id,
        created_at=now,
        files=file_results,
        scoring_triggered=scoring_triggered,
        bant_score=rubric_total if scored_now else None,
        sub_scores=rubric_scores.model_dump() if scored_now else None,
        feedback=feedback,
    )

    return success_response(
        data=response_data.model_dump(mode="json"),
        message="Request proyek berhasil dibuat.",
    )
