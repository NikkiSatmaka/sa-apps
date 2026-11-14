"""
SLA Timer — Modul tracking SLA DQ Number dengan auto-lock/unlock.

Mengelola countdown SLA sejak proyek di-assign ke SA.
Logic:
- Hari 0-2: Badge hijau (normal)
- Hari 3-4: Badge kuning + reminder ke Sales (trigger di hari ke-3)
- Hari 5+:  Badge merah + eskalasi (sekali) ke Lead SA dan Admin + auto-lock folder Solutions
            (lock dicoba ulang tiap siklus cron sampai berhasil)

Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.notification_log import NotificationLog
from app.models.project import Project
from app.models.sla_tracking import SLATracking
from app.models.user import User
from app.services.folder_provisioner import (
    FolderProvisioningError,
    folder_provisioner,
)
from app.services.notification_service import (
    NotificationEventType,
    notification_service,
)

logger = logging.getLogger(__name__)


class SLAStatus(str, Enum):
    """Status SLA berdasarkan jumlah hari elapsed."""

    GREEN = "green"  # 0-2 hari
    YELLOW = "yellow"  # 3-4 hari
    RED = "red"  # 5+ hari


# Threshold hari untuk perubahan status
SLA_YELLOW_THRESHOLD = 3  # Hari ke-3 mulai kuning
SLA_RED_THRESHOLD = 5  # Hari ke-5 mulai merah

# Retry configuration untuk GDrive operations
GDRIVE_MAX_RETRIES = 3
GDRIVE_RETRY_INTERVAL = 5  # detik


def _generate_id(prefix: str = "SLA") -> str:
    """Generate ID unik untuk record SLA tracking."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _calculate_sla_status(days_elapsed: int) -> SLAStatus:
    """
    Hitung status SLA berdasarkan jumlah hari elapsed.

    Args:
        days_elapsed: Jumlah hari sejak assignment

    Returns:
        SLAStatus: green (0-2), yellow (3-4), red (5+)
    """
    if days_elapsed < SLA_YELLOW_THRESHOLD:
        return SLAStatus.GREEN
    elif days_elapsed < SLA_RED_THRESHOLD:
        return SLAStatus.YELLOW
    else:
        return SLAStatus.RED


def hari_berjalan(sla, sekarang: datetime) -> int:
    """
    Hari SLA yang sudah berjalan, tanpa waktu jeda `On Hold` (issue #122).

    Waktu efektif = (jeda berjalan ? `paused_at` : `sekarang`) - `started_at` - akumulasi jeda
    yang sudah selesai (`paused_total_seconds`). Tidak pernah negatif.
    """
    akhir = sla.paused_at if sla.paused_at is not None else sekarang
    efektif = akhir - sla.started_at - timedelta(seconds=sla.paused_total_seconds)
    return max(0, efektif.days)


