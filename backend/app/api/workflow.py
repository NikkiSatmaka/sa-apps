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
    adalah_admin,
    ensure_project_access,
    get_current_user,
)
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.project_assignment import ProjectAssignment
from app.models.project import Project
from app.models.user import User
from app.schemas.response import error_response, success_response
from app.schemas.workflow import StatusTransitionResponse, StatusUpdateRequest, AuditLogEntry
from app.services.sla_timer import sla_timer
from app.services.notification_service import (
    NotificationEvent,
    NotificationEventType,
    notification_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Workflow"])

# === Definisi State Machine (ADR 0013, spec §2.0 "Siklus status") ===

# Transisi yang boleh lewat PATCH /projects/{id}/status, beserta tingkat akses yang berhak
# (di atas gerbang UBAH_STATUS: hubungan ke proyek). Lead_SA dan Admin selalu berhak.
#
# TIDAK ada di tabel ini, dengan sengaja:
# - `Intake` → `Awaiting Assignment`: otomatis oleh sistem saat gate BANT lolos.
# - `Awaiting Assignment` → `Assigned`: penugasan SA (POST /projects/{id}/assign).
# - `Assigned` → `In Progress`: otomatis dari activity log/subtask pertama (#122).
# - Lanjut dari `On Hold` dan buka kembali `Closed`/`Lost`: bukan baris tabel karena tujuannya
#   dinamis (selalu `previous_status`); ditangani cabang `_STATUS_KEMBALI` di endpoint (#122).
# - `Won` → `Handed Over`: hanya POST /projects/{id}/handover (issue #76: memeriksa HLD Final,
#   email PMO/Delivery, folder Drive).
_SEBELUM_HANDED_OVER = (
    status_konst.INTAKE,
    status_konst.AWAITING_ASSIGNMENT,
    status_konst.ASSIGNED,
    status_konst.IN_PROGRESS,
    status_konst.SUBMITTED,
    status_konst.WON,
    status_konst.ON_HOLD,
)

# Status yang bisa dijeda (`On Hold`): dari `Awaiting Assignment` sampai `Submitted` (ADR 0013).
_BOLEH_DIJEDA = (
    status_konst.AWAITING_ASSIGNMENT,
    status_konst.ASSIGNED,
    status_konst.IN_PROGRESS,
    status_konst.SUBMITTED,
)

# Status yang keluar HANYA ke `previous_status` (lanjut dari jeda, buka kembali) dan hak per
# status asal. Lanjut: Lead_SA/Admin/Sales/Product PIC. Buka kembali: hanya `is_admin`
# (diperiksa terpisah di endpoint karena Lead_SA ikut "privileged" di `TingkatAkses`).
_STATUS_KEMBALI: dict[str, TingkatAkses] = {
    status_konst.ON_HOLD: TingkatAkses.UBAH_STATUS_PIC,
    status_konst.CLOSED: TingkatAkses.UBAH_STATUS_LEAD,
    status_konst.LOST: TingkatAkses.UBAH_STATUS_LEAD,
}

TRANSISI_HAK: dict[tuple[str, str], TingkatAkses] = {
    (status_konst.ASSIGNED, status_konst.SUBMITTED): TingkatAkses.UBAH_STATUS_SA,
    (status_konst.IN_PROGRESS, status_konst.SUBMITTED): TingkatAkses.UBAH_STATUS_SA,
    (status_konst.SUBMITTED, status_konst.IN_PROGRESS): TingkatAkses.UBAH_STATUS_SA,
    (status_konst.SUBMITTED, status_konst.WON): TingkatAkses.UBAH_STATUS_PIC,
    (status_konst.HANDED_OVER, status_konst.CLOSED): TingkatAkses.UBAH_STATUS_LEAD,
    # On Hold: jeda; timer SLA berhenti. Lanjut ke `previous_status` lewat `_STATUS_KEMBALI`.
    **{(dari, status_konst.ON_HOLD): TingkatAkses.UBAH_STATUS_PIC for dari in _BOLEH_DIJEDA},
    # Lost: dari status mana pun sebelum Handed Over; alasan wajib.
    **{(dari, status_konst.LOST): TingkatAkses.UBAH_STATUS_LEAD for dari in _SEBELUM_HANDED_OVER},
}

# Transisi sah yang HANYA boleh lewat endpoint khusus: ditolak di PATCH dan diarahkan.
TRANSISI_VIA_ENDPOINT: dict[tuple[str, str], str] = {
    (status_konst.WON, status_konst.HANDED_OVER): "POST /projects/{id}/handover",
    (status_konst.AWAITING_ASSIGNMENT, status_konst.ASSIGNED): "POST /projects/{id}/assign",
}

# Dokumen wajib untuk `Submitted`: masing-masing minimal satu dokumen berstatus ini.
DOKUMEN_WAJIB_SUBMITTED = ("PropTek", "BOQ", "Mandays")
STATUS_DOKUMEN_MINIMAL_REVIEWED = ("Reviewed", "Final")


def status_berikutnya(status_sekarang: str, previous_status: str | None = None) -> list[str]:
    """Tujuan yang valid lewat PATCH /status dari `status_sekarang` (tanpa memandang peran).

    Dari `On Hold`/`Closed`/`Lost` ditambah `previous_status` (tujuan dinamis) bila ada.
    """
    tujuan = [ke for (dari, ke) in TRANSISI_HAK if dari == status_sekarang]
    if status_sekarang in _STATUS_KEMBALI and previous_status:
        tujuan.insert(0, previous_status)
    return tujuan


def transisi_valid(status_sekarang: str, status_baru: str) -> bool:
    """Apakah (`status_sekarang` → `status_baru`) ada di tabel transisi PATCH?"""
    return (status_sekarang, status_baru) in TRANSISI_HAK


def hak_transisi(status_sekarang: str, status_baru: str) -> TingkatAkses | None:
    """Tingkat akses yang diminta transisi, atau None bila transisinya tidak valid."""
    return TRANSISI_HAK.get((status_sekarang, status_baru))


_PESAN_HAK_TRANSISI: dict[TingkatAkses, str] = {
    TingkatAkses.UBAH_STATUS_SA: (
        "Hanya SA yang ditugaskan, Lead_SA, atau Admin yang dapat menjalankan transisi status ini."
    ),
    TingkatAkses.UBAH_STATUS_PIC: (
        "Hanya Sales/Product PIC proyek ini, Lead_SA, atau Admin yang dapat menjalankan "
        "transisi status ini ('Won', 'On Hold', atau melanjutkan dari 'On Hold')."
    ),
    TingkatAkses.UBAH_STATUS_LEAD: (
        "Hanya Lead_SA atau Admin yang dapat menjalankan transisi status ini "
        "('Lost' atau 'Closed')."
    ),
}


async def _pastikan_syarat_submitted(db: AsyncSession, project: Project) -> None:
    """`Submitted` butuh PropTek, BOQ, dan Mandays masing-masing minimal `Reviewed` (400)."""
    hasil = await db.execute(
        select(Document.doc_type).where(
            Document.id_project == project.id_project,
            Document.doc_type.in_(DOKUMEN_WAJIB_SUBMITTED),
            Document.status.in_(STATUS_DOKUMEN_MINIMAL_REVIEWED),
        )
    )
    ada = set(hasil.scalars().all())
    kurang = [tipe for tipe in DOKUMEN_WAJIB_SUBMITTED if tipe not in ada]
    if kurang:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Status 'Submitted' butuh dokumen PropTek, BOQ, dan Mandays masing-masing "
                f"minimal berstatus 'Reviewed'. Belum terpenuhi: {', '.join(kurang)}."
            ),
        )


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


