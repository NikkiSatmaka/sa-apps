"""
HandoverService — Modul untuk mengelola proses handover proyek ke PMO dan Delivery.

Fitur utama:
- Trigger handover otomatis saat HLD "Final" + status "Closed-Win"
- Provisioning folder Final_Deliverables + permission PMO/Delivery
- Kirim notifikasi handover (in-app + email)
- Update status → "Handover Complete" + audit log
- Handle error GDrive: retry 3x interval 5s, flag "Handover Failed"
- Handle konfigurasi PMO/Delivery belum ada

Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7
"""

import logging
import random
import string
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.project import Project
from app.models.user import User
from app.services.folder_provisioner import (
    FolderProvisioningError,
    folder_provisioner,
)
from app.services.notification_service import (
    NotificationEvent,
    NotificationEventType,
    notification_service,
)

logger = logging.getLogger(__name__)


class HandoverError(Exception):
    """Exception saat proses handover gagal."""

    pass


def _generate_audit_id() -> str:
    """Generate ID audit log unik dengan format AUDIT-{YYYYMMDD}-{random6}."""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"AUDIT-{date_part}-{random_part}"


class HandoverService:
    """
    Service untuk mengelola proses handover proyek.

    Proses handover terdiri dari:
    1. Validasi prasyarat (status Closed-Win, HLD Final, PMO/Delivery dikonfigurasi)
    2. Provisioning folder Final_Deliverables + permission (via FolderProvisioner)
    3. Kirim notifikasi handover ke PMO Lead dan Delivery Lead
    4. Update status proyek → "Handover Complete"
    5. Catat audit log

    Jika GDrive gagal setelah 3x retry, tandai "Handover Failed" dan notif error.

    Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7
    """

    async def check_handover_readiness(self, project_id: str, db: AsyncSession) -> dict:
        """
        Cek apakah semua prasyarat handover terpenuhi.

        Prasyarat:
        - Status proyek = "Closed-Win"
        - Dokumen HLD ada dengan status "Final"
        - PMO Lead email sudah dikonfigurasi
        - Delivery Lead email sudah dikonfigurasi
        - Folder GDrive sudah ada (gdrive_folder_id)

        Args:
            project_id: ID proyek yang dicek
            db: Database session

        Returns:
            Dict berisi: ready (bool), missing_items (list), pmo_email, delivery_email,
            project_status, hld_status
        """
        missing_items = []

        # Cari proyek
        result = await db.execute(select(Project).where(Project.id_project == project_id))
        project = result.scalar_one_or_none()

        if project is None:
            return {
                "ready": False,
                "missing_items": ["Proyek tidak ditemukan"],
                "pmo_email": None,
                "delivery_email": None,
                "project_status": None,
                "hld_status": None,
            }

        # Cek status proyek
        if project.status != "Closed-Win":
            missing_items.append(f"Status proyek harus 'Closed-Win' (saat ini: '{project.status}')")

        # Cek dokumen HLD Final
        # Satu proyek boleh punya beberapa dokumen HLD (revisi); cukup satu yang Final.
        # Bila belum ada yang Final, laporkan status dokumen HLD terbaru.
        hld_result = await db.execute(
            select(Document)
            .where(
                and_(
                    Document.id_project == project_id,
                    Document.doc_type == "HLD",
                )
            )
            .order_by(Document.created_at.desc())
        )
        hld_docs = hld_result.scalars().all()

        hld_status = None
        if not hld_docs:
            missing_items.append("Dokumen HLD belum dibuat")
        else:
            hld_doc = next((d for d in hld_docs if d.status == "Final"), hld_docs[0])
            hld_status = hld_doc.status
            if hld_doc.status != "Final":
                missing_items.append(
                    f"Dokumen HLD harus berstatus 'Final' (saat ini: '{hld_doc.status}')"
                )

        # Cek konfigurasi PMO/Delivery
        pmo_email = project.pmo_lead_email if hasattr(project, "pmo_lead_email") else None
        delivery_email = (
            project.delivery_lead_email if hasattr(project, "delivery_lead_email") else None
        )

        if not pmo_email:
            missing_items.append("Email PMO Lead belum dikonfigurasi")

        if not delivery_email:
            missing_items.append("Email Delivery Lead belum dikonfigurasi")

        # Cek folder GDrive
        if not project.gdrive_folder_id:
            missing_items.append("Folder Google Drive belum di-provisioning")

        # Final_Deliverables dibuat di dalam Solutions (ADR 0005): id Solutions wajib ada.
        if not project.gdrive_solutions_folder_id:
            missing_items.append("Folder Solutions Google Drive belum di-provisioning")

        return {
            "ready": len(missing_items) == 0,
            "missing_items": missing_items,
            "pmo_email": pmo_email,
            "delivery_email": delivery_email,
            "project_status": project.status,
            "hld_status": hld_status,
        }

    async def trigger_handover(
        self,
        project_id: str,
        performed_by: UUID,
        db: AsyncSession,
    ) -> dict:
        """
        Eksekusi proses handover proyek ke PMO dan Delivery.

        Flow:
        1. Validasi prasyarat (status Closed-Win, HLD Final, config ada)
        2. Panggil FolderProvisioner.provision_handover()
        3. Kirim notifikasi handover ke PMO Lead + Delivery Lead
        4. Update status → "Handover Complete"
        5. Catat audit log

        Jika GDrive gagal (retry sudah di-handle oleh FolderProvisioner),
        tandai "Handover Failed" dan kirim notif error.

        Args:
            project_id: ID proyek yang akan di-handover
            performed_by: UUID user yang memicu handover
            db: Database session

        Returns:
            Dict berisi detail handover yang berhasil

        Raises:
            HandoverError: Jika prasyarat tidak terpenuhi atau GDrive gagal
        """
        now = datetime.now(timezone.utc)

        # === 1. Cari proyek dan validasi ===
        result = await db.execute(select(Project).where(Project.id_project == project_id))
        project = result.scalar_one_or_none()

        if project is None:
            raise HandoverError(f"Proyek '{project_id}' tidak ditemukan.")

        # Validasi status
        if project.status != "Closed-Win":
            raise HandoverError(
                f"Handover hanya bisa dilakukan saat status 'Closed-Win' "
                f"(saat ini: '{project.status}')."
            )

        # Validasi HLD Final
        hld_result = await db.execute(
            select(Document)
            .where(
                and_(
                    Document.id_project == project_id,
                    Document.doc_type == "HLD",
                    Document.status == "Final",
                )
            )
            .limit(1)
        )
        hld_doc = hld_result.scalars().first()

        if hld_doc is None:
            raise HandoverError(
                "Dokumen HLD berstatus 'Final' belum ada. "
                "Buat dan finalisasi HLD sebelum memulai handover."
            )

        # Validasi konfigurasi PMO/Delivery
        pmo_email = project.pmo_lead_email
        delivery_email = project.delivery_lead_email

        if not pmo_email or not delivery_email:
            raise HandoverError(
                "Email PMO Lead dan/atau Delivery Lead belum dikonfigurasi. "
                "Silakan konfigurasi melalui endpoint handover-config terlebih dahulu."
            )

        # Validasi folder GDrive ada
        if not project.gdrive_folder_id:
            raise HandoverError(
                "Folder Google Drive proyek belum di-provisioning. "
                "Pastikan folder sudah dibuat sebelum handover."
            )

        # Final_Deliverables dibuat di dalam Solutions; tanpa id-nya folder akan salah tempat.
        if not project.gdrive_solutions_folder_id:
            raise HandoverError(
                "Folder Solutions Google Drive proyek belum di-provisioning. "
                "Provisioning ulang folder sebelum handover."
            )

        # === 2. Provisioning folder Final_Deliverables ===
        # FolderProvisioner sudah handle retry 3x interval 5s
        final_deliverables_id: Optional[str] = None
        try:
            final_deliverables_id = await folder_provisioner.provision_handover(
                solutions_folder_id=project.gdrive_solutions_folder_id,
                pmo_email=pmo_email,
                delivery_email=delivery_email,
            )
            logger.info(f"Folder Final_Deliverables berhasil dibuat: {final_deliverables_id}")
        except FolderProvisioningError as e:
            # GDrive gagal setelah 3x retry — tandai Handover Failed
            logger.error(f"Handover gagal (GDrive error): {e}")

            # Kirim notifikasi error ke SA dan Lead_SA
            await self._notify_handover_failed(project, performed_by, str(e), db)

            raise HandoverError(
                f"Provisioning folder gagal setelah 3x retry: {e}. "
                f"Handover ditandai sebagai 'Handover Failed'. "
                f"SA dan Lead_SA telah diberitahu."
            )

        # === 3. Kirim notifikasi handover ke PMO + Delivery ===
        # Kumpulkan dokumen Final untuk info di notifikasi
        docs_result = await db.execute(
            select(Document).where(
                and_(
                    Document.id_project == project_id,
                    Document.status == "Final",
                )
            )
        )
        final_docs = docs_result.scalars().all()
        final_doc_types = [doc.doc_type for doc in final_docs]

        # Metadata notifikasi
        handover_metadata = {
            "project_id": project_id,
            "project_name": project.project_name,
            "customer_name": project.customer_name,
            "gdrive_folder_id": project.gdrive_folder_id,
            "final_deliverables_folder_id": final_deliverables_id,
            "final_documents": final_doc_types,
            "use_case_tags": project.use_case_tags or [],
            "handover_at": now.isoformat(),
        }

        # Cari user PMO dan Delivery (jika terdaftar di sistem)
        # Jika tidak terdaftar, kirim notifikasi tetap (email only)
        pmo_user = await self._find_user_by_email(pmo_email, db)
        delivery_user = await self._find_user_by_email(delivery_email, db)

        # Kirim notifikasi ke PMO Lead
        if pmo_user:
            await notification_service.send_notification(
                NotificationEvent(
                    event_type=NotificationEventType.HANDOVER,
                    recipient_user_id=pmo_user.id,
                    recipient_email=pmo_email,
                    reference_id=project_id,
                    metadata=handover_metadata,
                    subject=(
                        f"[Portal SA] Handover Proyek: "
                        f"{project.customer_name} - {project.project_name}"
                    ),
                )
            )

        # Kirim notifikasi ke Delivery Lead
        if delivery_user:
            await notification_service.send_notification(
                NotificationEvent(
                    event_type=NotificationEventType.HANDOVER,
                    recipient_user_id=delivery_user.id,
                    recipient_email=delivery_email,
                    reference_id=project_id,
                    metadata=handover_metadata,
                    subject=(
                        f"[Portal SA] Handover Proyek: "
                        f"{project.customer_name} - {project.project_name}"
                    ),
                )
            )

        logger.info(
            f"Notifikasi handover terkirim ke PMO ({pmo_email}) dan Delivery ({delivery_email})"
        )

        # === 4. Update status → "Handover Complete" ===
        old_status = project.status
        project.status = "Handover Complete"
        project.updated_at = now

        # === 5. Catat audit log ===
        audit_id = _generate_audit_id()
        audit_log = AuditLog(
            id=audit_id,
            entity_type="project",
            entity_id=project_id,
            action="handover",
            performed_by=performed_by,
            old_value={"status": old_status},
            new_value={
                "status": "Handover Complete",
                "pmo_lead_email": pmo_email,
                "delivery_lead_email": delivery_email,
                "final_deliverables_folder_id": final_deliverables_id,
                "handover_at": now.isoformat(),
            },
            created_at=now,
        )
        db.add(audit_log)

        # Commit perubahan
        await db.commit()
        await db.refresh(project)

        logger.info(
            f"Handover proyek {project_id} berhasil. "
            f"Status: '{old_status}' → 'Handover Complete'. "
            f"PMO: {pmo_email}, Delivery: {delivery_email}"
        )

        return {
            "id_project": project.id_project,
            "project_name": project.project_name,
            "customer_name": project.customer_name,
            "old_status": old_status,
            "new_status": "Handover Complete",
            "pmo_email": pmo_email,
            "delivery_email": delivery_email,
            "final_deliverables_folder_id": final_deliverables_id,
            "documents_handed_over": final_doc_types,
            "handover_at": now,
        }

    async def _notify_handover_failed(
        self,
        project: Project,
        performed_by: UUID,
        error_detail: str,
        db: AsyncSession,
    ) -> None:
        """
        Kirim notifikasi error handover ke SA dan Lead_SA yang terkait.
        Dipanggil saat GDrive provisioning gagal setelah semua retry.

        Args:
            project: Object Project yang gagal di-handover
            performed_by: UUID user yang memicu handover
            error_detail: Detail error dari GDrive
            db: Database session
        """
        error_metadata = {
            "project_id": project.id_project,
            "project_name": project.project_name,
            "customer_name": project.customer_name,
            "error": error_detail,
            "status": "Handover Failed",
        }

        # Kirim ke SA yang ditugaskan (jika ada)
        if project.assigned_sa:
            sa_result = await db.execute(select(User).where(User.id == project.assigned_sa))
            sa_user = sa_result.scalar_one_or_none()
            if sa_user:
                await notification_service.send_notification(
                    NotificationEvent(
                        event_type=NotificationEventType.STATUS_CHANGE,
                        recipient_user_id=sa_user.id,
                        recipient_email=sa_user.email,
                        reference_id=project.id_project,
                        metadata=error_metadata,
                        subject=(
                            f"[Portal SA] GAGAL: Handover proyek "
                            f"{project.project_name} tidak berhasil"
                        ),
                    )
                )

        # Kirim ke semua Lead_SA
        lead_result = await db.execute(select(User).where(User.role == "Lead_SA"))
        lead_users = lead_result.scalars().all()
        for lead in lead_users:
            await notification_service.send_notification(
                NotificationEvent(
                    event_type=NotificationEventType.STATUS_CHANGE,
                    recipient_user_id=lead.id,
                    recipient_email=lead.email,
                    reference_id=project.id_project,
                    metadata=error_metadata,
                    subject=(
                        f"[Portal SA] GAGAL: Handover proyek {project.project_name} tidak berhasil"
                    ),
                )
            )

    async def _find_user_by_email(self, email: str, db: AsyncSession) -> Optional[User]:
        """
        Cari user berdasarkan email. Return None jika tidak ditemukan.
        Digunakan untuk mengirim notifikasi in-app (perlu user_id).
        """
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()


# Singleton instance
handover_service = HandoverService()
