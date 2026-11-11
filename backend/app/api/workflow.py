"""
API endpoint untuk workflow status proyek.
Menangani transisi status proyek dengan validasi state machine,
role-based access control, dan pencatatan audit log.

Workflow valid:
  New → Pending Assignment → Assigned → Ready → Closed-Win → Handover Complete

Status khusus:
  "Lost" — hanya Lead_SA, dari status manapun kecuali "Handover Complete"
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
    "New": "Pending Assignment",
    "Pending Assignment": "Assigned",
    "Assigned": "Ready",
    "Ready": "Closed-Win",
    "Closed-Win": "Handover Complete",
}

# Status yang tidak bisa diubah ke "Lost"
LOST_EXCLUDED_STATUSES = ("Handover Complete", "Lost")


def _get_valid_next_statuses(current_status: str, user_role: str) -> list[str]:
    """
    Mendapatkan daftar status yang valid dari status saat ini.
    Mempertimbangkan role user untuk status khusus (Lost).
    """
    valid = []

    # Transisi forward
    next_status = VALID_FORWARD_TRANSITIONS.get(current_status)
    if next_status:
        valid.append(next_status)

    # Status "Lost" — hanya Lead_SA/Admin, dari status manapun kecuali "Handover Complete" dan "Lost" sendiri
    if user_role in ("Lead_SA", "Admin") and current_status not in LOST_EXCLUDED_STATUSES:
        valid.append("Lost")

    return valid


def _is_valid_transition(current_status: str, new_status: str, user_role: str) -> bool:
    """Validasi apakah transisi status yang diminta valid."""
    valid_statuses = _get_valid_next_statuses(current_status, user_role)
    return new_status in valid_statuses


def _generate_audit_id() -> str:
    """Generate ID audit log unik dengan format AUDIT-{YYYYMMDD}-{random6}."""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"AUDIT-{date_part}-{random_part}"


def _pesan_ditolak_ubah_status(peran: str) -> str:
    """Pesan 403 per peran (kontrak lama dipertahankan); aturannya ada di TingkatAkses.UBAH_STATUS."""
    if peran == "Sales":
        return "Anda hanya dapat mengubah status proyek milik Anda sendiri."
    if peran == "SA":
        return "Anda hanya dapat mengubah status proyek yang ditugaskan kepada Anda."
    return "Role Anda tidak memiliki izin untuk operasi ini."


async def _notify_mandatory_hld(project: Project, db: AsyncSession) -> None:
    """
    Kirim notifikasi wajib "buat HLD" ke SA saat proyek menjadi Closed-Win.

    Spec Flow 4 langkah 1. Memakai event `status_change` dengan flag
    `mandatory_hld` di metadata (event_type baru butuh migration CheckConstraint
    tanpa manfaat tambahan). Kegagalan di sini tidak boleh menggagalkan transisi.
    """
    if project.assigned_sa is None:
        logger.warning(
            f"Proyek {project.id_project} Closed-Win tapi belum punya SA; "
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
                subject="[Portal SA] Wajib: buat HLD untuk proyek Closed-Win",
                metadata={
                    "project_name": project.project_name,
                    "customer_name": project.customer_name,
                    "new_status": "Closed-Win",
                    "mandatory_hld": True,
                    "message": (
                        f"Proyek '{project.project_name}' berstatus Closed-Win. "
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
        "Lead_SA (semua proyek + status Lost)."
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
    if new_status == "Lost" and current_user.role not in ("Lead_SA", "Admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hanya Lead_SA atau Admin yang dapat mengubah status proyek menjadi 'Lost'.",
        )

    # Validasi transisi menggunakan state machine
    if not _is_valid_transition(old_status, new_status, current_user.role):
        valid_next = _get_valid_next_statuses(old_status, current_user.role)
        valid_str = ", ".join(f"'{s}'" for s in valid_next) if valid_next else "tidak ada (status terminal)"

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Transisi status tidak valid: '{old_status}' → '{new_status}'. "
                f"Transisi yang diperbolehkan dari status '{old_status}': {valid_str}."
            ),
        )

    # === 4. Update status proyek ===
    now = datetime.now(timezone.utc)
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
        new_value={"status": new_status},
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

    # === 5b. Closed-Win → notifikasi wajib buat HLD ke SA (Flow 4 langkah 1) ===
    if new_status == "Closed-Win":
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
            new_value={"status": new_status},
            created_at=now,
        ),
    )

    return success_response(
        data=response_data.model_dump(mode="json"),
        message=f"Status proyek '{project.project_name}' berhasil diubah dari '{old_status}' ke '{new_status}'.",
    )