async def _penerima_hld(project: Project, db: AsyncSession) -> list[User]:
    """Semua SA proyek: SA utama dulu, lalu SA tambahan (`project_assignments`), tanpa ganda."""
    urutan_id: list = [] if project.assigned_sa is None else [project.assigned_sa]
    tambahan = await db.execute(
        select(ProjectAssignment.user_id)
        .where(ProjectAssignment.id_project == project.id_project)
        .order_by(ProjectAssignment.created_at)
    )
    urutan_id += [uid for uid in tambahan.scalars().all() if uid not in urutan_id]
    if not urutan_id:
        return []
    hasil = await db.execute(select(User).where(User.id.in_(urutan_id)))
    return sorted(hasil.scalars().all(), key=lambda u: urutan_id.index(u.id))


async def _notify_mandatory_hld(project: Project, db: AsyncSession) -> None:
    """
    Kirim notifikasi wajib "buat HLD" ke SEMUA SA proyek (SA utama dan SA tambahan, ADR 0014)
    saat proyek menjadi Won.

    Spec Flow 4 langkah 1. Memakai event `status_change` dengan flag
    `mandatory_hld` di metadata (event_type baru butuh migration CheckConstraint
    tanpa manfaat tambahan). Kegagalan di sini tidak boleh menggagalkan transisi, dan satu
    penerima yang gagal tidak menghalangi penerima lain.
    """
    try:
        penerima = await _penerima_hld(project, db)
    except Exception as e:  # noqa: BLE001 - side-effect tidak boleh menggagalkan transisi
        logger.error(f"Gagal menentukan penerima notifikasi wajib HLD {project.id_project}: {e}")
        return

    if not penerima:
        logger.warning(
            f"Proyek {project.id_project} Won tapi belum punya SA; "
            f"notifikasi wajib HLD dilewati."
        )
        return

    for sa_user in penerima:
        try:
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
            logger.error(
                f"Gagal mengirim notifikasi wajib HLD untuk {project.id_project} "
                f"ke {sa_user.id}: {e}"
            )