class SLATimer:
    """
    Mengelola SLA countdown DQ Number untuk proyek yang di-assign.

    Timer dimulai saat proyek berstatus 'Assigned' dan berhenti saat
    DQ Number diinput oleh Sales.

    Methods:
        start_timer: Mulai tracking SLA
        check_sla_status: Cek status SLA saat ini
        process_sla_actions: Proses semua proyek aktif (cron job)
        stop_timer: Hentikan timer saat DQ diinput
    """

    async def start_timer(
        self, project_id: str, assigned_at: datetime, db: AsyncSession
    ) -> SLATracking:
        """
        Mulai tracking SLA untuk proyek yang baru di-assign.

        Membuat record SLATracking baru dengan status 'green'.

        Args:
            project_id: ID proyek yang di-assign
            assigned_at: Timestamp assignment SA
            db: Database session

        Returns:
            SLATracking: Record yang baru dibuat
        """
        # Cek apakah sudah ada SLA tracker untuk proyek ini
        result = await db.execute(select(SLATracking).where(SLATracking.project_id == project_id))
        existing = result.scalar_one_or_none()

        if existing:
            logger.info(f"SLA tracker sudah ada untuk proyek {project_id}, skip pembuatan.")
            return existing

        # Buat record baru
        sla_record = SLATracking(
            id=_generate_id(),
            project_id=project_id,
            started_at=assigned_at,
            days_elapsed=0,
            current_status=SLAStatus.GREEN.value,
            is_locked=False,
            paused_total_seconds=0,
        )

        db.add(sla_record)
        await db.commit()
        await db.refresh(sla_record)

        logger.info(
            f"SLA timer dimulai untuk proyek {project_id}, assigned_at: {assigned_at.isoformat()}"
        )

        return sla_record

    async def check_sla_status(self, project_id: str, db: AsyncSession) -> Optional[dict]:
        """
        Hitung dan kembalikan status SLA saat ini untuk sebuah proyek.

        Args:
            project_id: ID proyek yang dicek
            db: Database session

        Returns:
            dict dengan info status SLA, atau None jika tidak ada tracker
        """
        result = await db.execute(select(SLATracking).where(SLATracking.project_id == project_id))
        sla = result.scalar_one_or_none()

        if sla is None:
            return None

        # Jika timer sudah dihentikan, kembalikan status terakhir
        if sla.stopped_at is not None:
            return {
                "project_id": project_id,
                "status": sla.current_status,
                "days_elapsed": sla.days_elapsed,
                "is_locked": sla.is_locked,
                "is_active": False,
                "is_paused": False,
                "started_at": sla.started_at.isoformat(),
                "stopped_at": sla.stopped_at.isoformat(),
            }

        # Hitung hari elapsed dari sekarang
        now = datetime.now(timezone.utc)
        days_elapsed = hari_berjalan(sla, now)
        current_status = _calculate_sla_status(days_elapsed)

        # Update record di database
        sla.days_elapsed = days_elapsed
        sla.current_status = current_status.value
        await db.commit()

        return {
            "project_id": project_id,
            "status": current_status.value,
            "days_elapsed": days_elapsed,
            "is_locked": sla.is_locked,
            "is_active": True,
            "is_paused": sla.paused_at is not None,
            "started_at": sla.started_at.isoformat(),
            "stopped_at": None,
        }

    async def process_sla_actions(self) -> dict:
        """
        Cron job: cek SEMUA proyek dengan SLA timer aktif dan trigger aksi.

        Aksi yang di-trigger:
        - Hari ke-3: Kirim reminder ke Sales (status → yellow)
        - Hari ke-5: Kirim eskalasi (SEKALI) ke Lead SA dan Admin + auto-lock folder Solutions.
          Bila lock gagal, hanya lock yang dicoba lagi di siklus berikutnya.
        - Tracker yang sudah berhenti (DQ diinput) tetapi foldernya masih terkunci karena unlock
          gagal: unlock dicoba lagi.

        Returns:
            dict: Ringkasan hasil proses (jumlah proyek diproses, reminder, eskalasi, lock,
            unlock yang berhasil dicoba ulang)
        """
        async with AsyncSessionLocal() as db:
            # Ambil semua SLA tracker yang masih aktif (belum stopped) dan tidak sedang dijeda
            # (`On Hold`): tracker yang dijeda tidak menembak reminder/eskalasi/lock.
            result = await db.execute(
                select(SLATracking).where(
                    SLATracking.stopped_at.is_(None), SLATracking.paused_at.is_(None)
                )
            )
            active_slas = result.scalars().all()

            stats = {
                "total_checked": 0,
                "reminders_sent": 0,
                "escalations_sent": 0,
                "locks_performed": 0,
                "unlocks_retried": 0,
                "errors": [],
            }

            now = datetime.now(timezone.utc)

            for sla in active_slas:
                stats["total_checked"] += 1

                try:
                    days_elapsed = hari_berjalan(sla, now)
                    new_status = _calculate_sla_status(days_elapsed)
                    old_status = sla.current_status

                    # Update days_elapsed dan status
                    sla.days_elapsed = days_elapsed
                    sla.current_status = new_status.value

                    # Ambil data proyek untuk notifikasi
                    project_result = await db.execute(
                        select(Project).where(Project.id_project == sla.project_id)
                    )
                    project = project_result.scalar_one_or_none()

                    if project is None:
                        logger.warning(
                            f"Proyek {sla.project_id} tidak ditemukan, skip SLA processing."
                        )
                        continue

                    # === Trigger reminder di hari ke-3 (yellow) ===
                    if days_elapsed >= SLA_YELLOW_THRESHOLD and old_status == SLAStatus.GREEN.value:
                        await self._send_sla_reminder(
                            project=project, days_elapsed=days_elapsed, db=db
                        )
                        stats["reminders_sent"] += 1

                    # === Trigger eskalasi + auto-lock di hari ke-5 (red) ===
                    if days_elapsed >= SLA_RED_THRESHOLD and not sla.is_locked:
                        # Eskalasi hanya sekali; bila lock gagal terus, siklus berikutnya hanya
                        # mengulang lock (tanpa membanjiri Lead SA/Admin/Sales dengan notifikasi).
                        if sla.escalated_at is None:
                            await self._send_sla_escalation(
                                project=project, days_elapsed=days_elapsed, db=db
                            )
                            sla.escalated_at = now
                            stats["escalations_sent"] += 1

                        # Auto-lock folder Solutions
                        lock_success = await self._lock_solutions_with_retry(
                            project=project, sla=sla, db=db
                        )
                        if lock_success:
                            stats["locks_performed"] += 1

                except Exception as e:
                    error_msg = f"Error processing SLA untuk proyek {sla.project_id}: {e}"
                    logger.error(error_msg)
                    stats["errors"].append(error_msg)

            await db.commit()

            # === Coba lagi unlock yang gagal saat DQ diinput (timer berhenti, folder terkunci) ===
            await self._coba_ulang_unlock_tertunda(db=db, now=now, stats=stats)

        logger.info(
            f"SLA processing selesai: {stats['total_checked']} dicek, "
            f"{stats['reminders_sent']} reminder, "
            f"{stats['escalations_sent']} eskalasi, "
            f"{stats['locks_performed']} lock."
        )

        return stats

    async def stop_timer(self, project_id: str, db: AsyncSession) -> Optional[SLATracking]:
        """
        Hentikan SLA timer saat DQ Number diinput.

        Jika folder sudah di-lock (H+5 sudah lewat), lakukan auto-unlock.

        Args:
            project_id: ID proyek yang DQ-nya baru diinput
            db: Database session

        Returns:
            SLATracking record yang di-update, atau None jika tidak ada tracker
        """
        result = await db.execute(select(SLATracking).where(SLATracking.project_id == project_id))
        sla = result.scalar_one_or_none()

        if sla is None:
            logger.info(f"Tidak ada SLA tracker untuk proyek {project_id}, skip stop.")
            return None

        # Jika sudah stopped sebelumnya, skip
        if sla.stopped_at is not None:
            logger.info(f"SLA timer untuk proyek {project_id} sudah dihentikan sebelumnya.")
            return sla

        now = datetime.now(timezone.utc)
        sla.stopped_at = now

        # Jika folder di-lock, lakukan auto-unlock. Bila gagal, timer tetap berhenti dan folder
        # tetap terkunci; `process_sla_actions` mencoba lagi pada siklus cron berikutnya.
        if sla.is_locked:
            await self._buka_kunci_dan_catat(project_id=project_id, sla=sla, now=now, db=db)

        await db.commit()
        await db.refresh(sla)

        logger.info(
            f"SLA timer dihentikan untuk proyek {project_id}. "
            f"Days elapsed: {sla.days_elapsed}, was_locked: {sla.is_locked}"
        )

        return sla

    async def jeda_timer(self, project_id: str, db: AsyncSession) -> Optional[SLATracking]:
        """
        Jeda timer saat proyek menjadi `On Hold` (issue #122). Idempoten.

        Tidak commit: pemanggil menyimpannya satu transaksi dengan perubahan status proyek.
        Tanpa tracker (proyek belum di-assign) atau tracker yang sudah berhenti: tidak ada
        yang dijeda dan return None.
        """
        sla = await self._tracker_aktif(project_id, db)
        if sla is None or sla.paused_at is not None:
            return sla
        sla.paused_at = datetime.now(timezone.utc)
        return sla

    async def lanjutkan_timer(self, project_id: str, db: AsyncSession) -> Optional[SLATracking]:
        """
        Lanjutkan timer yang dijeda: durasi jeda ditambahkan ke akumulasi sehingga batas H+3/H+5
        bergeser sebesar jeda (issue #122). Idempoten; tidak commit (lihat `jeda_timer`).
        """
        sla = await self._tracker_aktif(project_id, db)
        if sla is None or sla.paused_at is None:
            return sla
        sekarang = datetime.now(timezone.utc)
        sla.paused_total_seconds += max(0, int((sekarang - sla.paused_at).total_seconds()))
        sla.paused_at = None
        return sla

    # === Private helper methods ===

    async def _tracker_aktif(self, project_id: str, db: AsyncSession) -> Optional[SLATracking]:
        """Tracker proyek yang belum berhenti (DQ belum diinput), atau None."""
        result = await db.execute(select(SLATracking).where(SLATracking.project_id == project_id))
        sla = result.scalar_one_or_none()
        if sla is None or sla.stopped_at is not None:
            return None
        return sla

    async def _buka_kunci_dan_catat(
        self, project_id: str, sla: SLATracking, now: datetime, db: AsyncSession
    ) -> bool:
        """Unlock folder Solutions; bila berhasil perbarui tracker dan tulis audit. Return sukses."""
        if not await self._unlock_solutions_with_retry(project_id=project_id, sla=sla, db=db):
            return False

        sla.is_locked = False
        sla.unlocked_at = now
        await self._create_audit_log(
            entity_type="folder",
            entity_id=project_id,
            action="unlock",
            old_value={
                "is_locked": True,
                "locked_at": sla.locked_at.isoformat() if sla.locked_at else None,
            },
            new_value={
                "is_locked": False,
                "unlocked_at": now.isoformat(),
                "delay_days": sla.days_elapsed,
            },
            db=db,
        )
        return True

    async def _coba_ulang_unlock_tertunda(
        self, db: AsyncSession, now: datetime, stats: dict
    ) -> None:
        """Ulangi unlock untuk tracker yang sudah berhenti tetapi foldernya masih terkunci."""
        result = await db.execute(
            select(SLATracking).where(
                SLATracking.stopped_at.is_not(None), SLATracking.is_locked.is_(True)
            )
        )
        for sla in result.scalars().all():
            try:
                if await self._buka_kunci_dan_catat(
                    project_id=sla.project_id, sla=sla, now=now, db=db
                ):
                    stats["unlocks_retried"] += 1
            except Exception as e:  # noqa: BLE001 - satu proyek tak boleh menghentikan yang lain
                error_msg = f"Error unlock ulang untuk proyek {sla.project_id}: {e}"
                logger.error(error_msg)
                stats["errors"].append(error_msg)
        await db.commit()

    async def _send_sla_reminder(
        self, project: Project, days_elapsed: int, db: AsyncSession
    ) -> None:
        """
        Kirim notifikasi reminder SLA ke Sales yang bersangkutan.

        Args:
            project: Object Project
            days_elapsed: Jumlah hari elapsed
            db: Database session
        """
        if project.sales_pic is None:  # tanpa Sales (ADR 0014): penerima baru ditentukan di #120
            logger.info(f"Proyek {project.id_project} tanpa Sales PIC; reminder SLA dilewati.")
            return
        notification = NotificationLog(
            id=_generate_id("NOTIF"),
            event_type="sla_reminder",
            recipient_user_id=project.sales_pic,
            channel="in-app",
            status="sent",
            reference_id=project.id_project,
            notification_metadata={
                "project_name": project.project_name,
                "customer_name": project.customer_name,
                "days_elapsed": days_elapsed,
                "message": (
                    f"DQ Number untuk proyek '{project.project_name}' "
                    f"belum diinput selama {days_elapsed} hari. "
                    f"Harap segera input DQ Number."
                ),
            },
        )
        db.add(notification)
        await notification_service.dispatch_email_for_user(
            NotificationEventType.SLA_REMINDER,
            project.sales_pic,
            project.id_project,
            notification.notification_metadata,
        )

        logger.info(
            f"Reminder SLA dikirim ke Sales ({project.sales_pic}) "
            f"untuk proyek {project.id_project} (H+{days_elapsed})"
        )

    async def _send_sla_escalation(
        self, project: Project, days_elapsed: int, db: AsyncSession
    ) -> None:
        """
        Kirim notifikasi eskalasi SLA ke Lead SA dan Admin (penerima eskalasi; peran "Sales
        Manager" tidak ada di portal).

        Juga kirim notifikasi ke Sales yang bersangkutan bahwa
        folder Solutions akan di-lock.

        Args:
            project: Object Project
            days_elapsed: Jumlah hari elapsed
            db: Database session
        """
        # Penerima eskalasi: semua Lead_SA dan Admin
        manager_result = await db.execute(
            select(User).where(or_(User.role == "Lead_SA", User.is_admin.is_(True)))
        )
        managers = manager_result.scalars().all()

        for manager in managers:
            escalation_notif = NotificationLog(
                id=_generate_id("NOTIF"),
                event_type="sla_escalation",
                recipient_user_id=manager.id,
                channel="in-app",
                status="sent",
                reference_id=project.id_project,
                notification_metadata={
                    "project_name": project.project_name,
                    "customer_name": project.customer_name,
                    "days_elapsed": days_elapsed,
                    "sales_pic_id": str(project.sales_pic) if project.sales_pic else None,
                    "message": (
                        f"ESKALASI: DQ Number untuk proyek "
                        f"'{project.project_name}' ({project.customer_name}) "
                        f"belum diinput selama {days_elapsed} hari. "
                        f"Folder Solutions akan di-lock otomatis."
                    ),
                },
            )
            db.add(escalation_notif)
            await notification_service.dispatch_email_for_user(
                NotificationEventType.SLA_ESCALATION,
                manager.id,
                project.id_project,
                escalation_notif.notification_metadata,
            )

        # Notifikasi ke Sales bahwa folder akan di-lock (hanya bila project punya Sales)
        if project.sales_pic is not None:
            lock_notif = NotificationLog(
                id=_generate_id("NOTIF"),
                event_type="sla_escalation",
                recipient_user_id=project.sales_pic,
                channel="in-app",
                status="sent",
                reference_id=project.id_project,
                notification_metadata={
                    "project_name": project.project_name,
                    "days_elapsed": days_elapsed,
                    "message": (
                        f"Folder Solutions untuk proyek '{project.project_name}' "
                        f"telah di-lock karena DQ Number belum diinput "
                        f"selama {days_elapsed} hari. "
                        f"Input DQ Number untuk membuka kembali akses."
                    ),
                },
            )
            db.add(lock_notif)
            await notification_service.dispatch_email_for_user(
                NotificationEventType.SLA_ESCALATION,
                project.sales_pic,
                project.id_project,
                lock_notif.notification_metadata,
            )

        logger.info(
            f"Eskalasi SLA dikirim ke {len(managers)} manager(s) "
            f"untuk proyek {project.id_project} (H+{days_elapsed})"
        )

    async def _lock_solutions_with_retry(
        self, project: Project, sla: SLATracking, db: AsyncSession
    ) -> bool:
        """
        Lock folder Solutions via GDrive dengan retry 3x interval 5s.

        Args:
            project: Object Project
            sla: SLATracking record
            db: Database session

        Returns:
            bool: True jika berhasil lock, False jika gagal
        """
        if not project.gdrive_solutions_folder_id:
            logger.warning(
                f"Proyek {project.id_project} tidak punya gdrive_solutions_folder_id, "
                f"skip auto-lock."
            )
            return False

        # Ambil email Sales
        sales_result = await db.execute(select(User).where(User.id == project.sales_pic))
        sales_user = sales_result.scalar_one_or_none()

        if sales_user is None:
            logger.error(f"User Sales ({project.sales_pic}) tidak ditemukan, skip lock.")
            return False

        try:
            # folder_provisioner.lock_solutions_folder sudah punya retry internal
            # Tapi kita tetap panggil sesuai interface yang ada
            await folder_provisioner.lock_solutions_folder(
                solutions_folder_id=project.gdrive_solutions_folder_id,
                sales_email=sales_user.email,
            )

            # Update SLA record
            now = datetime.now(timezone.utc)
            sla.is_locked = True
            sla.locked_at = now

            # Catat audit log
            await self._create_audit_log(
                entity_type="folder",
                entity_id=project.id_project,
                action="lock",
                old_value={"is_locked": False},
                new_value={
                    "is_locked": True,
                    "locked_at": now.isoformat(),
                    "reason": "SLA DQ Number exceeded 5 days",
                    "days_elapsed": sla.days_elapsed,
                },
                db=db,
            )

            logger.info(
                f"Folder Solutions berhasil di-lock untuk proyek "
                f"{project.id_project} (H+{sla.days_elapsed})"
            )
            return True

        except FolderProvisioningError as e:
            logger.error(
                f"Gagal lock folder Solutions untuk proyek {project.id_project} setelah retry: {e}"
            )
            return False

    async def _unlock_solutions_with_retry(
        self, project_id: str, sla: SLATracking, db: AsyncSession
    ) -> bool:
        """
        Unlock folder Solutions via GDrive dengan retry 3x interval 5s.

        Dipanggil saat DQ Number diinput setelah folder sudah di-lock.

        Args:
            project_id: ID proyek
            sla: SLATracking record
            db: Database session

        Returns:
            bool: True jika berhasil unlock, False jika gagal
        """
        # Ambil data proyek
        project_result = await db.execute(select(Project).where(Project.id_project == project_id))
        project = project_result.scalar_one_or_none()

        if project is None or not project.gdrive_solutions_folder_id:
            logger.warning(
                f"Proyek {project_id} tidak ada atau belum punya folder Solutions, skip unlock."
            )
            return False

        # Ambil email Sales
        sales_result = await db.execute(select(User).where(User.id == project.sales_pic))
        sales_user = sales_result.scalar_one_or_none()

        if sales_user is None:
            logger.error(f"User Sales ({project.sales_pic}) tidak ditemukan, skip unlock.")
            return False

        try:
            # folder_provisioner.unlock_solutions_folder sudah punya retry internal
            await folder_provisioner.unlock_solutions_folder(
                solutions_folder_id=project.gdrive_solutions_folder_id,
                sales_email=sales_user.email,
            )

            logger.info(
                f"Folder Solutions berhasil di-unlock untuk proyek "
                f"{project_id} setelah DQ Number diinput."
            )
            return True

        except FolderProvisioningError as e:
            logger.error(
                f"Gagal unlock folder Solutions untuk proyek {project_id} setelah retry: {e}"
            )
            return False

    async def _create_audit_log(
        self,
        entity_type: str,
        entity_id: str,
        action: str,
        old_value: Optional[dict],
        new_value: dict,
        db: AsyncSession,
        performed_by: Optional[uuid.UUID] = None,
    ) -> None:
        """
        Buat entry audit log.

        Aksi otomatis (lock/unlock oleh cron SLA) tidak punya pelaku: `performed_by` NULL.
        Tidak ada user sistem palsu (ia akan ikut jadi penerima eskalasi Admin; issue #77).

        Args:
            entity_type: Tipe entitas (folder, project, dll)
            entity_id: ID entitas
            action: Aksi yang dilakukan
            old_value: Nilai sebelum perubahan
            new_value: Nilai setelah perubahan
            db: Database session
            performed_by: UUID user yang melakukan aksi, atau None untuk aksi otomatis
        """
        db.add(
            AuditLog(
                id=_generate_id("AUDIT"),
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                performed_by=performed_by,
                old_value=old_value,
                new_value=new_value,
            )
        )
        await db.flush()


# Singleton instance
sla_timer = SLATimer()
