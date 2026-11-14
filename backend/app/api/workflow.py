"""
API endpoint untuk workflow status proyek.
Menangani transisi status proyek dengan validasi state machine,
role-based access control, dan pencatatan audit log.

Workflow valid (ADR 0013):
  Awaiting Assignment → Assigned → Submitted → Won
  Won → Handed Over hanya lewat POST /projects/{id}/handover (bukan endpoint ini)
  Intake → Awaiting Assignment hanya oleh sistem (gate BANT), bukan endpoint ini

Status khusus:
  "Lost" — hanya Lead_SA/Admin, dari status manapun kecuali "Handed Over"; `reason` wajib
  dan disimpan ke `lost_reason`
"""

import logging
import random
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import status as status_konst
from app.core.database import get_db
from app.core.dependencies import (
    PERAN_REQUESTER,
    TingkatAkses,
    adalah_privileged,
    ensure_project_access,
    get_current_user,
)
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.user import User
from app.schemas.response import error_response, success_response
from app.schemas.workflow import StatusTransitionResponse, StatusUpdateRequest, AuditLogEntry
from app.services.notification_service import (
    NotificationEvent,
    NotificationEventType,
    notification_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Workflow"])

# === Definisi State Machine ===

# Transisi forward yang valid (urutan linear)
VALID_FORWARD_TRANSITIONS: dict[str, str] = {
    status_konst.AWAITING_ASSIGNMENT: status_konst.ASSIGNED,
    status_konst.ASSIGNED: status_konst.SUBMITTED,
    status_konst.SUBMITTED: status_konst.WON,
    # `Won` → `Handed Over` SENGAJA tidak ada di sini (issue #76): status itu hanya
    # boleh dicapai lewat `POST /projects/{id}/handover`, yang memeriksa prasyarat (HLD Final,
    # email PMO/Delivery, folder Drive), membuat folder, dan mengirim notifikasi.
}

# Status yang hanya dapat dicapai lewat endpoint khusus, bukan PATCH /status
STATUS_VIA_ENDPOINT_KHUSUS: dict[str, str] = {
    status_konst.HANDED_OVER: "POST /projects/{id}/handover",
}

# Status yang tidak bisa diubah ke "Lost"
LOST_EXCLUDED_STATUSES = (status_konst.HANDED_OVER, status_konst.LOST)


def _get_valid_next_statuses(current_status: str, privileged: bool) -> list[str]:
    """
    Mendapatkan daftar status yang valid dari status saat ini.
    Mempertimbangkan hak privileged (Lead_SA/admin) untuk status khusus (Lost).
    """
    valid = []

    # Transisi forward
    next_status = VALID_FORWARD_TRANSITIONS.get(current_status)
    if next_status:
        valid.append(next_status)

    # Status "Lost" — hanya Lead_SA/Admin, dari status manapun kecuali "Handed Over" dan "Lost" sendiri
    if privileged and current_status not in LOST_EXCLUDED_STATUSES:
        valid.append(status_konst.LOST)

    return valid


def _is_valid_transition(current_status: str, new_status: str, privileged: bool) -> bool:
    """Validasi apakah transisi status yang diminta valid."""
    valid_statuses = _get_valid_next_statuses(current_status, privileged)
    return new_status in valid_statuses


def _generate_audit_id() -> str:
    """Generate ID audit log unik dengan format AUDIT-{YYYYMMDD}-{random6}."""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"AUDIT-{date_part}-{random_part}"


def _pesan_ditolak_ubah_status(peran: str) -> str:
    """Pesan 403 per peran (kontrak lama dipertahankan); aturannya ada di TingkatAkses.UBAH_STATUS."""
    if peran in PERAN_REQUESTER:
        return "Anda hanya dapat mengubah status proyek milik Anda sendiri."
    if peran == "SA":
        return "Anda hanya dapat mengubah status proyek yang ditugaskan kepada Anda."
    return "Role Anda tidak memiliki izin untuk operasi ini."


async def _notify_mandatory_hld(project: Project, db: AsyncSession) -> None:
    """
    Kirim notifikasi wajib "buat HLD" ke SA saat proyek menjadi Won.

    Spec Flow 4 langkah 1. Memakai event `status_change` dengan flag
    `mandatory_hld` di metadata (event_type baru butuh migration CheckConstraint
    tanpa manfaat tambahan). Kegagalan di sini tidak boleh menggagalkan transisi.
    """
    if project.assigned_sa is None:
        logger.warning(
            f"Proyek {project.id_project} Won tapi belum punya SA; "
            f"notifikasi wajib HLD dilewati."
        )
        return

    try:
        result = await db.execute(select(User).where(User.id == project.assigned_sa))
        sa_user = result.scalar_one_or_none()
        if sa_user is None:
            logger.warning(
                f"SA {project.assigned_sa} untuk proyek {project.id_project} "
                f"tidak ditemukan; notifikasi wajib HLD dilewati."
            )
            return

        await notification_service.send_notification(
            NotificationEvent(
                event_type=NotificationEventType.STATUS_CHANGE,
                recipient_user_id=sa_user.id,
                recipient_email=sa_user.email,
                reference_id=project.id_project,
                subject="[Portal SA] Wajib: buat HLD untuk proyek Won",
                metadata={
                    "project_name": project.project_name,
                    "customer_name": project.customer_name,
                    "new_status": status_konst.WON,
                    "mandatory_hld": True,
                    "message": (
                        f"Proyek '{project.project_name}' berstatus Won. "
                        f"Segera buat HLD (High Level Document)."
                    ),
                },
            )
        )
    except Exception as e:  # noqa: BLE001 - side-effect tidak boleh menggagalkan transisi
        logger.error(f"Gagal mengirim notifikasi wajib HLD untuk {project.id_project}: {e}")


@router.patch(
    "/projects/{project_id}/status",
    summary="Ubah status proyek",
    description=(
        "Mengubah status proyek sesuai workflow yang valid. "
        "Mencatat perubahan di audit log. "
        "Role-based: Sales (proyek sendiri), SA (proyek ditugaskan), "
        "Lead_SA (semua proyek + status Lost; wajib `reason`)."
    ),
)
async def update_project_status(
    project_id: str,
    body: StatusUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ubah status proyek dengan validasi state machine.

    Flow:
    1. Validasi proyek ada
    2. Validasi akses user terhadap proyek (role-based)
    3. Validasi transisi status (state machine)
    4. Update status proyek
    5. Catat perubahan di audit log
    6. Return response dengan data proyek dan audit log
    """

    # === 1. Cari proyek ===
    result = await db.execute(
        select(Project).where(Project.id_project == project_id)
    )
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proyek dengan ID '{project_id}' tidak ditemukan.",
        )

    # === 2. Validasi akses user ===
    # Titik keputusan bersama (UBAH_STATUS): Lead_SA/Admin semua proyek; Sales hanya PIC-nya;
    # SA hanya yang ditugaskan; role lain ditolak. Collaborator tidak dihitung.
    await ensure_project_access(
        db,
        project,
        current_user,
        TingkatAkses.UBAH_STATUS,
        pesan=_pesan_ditolak_ubah_status(current_user.role),
    )

    # === 3. Validasi transisi status ===
    old_status = project.status
    new_status = body.new_status

    # Khusus status "Lost" — hanya Lead_SA/Admin yang bisa
    if new_status == status_konst.LOST and not adalah_privileged(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Lead_SA atau Admin yang dapat mengubah status proyek menjadi 'Lost'.",
        )

    # Status yang hanya boleh dicapai lewat endpoint khusus: arahkan, jangan hanya "tidak valid".
    if new_status in STATUS_VIA_ENDPOINT_KHUSUS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Status '{new_status}' tidak dapat diubah lewat endpoint ini. "
                f"Gunakan {STATUS_VIA_ENDPOINT_KHUSUS[new_status]}."
            ),
        )

    # Validasi transisi menggunakan state machine
    if not _is_valid_transition(old_status, new_status, adalah_privileged(current_user)):
        valid_next = _get_valid_next_statuses(old_status, adalah_privileged(current_user))
        valid_str = ", ".join(f"'{s}'" for s in valid_next) if valid_next else "tidak ada (status terminal)"

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Transisi status tidak valid: '{old_status}' → '{new_status}'. "
                f"Transisi yang diperbolehkan dari status '{old_status}': {valid_str}."
            ),
        )

    # `Lost` wajib beralasan (CHECK `chk_projects_lost_reason`); alasan disimpan di proyek.
    alasan = (body.reason or "").strip()
    if new_status == status_konst.LOST and not alasan:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Alasan (reason) wajib diisi untuk mengubah status proyek menjadi 'Lost'.",
        )

    # === 4. Update status proyek ===
    now = datetime.now(timezone.utc)
    nilai_baru: dict = {"status": new_status}
    if new_status == status_konst.LOST:
        project.previous_status = old_status
        project.lost_reason = alasan
        nilai_baru["lost_reason"] = alasan
    project.status = new_status
    project.updated_at = now

    # === 5. Catat di audit log ===
    audit_id = _generate_audit_id()
    audit_log = AuditLog(
        id=audit_id,
        entity_type="project",
        entity_id=project_id,
        action="status_change",
        performed_by=current_user.id,
        old_value={"status": old_status},
        new_value=nilai_baru,
        created_at=now,
    )
    db.add(audit_log)

    # Commit perubahan
    await db.commit()
    await db.refresh(project)

    logger.info(
        f"Status proyek {project_id} diubah: '{old_status}' → '{new_status}' "
        f"oleh {current_user.email} (role: {current_user.role})"
    )

    # === 5b. Won → notifikasi wajib buat HLD ke SA (Flow 4 langkah 1) ===
    if new_status == status_konst.WON:
        await _notify_mandatory_hld(project, db)

    # === 6. Build response ===
    response_data = StatusTransitionResponse(
        id_project=project.id_project,
        project_name=project.project_name,
        old_status=old_status,
        new_status=new_status,
        audit_log=AuditLogEntry(
            id=audit_id,
            entity_type="project",
            entity_id=project_id,
            action="status_change",
            performed_by=str(current_user.id),
            old_value={"status": old_status},
            new_value=nilai_baru,
            created_at=now,
        ),
    )

    return success_response(
        data=response_data.model_dump(mode="json"),
        message=f"Status proyek '{project.project_name}' berhasil diubah dari '{old_status}' ke '{new_status}'.",
    )
