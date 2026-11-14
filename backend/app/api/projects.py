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

from app.core import status as status_konst
from app.core.database import get_db
from app.core.dependencies import (
    TingkatAkses,
    boleh_membuat_proyek,
    PeranUser,
    adalah_privileged,
    ensure_project_access,
    get_current_user,
)
from app.models.project import Project
from app.models.project_assignment import ProjectAssignment
from app.models.project_collaborator import ProjectCollaborator
from app.models.sla_tracking import SLATracking
from app.models.source_document import DOC_TYPES, SourceDocument
from app.models.user import User
from app.schemas.project import FileUploadResult, ProjectResponse
from app.schemas.qualification import parse_answers, validate_answers
from app.schemas.response import error_response, success_response
from app.services import bant_rubric
from app.services.scoring_engine import scoring_engine
from app.services.qualification_view import build_qualification_view
from app.services.requirement_generator import (
    generate_pending_requirement,
    resummarize_if_source_changed,
)
from app.services.source_document_extractor import extract_source_documents
from app.services.dq_akses import hentikan_timer_bila_pertama, terapkan_dq

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["Projects"])


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
                f"total_score={result.total_score}, status={result.status}, "
                f"qualification_state={result.qualification_state}"
            )
    except Exception as e:
        logger.error(f"[ScoringEngine] Gagal memproses proyek {project_id}: {e}")
        # Jaring pengaman: jangan biarkan proyek menggantung di qualification_state Scoring
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


def _ringkas_orang(user: Optional[User], user_id: Optional[uuid.UUID]) -> Optional[dict]:
    """Ringkasan orang pada project (id+nama+email); None bila tidak ada orangnya."""
    if user_id is None:
        return None
    return {
        "id": str(user_id),
        "name": user.name if user else None,
        "email": user.email if user else None,
    }


async def _muat_user(db: AsyncSession, ids) -> dict[uuid.UUID, User]:
    """Muat beberapa user sekaligus (satu query), kunci = id."""
    ids = {i for i in ids if i is not None}
    if not ids:
        return {}
    hasil = await db.execute(select(User).where(User.id.in_(ids)))
    return {u.id: u for u in hasil.scalars().all()}


async def _pilih_user_berrole(
    db: AsyncSession, field: str, nilai: Optional[str], role: PeranUser, errors: list[dict]
) -> Optional[User]:
    """Validasi pilihan user (UUID) harus ada dan berrole `role`; tambah error bila tidak."""
    try:
        user_id = uuid.UUID(nilai)  # type: ignore[arg-type]
    except (ValueError, TypeError, AttributeError):
        errors.append({"field": field, "reason": f"{field} harus berupa ID user yang valid."})
        return None
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or user.role != role:
        errors.append(
            {"field": field, "reason": f"User yang dipilih untuk {field} harus berrole {role}."}
        )
        return None
    return user


