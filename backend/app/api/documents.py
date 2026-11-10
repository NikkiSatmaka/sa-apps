"""
API endpoints untuk Document Tracking.
Menangani CRUD dokumen proyek dan state machine transisi status.

State Machine:
- Draft → Reviewed: SA, Lead_SA
- Reviewed → Final: SA, Lead_SA
- Final → Reviewed (mundur): HANYA Lead_SA
- Reviewed → Draft (mundur): HANYA Lead_SA
- Draft → Final (loncat): DITOLAK untuk semua role
"""

import logging
import random
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.document import Document
from app.models.project import Project
from app.models.user import User
from app.schemas.document import (
    DocTypeEnum,
    DocumentCreate,
    DocumentResponse,
    DocumentStatusUpdate,
)
from app.schemas.response import success_response
from app.services.requirement_generator import can_regenerate_requirement
from app.services.folder_provisioner import folder_provisioner
from app.services.notification_service import (
    NotificationEvent,
    NotificationEventType,
    notification_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Documents"])


def _generate_doc_id() -> str:
    """Generate ID dokumen unik dengan format DOC-{YYYYMMDD}-{random6}."""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"DOC-{date_part}-{random_part}"


def _to_response(doc: Document) -> dict:
    """Bentuk respons dokumen (JSON-ready), termasuk kolom khusus Requirement."""
    return DocumentResponse(
        id_doc=doc.id_doc,
        id_project=doc.id_project,
        doc_type=doc.doc_type,
        status=doc.status,
        gdrive_link=doc.gdrive_link,
        folder_type=doc.folder_type,
        notes=doc.notes,
        created_by=doc.created_by,
        updated_by=doc.updated_by,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        content=doc.content,
        is_overridden=doc.is_overridden,
        source_hash=doc.source_hash,
        generated_at=doc.generated_at,
        source_truncated=doc.source_truncated,
    ).model_dump(mode="json")


# Definisi transisi yang valid dalam state machine
VALID_TRANSITIONS = {
    "Draft": ["Reviewed"],  # Draft hanya bisa maju ke Reviewed
    "Reviewed": ["Final"],  # Reviewed hanya bisa maju ke Final
    "Final": [],  # Final tidak bisa maju (terminal state untuk forward)
}

# Transisi mundur — hanya bisa dilakukan oleh Lead_SA
BACKWARD_TRANSITIONS = {
    "Final": ["Reviewed"],  # Final bisa mundur ke Reviewed (Lead_SA only)
    "Reviewed": ["Draft"],  # Reviewed bisa mundur ke Draft (Lead_SA only)
    "Draft": [],  # Draft tidak bisa mundur
}


async def _handle_doc_ready(document: Document, db: AsyncSession) -> None:
    """
    Emit notifikasi `doc_ready` ke Sales DAN buka permission Drive Solutions
    saat dokumen berpindah ke status `Reviewed` dengan DQ Number sudah terisi.

    Sesuai spec Flow 2 (cabang "< 5 hari"): jika Sales sudah input DQ, saat
    dokumen SA berstatus `Reviewed`, link Google Drive Solutions terbuka
    otomatis untuk Sales disertai notifikasi (fix B13 / Fase 2A.3).

    Prasyarat agar side-effect dijalankan:
    - Proyek pemilik dokumen ada dan `dq_number` sudah terisi.
    Jika DQ belum terisi, tidak ada aksi (gating SLA/lock di luar scope ini).

    Side-effect ini TIDAK boleh menggagalkan transisi status dokumen; semua
    error hanya di-log (graceful degradation, konsisten dengan SLA timer).

    Args:
        document: Dokumen yang baru berpindah ke status `Reviewed`.
        db: Database session aktif.
    """
    # Ambil proyek pemilik dokumen untuk cek DQ + data Sales/folder
    project_result = await db.execute(
        select(Project).where(Project.id_project == document.id_project)
    )
    project = project_result.scalar_one_or_none()

    if project is None:
        logger.warning(
            f"Proyek '{document.id_project}' tidak ditemukan saat memproses "
            f"doc_ready untuk dokumen {document.id_doc}; skip."
        )
        return

    # Gating: tanpa DQ Number, doc_ready tidak di-emit (cabang "< 5 hari" belum terpenuhi)
    if project.dq_number is None:
        logger.info(
            f"Dokumen {document.id_doc} menjadi Reviewed tapi DQ Number proyek "
            f"'{project.id_project}' belum terisi; doc_ready tidak di-emit."
        )
        return

    # Ambil user Sales (requester/sales_pic) untuk notifikasi + akses Drive
    sales_result = await db.execute(select(User).where(User.id == project.sales_pic))
    sales_user = sales_result.scalar_one_or_none()

    if sales_user is None:
        logger.warning(
            f"User Sales ({project.sales_pic}) untuk proyek "
            f"'{project.id_project}' tidak ditemukan; skip doc_ready."
        )
        return

    # 1. Emit notifikasi doc_ready (in-app; email mengikuti T1 jika Gmail aktif)
    try:
        await notification_service.send_notification(
            NotificationEvent(
                event_type=NotificationEventType.DOC_READY,
                recipient_user_id=sales_user.id,
                recipient_email=sales_user.email,
                reference_id=project.id_project,
                metadata={
                    "project_name": project.project_name,
                    "customer_name": project.customer_name,
                    "doc_id": document.id_doc,
                    "doc_type": document.doc_type,
                    "message": (
                        f"Dokumen '{document.doc_type}' untuk proyek "
                        f"'{project.project_name}' sudah Reviewed dan siap diakses."
                    ),
                },
            )
        )
    except Exception as e:  # noqa: BLE001 - side-effect tidak boleh menggagalkan transisi
        logger.error(f"Gagal emit doc_ready untuk dokumen {document.id_doc}: {e}")

    # 2. Buka permission Drive Solutions untuk Sales (Viewer)
    if not project.gdrive_solutions_folder_id:
        logger.info(
            f"Proyek '{project.id_project}' belum punya gdrive_solutions_folder_id; "
            f"skip buka akses Solutions (notifikasi doc_ready tetap terkirim)."
        )
        return

    try:
        await folder_provisioner.unlock_solutions_folder(
            solutions_folder_id=project.gdrive_solutions_folder_id,
            sales_email=sales_user.email,
        )
    except Exception as e:  # noqa: BLE001 - side-effect tidak boleh menggagalkan transisi
        logger.error(
            f"Gagal membuka akses Solutions untuk Sales pada proyek '{project.id_project}': {e}"
        )


@router.post(
    "/projects/{project_id}/documents",
    summary="Buat dokumen baru untuk proyek",
    description=(
        "Membuat entry dokumen baru dengan status awal 'Draft'. "
        "Memvalidasi bahwa proyek ada sebelum membuat dokumen."
    ),
    status_code=status.HTTP_201_CREATED,
)
async def create_document(
    project_id: str,
    body: DocumentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Buat dokumen baru untuk proyek tertentu.

    Flow:
    1. Validasi proyek ada di database
    2. Generate id_doc unik
    3. Set status awal "Draft"
    4. Simpan ke database
    """
    # Requirement hanya dibuat sistem (generate AI), bukan lewat input link.
    if body.doc_type == DocTypeEnum.Requirement:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dokumen Requirement dibuat otomatis oleh sistem dan tidak dapat ditambahkan manual.",
        )

    # Validasi proyek ada
    project_result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = project_result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    # Generate ID dokumen dan timestamp
    now = datetime.now(timezone.utc)
    doc_id = _generate_doc_id()

    # Buat record dokumen baru
    new_document = Document(
        id_doc=doc_id,
        id_project=project_id,
        doc_type=body.doc_type.value,
        status="Draft",
        gdrive_link=body.gdrive_link,
        folder_type=body.folder_type.value,
        notes=body.notes,
        created_by=current_user.id,
        updated_by=None,
        created_at=now,
        updated_at=now,
    )
    db.add(new_document)
    await db.commit()
    await db.refresh(new_document)

    # Format response
    response_data = _to_response(new_document)

    return success_response(
        data=response_data,
        message=f"Dokumen '{body.doc_type.value}' berhasil dibuat untuk proyek '{project_id}'.",
    )


@router.get(
    "/projects/{project_id}/documents",
    summary="Daftar dokumen proyek",
    description="Menampilkan semua dokumen yang terkait dengan proyek tertentu.",
)
async def list_project_documents(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ambil daftar semua dokumen untuk proyek tertentu.
    Diurutkan berdasarkan waktu pembuatan (terbaru di atas).
    """
    # Validasi proyek ada
    project_result = await db.execute(select(Project).where(Project.id_project == project_id))
    project = project_result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    # Query semua dokumen untuk proyek ini
    result = await db.execute(
        select(Document)
        .where(Document.id_project == project_id)
        .order_by(Document.created_at.desc())
    )
    documents = result.scalars().all()

    # Format response
    documents_data = [
        _to_response(doc)
        for doc in documents
    ]

    return success_response(
        data={
            "documents": documents_data,
            "total": len(documents_data),
            # Status generate Requirement (#34): UI menampilkan pending/gagal + tombol coba lagi.
            "requirement_generation_status": project.requirement_generation_status,
            "can_regenerate_requirement": can_regenerate_requirement(project, current_user),
        },
        message=f"Ditemukan {len(documents_data)} dokumen untuk proyek '{project_id}'.",
    )


@router.patch(
    "/documents/{doc_id}/status",
    summary="Update status dokumen (state machine)",
    description=(
        "Mengubah status dokumen mengikuti aturan state machine. "
        "Transisi maju: Draft → Reviewed → Final (SA & Lead_SA). "
        "Transisi mundur: hanya Lead_SA. "
        "Loncat (Draft → Final): ditolak."
    ),
)
async def update_document_status(
    doc_id: str,
    body: DocumentStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Update status dokumen dengan enforcement state machine.

    Rules:
    - Transisi maju (Draft→Reviewed, Reviewed→Final): SA dan Lead_SA
    - Transisi mundur (Final→Reviewed, Reviewed→Draft): hanya Lead_SA
    - Loncat (Draft→Final): ditolak untuk semua role
    - Status "Final" hanya bisa diubah oleh Lead_SA
    - Catat timestamp dan user pada setiap transisi
    """
    # Cari dokumen
    doc_result = await db.execute(select(Document).where(Document.id_doc == doc_id))
    document = doc_result.scalar_one_or_none()

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dokumen dengan ID '{doc_id}' tidak ditemukan.",
        )

    current_status = document.status
    new_status = body.new_status.value

    # Cek jika status sama — tidak perlu transisi
    if current_status == new_status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dokumen sudah berstatus '{current_status}'. Tidak ada perubahan.",
        )

    # Cek proteksi: status "Final" hanya bisa diubah oleh Lead_SA
    if current_status == "Final" and current_user.role != "Lead_SA":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Hanya Lead_SA yang dapat mengubah status dokumen yang sudah 'Final'."),
        )

    # Cek apakah transisi maju yang valid
    is_forward = new_status in VALID_TRANSITIONS.get(current_status, [])

    # Cek apakah transisi mundur yang valid (hanya Lead_SA)
    is_backward = new_status in BACKWARD_TRANSITIONS.get(current_status, [])

    if is_forward:
        # Transisi maju — SA dan Lead_SA boleh
        pass
    elif is_backward:
        # Transisi mundur — hanya Lead_SA
        if current_user.role != "Lead_SA":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Hanya Lead_SA yang dapat melakukan transisi mundur. "
                    f"Transisi '{current_status}' → '{new_status}' memerlukan role Lead_SA."
                ),
            )
    else:
        # Transisi tidak valid (loncat atau arah yang tidak dikenali)
        valid_forward = VALID_TRANSITIONS.get(current_status, [])
        valid_backward = BACKWARD_TRANSITIONS.get(current_status, [])
        all_valid = valid_forward + valid_backward

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Transisi status tidak valid: '{current_status}' → '{new_status}'. "
                f"Dari status '{current_status}', transisi yang diizinkan: "
                f"{all_valid if all_valid else 'tidak ada (terminal state)'}."
            ),
        )

    # Update status, timestamp, dan user
    now = datetime.now(timezone.utc)
    document.status = new_status
    document.updated_at = now
    document.updated_by = current_user.id

    await db.commit()
    await db.refresh(document)

    # Side-effect doc_ready: HANYA saat transisi ke `Reviewed` dengan DQ terisi.
    # Transisi lain (ke Final, mundur, dll) tidak memicu ini (fix B13 / Fase 2A.3).
    # Requirement (konten turunan AI, bukan dokumen kerja SA) tidak memicu doc_ready
    # maupun pembukaan folder Solutions (#33).
    if new_status == "Reviewed" and document.doc_type != "Requirement":
        await _handle_doc_ready(document, db)

    # Format response
    response_data = _to_response(document)

    return success_response(
        data=response_data,
        message=(
            f"Status dokumen '{doc_id}' berhasil diubah: '{current_status}' → '{new_status}'."
        ),
    )
