"""Project intake, upload validation, and scoring API endpoint."""

import logging
import random
import string
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core import status as status_konst
from app.core.database import get_db
from app.core.dependencies import boleh_membuat_proyek, PeranUser, get_current_user
from app.models.customer import Customer, normalize_customer_name
from app.models.project import Project
from app.models.source_document import DOC_TYPES, SourceDocument
from app.models.user import User
from app.schemas.project import FileUploadResult, ProjectResponse
from app.schemas.qualification import parse_answers
from app.schemas.response import error_response, success_response
from app.services import bant_rubric
from app.services.scoring_engine import scoring_engine
from app.services.requirement_generator import generate_pending_requirement
from app.services.source_document_extractor import extract_source_documents
from app.api.project_api_helpers import _ringkas_orang

logger = logging.getLogger(__name__)
router = APIRouter()


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
    customer_id: Optional[uuid.UUID] = Form(default=None),
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
 
    # Resolve a stable Customer identity; legacy name-only clients create/reuse it by case-folded name.
    if customer_id:
        customer = await db.get(Customer, customer_id)
        if customer is None:
            raise HTTPException(status_code=422, detail="Customer tidak ditemukan.")
    else:
        normalized_customer = normalize_customer_name(customer_name)
        customer = await db.scalar(select(Customer).where(Customer.normalized_name == normalized_customer))
        if customer is None:
            customer = Customer(name=customer_name, normalized_name=normalized_customer)
            nested = await db.begin_nested()
            try:
                db.add(customer)
                await db.flush()
            except IntegrityError as exc:
                await nested.rollback()
                customer = await db.scalar(
                    select(Customer).where(Customer.normalized_name == normalized_customer)
                )
                if customer is None:
                    raise exc
    customer_name = customer.name


    new_project = Project(
        id_project=project_id,
        project_name=project_name,
        customer_name=customer_name,
        customer_id=customer.id,
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