async def _tentukan_orang(
    db: AsyncSession,
    pembuat: User,
    product_pic: Optional[str],
    sales_pic: Optional[str],
    errors: list[dict],
) -> tuple[Optional[User], Optional[User]]:
    """Tentukan (Product PIC, Sales PIC) saat membuat project (ADR 0014), berdasarkan role pembuat.

    - Product: dirinya `product_pic`; Sales opsional.
    - Sales: dirinya `sales_pic`; wajib memilih Product (isian `sales_pic` diabaikan).
    - Lead_SA / `is_admin` (role lain): wajib memilih Product; Sales opsional.
    """
    product_pic = (product_pic or "").strip() or None
    sales_pic = (sales_pic or "").strip() or None
    produk: Optional[User] = None
    sales: Optional[User] = None

    if pembuat.role == PeranUser.PRODUCT:
        produk = pembuat
    elif product_pic is None:
        errors.append({"field": "product_pic", "reason": "Product PIC wajib dipilih."})
    else:
        produk = await _pilih_user_berrole(db, "product_pic", product_pic, PeranUser.PRODUCT, errors)

    if pembuat.role == PeranUser.SALES:
        sales = pembuat
    elif sales_pic is not None:
        sales = await _pilih_user_berrole(db, "sales_pic", sales_pic, PeranUser.SALES, errors)
    return produk, sales


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
    involved: Optional[str] = Query(
        None, description="Filter: 'me' untuk proyek yang melibatkan user login (semua peran)"
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
    - involved=me → proyek yang melibatkan user saat ini (semua peran, ADR 0014)
    - sales_pic=me → proyek yang dibuat oleh user saat ini
    - assigned_to=me → proyek yang ditugaskan ke user saat ini
    - status=<value> → filter berdasarkan status

    Sort:
    - -updated_at (default): terbaru diupdate
    - updated_at: terlama diupdate
    - -created_at: terbaru dibuat
    """
    query = select(Project)

    # Semua proyek dapat dilihat semua pengguna terautentikasi (keputusan 2026-11-10); hanya akses
    # TULIS yang dibatasi. Query param sales_pic=me / assigned_to=me hanyalah penyempit opsional.
    # Penyempit opsional dari query param (hanya mempersempit, tidak memperluas akses)
    if involved == "me":
        query = query.where(_terlibat(current_user.id))
    elif sales_pic == "me":
        # Product PIC setara Sales PIC (ADR 0012/0014). Dipertahankan untuk kompatibilitas;
        # UI memakai `involved=me` (#109).
        query = query.where(
            or_(Project.sales_pic == current_user.id, Project.product_pic == current_user.id)
        )
    elif assigned_to == "me":
        query = query.where(_sa_ditugaskan_ke(current_user.id))

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
    orang = await _muat_user(
        db, {i for p in projects for i in (p.created_by, p.product_pic, p.sales_pic)}
    )
    projects_data = []
    for p in projects:
        projects_data.append(
            {
                "id_project": p.id_project,
                "project_name": p.project_name,
                "customer_name": p.customer_name,
                "status": p.status,
                "qualification_state": p.qualification_state,
                "dq_number": p.dq_number,
                "bant_score": p.bant_score,
                "use_case_tags": p.use_case_tags or [],
                "estimasi_nilai": str(p.estimasi_nilai) if p.estimasi_nilai is not None else None,
                "target_submit": p.target_submit.isoformat() if p.target_submit else None,
                "assigned_sa": str(p.assigned_sa) if p.assigned_sa else None,
                "created_by": _ringkas_orang(orang.get(p.created_by), p.created_by),
                "product_pic": _ringkas_orang(orang.get(p.product_pic), p.product_pic),
                "sales_pic": _ringkas_orang(orang.get(p.sales_pic), p.sales_pic),
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
    involved: Optional[str] = Query(
        None, description="Filter: 'me' untuk proyek yang melibatkan user login (semua peran)"
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hitung jumlah proyek per status, dengan filter berbasis role."""
    query = select(Project.status, func.count(Project.id_project))

    # Semua proyek dapat dilihat semua pengguna terautentikasi (sama seperti list_projects).
    # Penyempit opsional dari query param
    if involved == "me":
        query = query.where(_terlibat(current_user.id))
    elif sales_pic == "me":
        # Product PIC setara Sales PIC (ADR 0012/0014); dipertahankan untuk kompatibilitas.
        query = query.where(
            or_(Project.sales_pic == current_user.id, Project.product_pic == current_user.id)
        )
    elif assigned_to == "me":
        query = query.where(_sa_ditugaskan_ke(current_user.id))

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


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Submit request SA (request proyek pre-sales baru)",
    description=(
        "Endpoint untuk mengajukan Request SA (proyek pre-sales baru). "
        "Dapat diakses oleh role Sales, Product, Lead_SA, dan `is_admin` (SA ditolak). "
        "Menerima form data + file attachment (PDF/DOCX, max 20MB/file, max 5 files). "
        "Menerima jawaban Kuesioner kualifikasi (qualification_answers, JSON); skor BANT "
        "dihitung backend. Tanpa file: gate 60 langsung diterapkan. Dengan file: Intake + qualification_state 'Scoring' "
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
    product_pic: Optional[str] = Form(
        default=None,
        description=(
            "ID user Product penanggung jawab. Wajib untuk pembuat Sales/Lead_SA/is_admin; "
            "diabaikan untuk pembuat Product (dirinya sendiri)."
        ),
    ),
    sales_pic: Optional[str] = Form(
        default=None,
        description=(
            "ID user Sales PIC (opsional untuk pembuat Product/Lead_SA/is_admin; "
            "pembuat Sales selalu dirinya sendiri)."
        ),
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
    3. Buat record Project dengan status awal sesuai skor rubrik (Intake + Scoring bila ada file)
    4. Trigger Scoring_Engine async jika ada file valid
    5. Return 201 dengan data proyek + hasil upload per file
    """
    if not boleh_membuat_proyek(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Sales, Product, Lead_SA, atau Admin yang dapat membuat proyek.",
        )

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

    # Orang per project: Product PIC wajib, Sales PIC opsional (ADR 0014)
    produk_user, sales_user = await _tentukan_orang(
        db, current_user, product_pic, sales_pic, validation_errors
    )

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
    # Dengan file: perilaku scoring file tidak berubah (Intake + Scoring + background task).
    rubric_scores = bant_rubric.compute_rubric_scores(answers, target_submit)
    rubric_total = bant_rubric.total_score(rubric_scores)
    scored_now = not valid_files_data
    # Dengan file: Intake + `Scoring` sampai analisis AI selesai (skor rubrik sudah disimpan).
    initial_status, initial_state = (
        bant_rubric.decide_gate(rubric_total)
        if scored_now
        else (status_konst.INTAKE, status_konst.QS_SCORING)
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
        qualification_state=initial_state,
        # Lolos gate tanpa file: Requirement di-generate di background (#33).
        requirement_generation_status=(
            "pending" if scored_now and initial_status == status_konst.AWAITING_ASSIGNMENT else None
        ),
        created_by=current_user.id,
        product_pic=produk_user.id,
        sales_pic=sales_user.id if sales_user else None,
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
    elif initial_status == status_konst.AWAITING_ASSIGNMENT:
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
        qualification_state=initial_state,
        created_by=_ringkas_orang(current_user, current_user.id),
        product_pic=_ringkas_orang(produk_user, produk_user.id),
        sales_pic=_ringkas_orang(sales_user, sales_user.id) if sales_user else None,
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