@router.patch(
    "/projects/{project_id}/status",
    summary="Ubah status proyek",
    description=(
        "Mengubah status proyek sesuai workflow yang valid. "
        "Mencatat perubahan di audit log. "
        "Hak per transisi (spec §2.0): Submitted/revisi oleh SA ditugaskan, Lead_SA, Admin; "
        "Won oleh Sales/Product PIC, Lead_SA, Admin; Lost dan Closed oleh Lead_SA/Admin "
        "(Lost wajib `reason`). Assigned lewat penugasan dan Handed Over lewat handover."
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
    2. Validasi hubungan user ke proyek (gerbang UBAH_STATUS)
    3. Validasi transisi (state machine), hak per transisi, lalu syarat (dokumen/alasan)
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

    # Transisi sah yang hanya boleh lewat endpoint khusus: arahkan, jangan hanya "tidak valid".
    endpoint_khusus = TRANSISI_VIA_ENDPOINT.get((old_status, new_status))
    if endpoint_khusus is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Status '{new_status}' tidak dapat diubah lewat endpoint ini. "
                f"Gunakan {endpoint_khusus}."
            ),
        )

    # Kembali ke `previous_status` (lanjut dari On Hold, buka kembali Closed/Lost): tujuannya
    # dinamis sehingga tidak ada di tabel `TRANSISI_HAK`.
    kembali = (
        old_status in _STATUS_KEMBALI
        and project.previous_status is not None
        and new_status == project.previous_status
    )

    # Validasi transisi menggunakan state machine
    tingkat_transisi = (
        _STATUS_KEMBALI[old_status] if kembali else hak_transisi(old_status, new_status)
    )
    if tingkat_transisi is None:
        valid_next = status_berikutnya(old_status, project.previous_status)
        valid_str = ", ".join(f"'{s}'" for s in valid_next) if valid_next else "tidak ada (status terminal)"

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Transisi status tidak valid: '{old_status}' → '{new_status}'. "
                f"Transisi yang diperbolehkan dari status '{old_status}': {valid_str}."
            ),
        )

    # Hak per transisi (spec §2.0): diperiksa SEBELUM syarat agar kondisi dokumen/alasan tidak
    # bocor ke peran yang tidak berhak.
    await ensure_project_access(
        db, project, current_user, tingkat_transisi, pesan=_PESAN_HAK_TRANSISI[tingkat_transisi]
    )

    # Buka kembali `Closed`/`Lost`: hanya `is_admin` (Lead_SA lolos tingkat di atas, bukan ini)
    # dan wajib beralasan; alasan masuk audit log.
    alasan = (body.reason or "").strip()
    buka_kembali = kembali and old_status in (status_konst.CLOSED, status_konst.LOST)
    if buka_kembali:
        if not adalah_admin(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Hanya Admin yang dapat membuka kembali proyek '{old_status}'.",
            )
        if not alasan:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Alasan (reason) wajib diisi untuk membuka kembali proyek '{old_status}'."
                ),
            )

    # Syarat transisi: `Submitted` butuh dokumen wajib; `Lost` wajib beralasan (CHECK
    # `chk_projects_lost_reason`) dan alasan disimpan di proyek.
    if new_status == status_konst.SUBMITTED:
        await _pastikan_syarat_submitted(db, project)
    if new_status == status_konst.LOST and not alasan:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Alasan (reason) wajib diisi untuk mengubah status proyek menjadi 'Lost'.",
        )

    # === 4. Update status proyek ===
    now = datetime.now(timezone.utc)
    nilai_baru: dict = {"status": new_status}
    if new_status == status_konst.LOST:
        # Dari On Hold: `previous_status` sudah menyimpan status sebelum jeda; jangan ditimpa
        # dengan 'On Hold' (CHECK `chk_projects_previous_status`).
        if old_status != status_konst.ON_HOLD:
            project.previous_status = old_status
        project.lost_reason = alasan
        nilai_baru["lost_reason"] = alasan
    elif new_status == status_konst.CLOSED:
        project.previous_status = old_status  # dipakai saat dibuka kembali
    elif new_status == status_konst.ON_HOLD:
        project.previous_status = old_status
        nilai_baru["aksi"] = "jeda"
        await sla_timer.jeda_timer(project_id, db)
    elif kembali:
        # Lanjut dari On Hold atau buka kembali: timer SLA yang dijeda berjalan lagi (juga bila
        # `Lost` datang dari `On Hold`, saat timer sengaja tetap berhenti).
        nilai_baru["aksi"] = "buka_kembali" if buka_kembali else "lanjut"
        project.previous_status = None
        await sla_timer.lanjutkan_timer(project_id, db)
    if alasan and "aksi" in nilai_baru:
        nilai_baru["reason"] = alasan
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
